"""Reglas de negocio de Préstamos: evaluación, cambios de estado y reacción a eventos de Inventario."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from credimarket_common.config import entero
from credimarket_common.mensajeria import EX_COMANDOS, RK_LIBERAR, RK_RESERVAR, crear_mensaje, encolar
from credimarket_ml.variables import ESPECIFICACION, PLAZOS_PERMITIDOS, cuota_mensual, validar_registro

from . import estados as E
from .modelo_ml import modelo
from .modelos import CambioEstado, Prediccion, Prestamo, outbox

log = logging.getLogger(__name__)

MONTO_MIN = ESPECIFICACION["monto_solicitado_cop"]["min"]
MONTO_MAX = ESPECIFICACION["monto_solicitado_cop"]["max"]
CARGA_MAXIMA = entero("CARGA_FINANCIERA_MAXIMA_PCT", 70) / 100
PENDIENTE_TIMEOUT = entero("PENDIENTE_TIMEOUT_SEGUNDOS", 600)
EVALUANDO_TIMEOUT = entero("EVALUANDO_TIMEOUT_SEGUNDOS", 300)
CANCELANDO_REINTENTO = entero("CANCELANDO_REINTENTO_SEGUNDOS", 120)


def cambiar_estado(s: Session, p: Prestamo, nuevo: str, motivo: str | None, origen: str) -> None:
    E.validar_transicion(p.estado, nuevo)
    s.add(CambioEstado(prestamo_id=p.id, estado_anterior=p.estado, estado_nuevo=nuevo, motivo=motivo, origen=origen))
    p.estado = nuevo
    p.motivo = motivo
    p.actualizado_at = datetime.now(timezone.utc)


def solicitar_liberacion(s: Session, p: Prestamo, motivo: str) -> None:
    encolar(s, outbox, EX_COMANDOS, RK_LIBERAR, crear_mensaje(
        "LiberacionSolicitada", p.id, p.correlation_id, {"producto_id": p.producto_id, "motivo": motivo}))


# ------------------------------------------------------------------ Evaluación
def construir_caracteristicas(cliente: dict, monto: int, plazo: int) -> dict:
    """Mismas variables de entrada que en el entrenamiento (ver credimarket_ml.variables)."""
    return {
        "ingresos_mensuales_cop": cliente.get("ingresos_mensuales_cop"),
        "obligaciones_mensuales_cop": cliente.get("obligaciones_mensuales_cop"),
        "antiguedad_laboral_meses": cliente.get("antiguedad_laboral_meses"),
        "meses_historial_crediticio": cliente.get("meses_historial_crediticio"),
        "creditos_previos": cliente.get("creditos_previos"),
        "atrasos_previos_30d": cliente.get("atrasos_previos_30d"),
        "porcentaje_pago_puntual": cliente.get("porcentaje_pago_puntual"),
        "monto_solicitado_cop": monto,
        "plazo_meses": plazo,
        "tipo_empleo": cliente.get("tipo_empleo"),
    }


def evaluar(cliente: dict, cotizacion: dict, cantidad: int, plazo: int) -> dict:
    """Devuelve el resultado de la evaluación SIN escribir en la base de datos.

    Orden: datos mínimos -> modelo de riesgo -> reglas de negocio.
    """
    res: dict = {"precio_unitario": cotizacion["precio"], "version_producto": cotizacion["version"],
                 "cotizado_at": cotizacion["cotizado_at"], "producto_nombre": cotizacion["nombre"]}
    monto = int(cotizacion["precio"]) * cantidad  # el monto nunca lo decide el cliente
    res["monto"] = monto
    res["cuota_estimada"] = round(float(cuota_mensual(monto, plazo)), 2)

    if not cotizacion["activo"]:
        return {**res, "estado": E.RECHAZADA, "motivo": "PRODUCTO_NO_DISPONIBLE: el producto está inactivo"}
    if not cliente.get("activo", False):
        return {**res, "estado": E.RECHAZADA, "motivo": "CLIENTE_INACTIVO"}
    if plazo not in PLAZOS_PERMITIDOS:
        return {**res, "estado": E.RECHAZADA, "motivo": f"PLAZO_INVALIDO: permitidos {PLAZOS_PERMITIDOS}"}
    if not (MONTO_MIN <= monto <= MONTO_MAX):
        return {**res, "estado": E.RECHAZADA,
                "motivo": f"MONTO_FUERA_DE_RANGO: {monto:,} COP (permitido {MONTO_MIN:,} a {MONTO_MAX:,})"}

    caracteristicas = construir_caracteristicas(cliente, monto, plazo)
    errores = validar_registro(caracteristicas)
    if errores:
        return {**res, "estado": E.RECHAZADA, "motivo": "INFORMACION_INSUFICIENTE: " + "; ".join(errores)}

    riesgo = modelo.predecir(caracteristicas)
    ingresos = float(caracteristicas["ingresos_mensuales_cop"])
    carga = (float(caracteristicas["obligaciones_mensuales_cop"]) + res["cuota_estimada"]) / ingresos
    res.update({"caracteristicas": caracteristicas, "riesgo": riesgo, "carga_financiera": round(carga, 4)})

    if riesgo["decision_riesgo"] == "ALTO":
        return {**res, "estado": E.RECHAZADA,
                "motivo": f"RIESGO_ALTO: probabilidad {riesgo['probabilidad_incumplimiento']:.3f} >= umbral "
                          f"{riesgo['umbral']:.2f}"}
    if carga > CARGA_MAXIMA:
        return {**res, "estado": E.RECHAZADA,
                "motivo": f"CAPACIDAD_DE_PAGO: carga financiera {carga:.0%} supera el máximo {CARGA_MAXIMA:.0%}"}
    return {**res, "estado": E.PENDIENTE_INVENTARIO, "motivo": "Riesgo favorable; esperando reserva de inventario"}


def aplicar_evaluacion(s: Session, p: Prestamo, ev: dict) -> bool:
    """Guarda el resultado y, si es favorable, publica ReservaSolicitada (misma transacción)."""
    if p.estado != E.EVALUANDO:
        return False  # otra petición concurrente con la misma clave ya terminó la evaluación
    for campo in ("precio_unitario", "version_producto", "cotizado_at", "producto_nombre", "monto",
                  "cuota_estimada", "carga_financiera"):
        if campo in ev:
            setattr(p, campo, ev[campo])
    if "riesgo" in ev:
        r = ev["riesgo"]
        p.probabilidad_incumplimiento = r["probabilidad_incumplimiento"]
        p.decision_riesgo, p.umbral = r["decision_riesgo"], r["umbral"]
        p.model_version, p.model_run_id = r["model_version"], r["run_id"]
        s.add(Prediccion(origen="prestamo", prestamo_id=p.id, model_version=r["model_version"],
                         entrada=ev["caracteristicas"], probabilidad=r["probabilidad_incumplimiento"],
                         decision=r["decision_riesgo"], umbral=r["umbral"]))
    cambiar_estado(s, p, ev["estado"], ev["motivo"], "evaluacion")
    if ev["estado"] == E.PENDIENTE_INVENTARIO:
        # A Inventario solo viaja lo que necesita: nada de información financiera del cliente.
        encolar(s, outbox, EX_COMANDOS, RK_RESERVAR, crear_mensaje(
            "ReservaSolicitada", p.id, p.correlation_id, {"producto_id": p.producto_id, "cantidad": p.cantidad}))
    return True


# ------------------------------------------------------------------ Eventos de Inventario
def _prestamo(s: Session, prestamo_id: str) -> Prestamo | None:
    return s.get(Prestamo, prestamo_id, with_for_update=True)


def al_inventario_reservado(m: dict, s: Session) -> str:
    p = _prestamo(s, m["prestamo_id"])
    if p is None:
        return "prestamo-desconocido"
    if p.estado == E.PENDIENTE_INVENTARIO:
        p.reserva_id = m["payload"]["reserva_id"]
        p.reserva_expira_at = m["payload"].get("expira_at")
        cambiar_estado(s, p, E.APROBADA, "Inventario confirmó la reserva", "InventarioReservado")
        return "aprobada"
    if p.estado in (E.CANCELADA, E.CANCELADA_SIN_STOCK, E.RECHAZADA):
        # Evento tardío: NUNCA reactiva el préstamo. Por seguridad se pide liberar esa reserva.
        solicitar_liberacion(s, p, "reserva tardía de un préstamo ya finalizado")
        return f"tardio-ignorado-en-{p.estado}-liberacion-solicitada"
    return f"ignorado-en-{p.estado}"  # APROBADA (duplicado) o CANCELANDO (la liberación ya está en camino)


def al_inventario_insuficiente(m: dict, s: Session) -> str:
    p = _prestamo(s, m["prestamo_id"])
    if p is None:
        return "prestamo-desconocido"
    if p.estado == E.PENDIENTE_INVENTARIO:
        disp = m["payload"].get("disponible")
        cambiar_estado(s, p, E.CANCELADA_SIN_STOCK, f"Sin existencias suficientes (disponibles: {disp})",
                       "InventarioInsuficiente")
        return "cancelada-sin-stock"
    if p.estado == E.CANCELANDO:
        cambiar_estado(s, p, E.CANCELADA, "Cancelado por el usuario (no había reserva que liberar)",
                       "InventarioInsuficiente")
        return "cancelada"
    return f"ignorado-en-{p.estado}"


def al_reserva_liberada(m: dict, s: Session) -> str:
    p = _prestamo(s, m["prestamo_id"])
    if p is None:
        return "prestamo-desconocido"
    if p.estado == E.CANCELANDO:
        cambiar_estado(s, p, E.CANCELADA, f"{p.motivo or 'Cancelado'} — reserva liberada", "ReservaLiberada")
        return "cancelada"
    return f"ignorado-en-{p.estado}"


def al_reserva_vencida(m: dict, s: Session) -> str:
    p = _prestamo(s, m["prestamo_id"])
    if p is None:
        return "prestamo-desconocido"
    if p.estado in (E.APROBADA, E.CANCELANDO):
        # Un préstamo aprobado no puede conservar una reserva inexistente.
        cambiar_estado(s, p, E.CANCELADA, "RESERVA_VENCIDA: la reserva expiró antes de la entrega", "ReservaVencida")
        return "cancelada-por-vencimiento"
    return f"ignorado-en-{p.estado}"


def al_salida_confirmada(m: dict, s: Session) -> str:
    p = _prestamo(s, m["prestamo_id"])
    if p is None:
        return "prestamo-desconocido"
    if p.estado == E.APROBADA:
        cambiar_estado(s, p, E.COMPLETADA, "Entrega confirmada por Inventario", "SalidaConfirmada")
        return "completada"
    if p.estado == E.CANCELANDO:
        cambiar_estado(s, p, E.COMPLETADA, "La entrega ocurrió antes de procesar la cancelación", "SalidaConfirmada")
        return "completada-entrega-previa-a-cancelacion"
    return f"ignorado-en-{p.estado}"


MANEJADORES = {
    "InventarioReservado": al_inventario_reservado,
    "InventarioInsuficiente": al_inventario_insuficiente,
    "ReservaLiberada": al_reserva_liberada,
    "ReservaVencida": al_reserva_vencida,
    "SalidaConfirmada": al_salida_confirmada,
}


# ------------------------------------------------------------------ Tiempos de espera
def revisar_tiempos(s: Session) -> dict:
    ahora = datetime.now(timezone.utc)
    conteo = {"pendientes_vencidos": 0, "evaluaciones_abandonadas": 0, "liberaciones_reenviadas": 0}
    for p in s.scalars(select(Prestamo).where(Prestamo.estado == E.PENDIENTE_INVENTARIO,
                                              Prestamo.actualizado_at < ahora - timedelta(seconds=PENDIENTE_TIMEOUT))
                       .with_for_update(skip_locked=True).limit(100)):
        cambiar_estado(s, p, E.CANCELANDO, "TIEMPO_ESPERA_INVENTARIO: Inventario no respondió a tiempo", "temporizador")
        solicitar_liberacion(s, p, "tiempo de espera agotado")
        conteo["pendientes_vencidos"] += 1
    for p in s.scalars(select(Prestamo).where(Prestamo.estado == E.EVALUANDO,
                                              Prestamo.creado_at < ahora - timedelta(seconds=EVALUANDO_TIMEOUT))
                       .with_for_update(skip_locked=True).limit(100)):
        cambiar_estado(s, p, E.RECHAZADA, "EVALUACION_INCOMPLETA: no se completó la evaluación a tiempo",
                       "temporizador")
        conteo["evaluaciones_abandonadas"] += 1
    for p in s.scalars(select(Prestamo).where(Prestamo.estado == E.CANCELANDO,
                                              Prestamo.actualizado_at < ahora - timedelta(seconds=CANCELANDO_REINTENTO))
                       .with_for_update(skip_locked=True).limit(100)):
        solicitar_liberacion(s, p, "reintento de liberación")  # idempotente en Inventario
        p.actualizado_at = ahora
        conteo["liberaciones_reenviadas"] += 1
    return conteo
