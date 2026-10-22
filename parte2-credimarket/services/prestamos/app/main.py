import hashlib
import json
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from credimarket_common.auth import Principal, principal_actual, requiere_admin, requiere_servicio_o_admin
from credimarket_common.db import bd_lista, crear_engine, crear_sesiones, esperar_bd
from credimarket_common.web import configurar_cors, configurar_logging
from credimarket_ml.variables import CATEGORIAS_EMPLEO, PLAZOS_PERMITIDOS, validar_registro

from . import estados as E
from . import logica
from .integraciones import DependenciaNoDisponible, NoEncontrado, dependencias_disponibles, obtener_cliente, \
    obtener_cotizacion
from .modelo_ml import ModeloNoDisponible, modelo
from .modelos import Base, CambioEstado, Prediccion, Prestamo

configurar_logging("prestamos")
log = logging.getLogger("prestamos")

engine = crear_engine()
Sesiones = crear_sesiones(engine)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    esperar_bd(engine)
    Base.metadata.create_all(engine)
    try:
        modelo.cargar()  # una sola vez al iniciar; /ready informa si falló
    except ModeloNoDisponible:
        pass
    yield


app = FastAPI(title="CrediMarket - Préstamos", version="1.0.0", lifespan=lifespan)
configurar_cors(app)


def sesion():
    with Sesiones() as s:
        yield s


# ------------------------------------------------------------------ Esquemas
class SolicitudPrestamo(BaseModel):
    model_config = ConfigDict(extra="forbid")  # p. ej. un "precio" enviado por el cliente se rechaza
    producto_id: str = Field(min_length=36, max_length=36)
    cantidad: int = Field(ge=1, le=5)
    plazo_meses: int = Field(description=f"Uno de {PLAZOS_PERMITIDOS}")


class EntradaRiesgo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ingresos_mensuales_cop: int
    obligaciones_mensuales_cop: int
    antiguedad_laboral_meses: float | None = None
    meses_historial_crediticio: float | None = None
    creditos_previos: int
    atrasos_previos_30d: int
    porcentaje_pago_puntual: float | None = None
    monto_solicitado_cop: int
    plazo_meses: int
    tipo_empleo: str | None = Field(default=None, description=f"Uno de {CATEGORIAS_EMPLEO}")


def _hash_solicitud(datos: SolicitudPrestamo) -> str:
    return hashlib.sha256(json.dumps(datos.model_dump(), sort_keys=True).encode()).hexdigest()


def _autorizar(p: Principal, prestamo: Prestamo) -> None:
    if not (p.es_admin or prestamo.usuario_id == p.sub):
        raise HTTPException(403, "No puede consultar solicitudes de otro cliente")


def _respuesta(prestamo: Prestamo, repetida: bool = False) -> JSONResponse:
    codigo = 202 if prestamo.estado in (E.EVALUANDO, E.PENDIENTE_INVENTARIO) else 201
    if repetida:
        codigo = 200
    return JSONResponse(prestamo.a_dict(), status_code=codigo, headers={
        "Location": f"/prestamos/{prestamo.id}", "Idempotent-Replay": "true" if repetida else "false"})


# ------------------------------------------------------------------ Flujo de financiación
@app.post("/prestamos", status_code=202, responses={200: {"description": "Repetición idempotente"},
                                                    201: {"description": "Rechazada (estado final)"},
                                                    409: {"description": "Misma clave con contenido distinto"}})
def solicitar(datos: SolicitudPrestamo, s: Session = Depends(sesion), p: Principal = Depends(principal_actual),
              idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    if p.rol != "CLIENTE" or not p.cliente_id:
        raise HTTPException(403, "Solo un cliente autenticado puede solicitar financiación")
    if not idempotency_key or not (8 <= len(idempotency_key) <= 100):
        raise HTTPException(400, "El encabezado Idempotency-Key es obligatorio (8 a 100 caracteres)")
    huella = _hash_solicitud(datos)

    # 1. Tomar la clave de idempotencia (restricción UNIQUE durable en la base de datos).
    prestamo = Prestamo(id=str(uuid.uuid4()), usuario_id=p.sub, cliente_id=p.cliente_id,
                        idempotency_key=idempotency_key, request_hash=huella, correlation_id=idempotency_key,
                        producto_id=datos.producto_id, cantidad=datos.cantidad, plazo_meses=datos.plazo_meses,
                        estado=E.EVALUANDO, motivo="Solicitud recibida")
    try:
        with s.begin():
            s.add(prestamo)
            s.flush()
            s.add(CambioEstado(prestamo_id=prestamo.id, estado_anterior=None, estado_nuevo=E.EVALUANDO,
                               motivo="Solicitud recibida", origen="POST /prestamos"))
    except IntegrityError:
        s.rollback()
        existente = s.scalar(select(Prestamo).where(Prestamo.usuario_id == p.sub,
                                                    Prestamo.idempotency_key == idempotency_key))
        if existente is None:
            raise HTTPException(409, "Conflicto de concurrencia; reintente") from None
        if existente.request_hash != huella:
            raise HTTPException(409, "La Idempotency-Key ya se usó con un contenido distinto") from None
        if existente.estado != E.EVALUANDO:
            return _respuesta(existente, repetida=True)
        prestamo = existente  # la evaluación anterior no terminó: se reanuda

    # 2. Reunir datos por API (Clientes y Productos) y 3-4. evaluar riesgo y reglas.
    try:
        cliente = obtener_cliente(p.cliente_id)
        cotizacion = obtener_cotizacion(datos.producto_id)
        evaluacion = logica.evaluar(cliente, cotizacion, datos.cantidad, datos.plazo_meses)
    except NoEncontrado as exc:
        evaluacion = {"estado": E.RECHAZADA, "motivo": f"NO_ENCONTRADO: {exc} no encontró el recurso"}
    except DependenciaNoDisponible as exc:
        # La solicitud queda en EVALUANDO: reintentar con la MISMA clave reanuda la evaluación.
        raise HTTPException(503, f"{exc}. Reintente con la misma Idempotency-Key.") from None
    except ModeloNoDisponible as exc:
        raise HTTPException(503, f"Modelo de riesgo no disponible: {exc}") from None

    # 5. Guardar decisión y, si es favorable, publicar ReservaSolicitada (outbox, misma transacción).
    with s.begin():
        actual = s.get(Prestamo, prestamo.id, with_for_update=True, populate_existing=True)
        logica.aplicar_evaluacion(s, actual, evaluacion)
    s.refresh(actual)
    log.info("Préstamo %s -> %s (%s)", actual.id, actual.estado, actual.motivo)
    return _respuesta(actual)


@app.get("/prestamos")
def listar(estado: str | None = None, limite: int = Query(50, ge=1, le=200), s: Session = Depends(sesion),
           p: Principal = Depends(principal_actual)):
    q = select(Prestamo).order_by(Prestamo.creado_at.desc()).limit(limite)
    if not p.es_admin:
        q = q.where(Prestamo.usuario_id == p.sub)  # un cliente solo ve sus propias solicitudes
    if estado:
        q = q.where(Prestamo.estado == estado.upper())
    return [x.a_dict() for x in s.scalars(q)]


@app.get("/prestamos/{prestamo_id}")
def consultar(prestamo_id: str, s: Session = Depends(sesion), p: Principal = Depends(principal_actual)):
    prestamo = s.get(Prestamo, prestamo_id)
    if prestamo is None:
        raise HTTPException(404, "Solicitud no encontrada")
    _autorizar(p, prestamo)
    return prestamo.a_dict()


@app.get("/prestamos/{prestamo_id}/historial")
def historial(prestamo_id: str, s: Session = Depends(sesion), p: Principal = Depends(principal_actual)):
    prestamo = s.get(Prestamo, prestamo_id)
    if prestamo is None:
        raise HTTPException(404, "Solicitud no encontrada")
    _autorizar(p, prestamo)
    filas = s.scalars(select(CambioEstado).where(CambioEstado.prestamo_id == prestamo_id).order_by(CambioEstado.id))
    return [{"estado_anterior": c.estado_anterior, "estado_nuevo": c.estado_nuevo, "motivo": c.motivo,
             "origen": c.origen, "fecha": c.creado_at.isoformat()} for c in filas]


@app.post("/prestamos/{prestamo_id}/cancelar")
def cancelar(prestamo_id: str, s: Session = Depends(sesion), p: Principal = Depends(principal_actual)):
    with s.begin():
        prestamo = s.get(Prestamo, prestamo_id, with_for_update=True)
        if prestamo is None:
            raise HTTPException(404, "Solicitud no encontrada")
        _autorizar(p, prestamo)
        if prestamo.estado in (E.CANCELANDO, E.CANCELADA):
            return prestamo.a_dict()  # cancelar dos veces es idempotente
        if prestamo.estado not in E.CANCELABLES:
            raise HTTPException(409, f"No se puede cancelar una solicitud en estado {prestamo.estado}")
        quien = "administrador" if p.es_admin else "cliente"
        logica.cambiar_estado(s, prestamo, E.CANCELANDO, f"Cancelación solicitada por el {quien}",
                              f"POST /cancelar ({p.email})")
        logica.solicitar_liberacion(s, prestamo, f"cancelación del {quien}")
    return prestamo.a_dict()


# ------------------------------------------------------------------ Modelo de riesgo
@app.post("/riesgo/predict")
def predecir(entrada: EntradaRiesgo, s: Session = Depends(sesion),
             _p: Principal = Depends(requiere_servicio_o_admin)):
    """Prueba el pipeline con características válidas. No crea préstamos ni reserva inventario."""
    registro = entrada.model_dump()
    errores = validar_registro(registro)
    if errores:
        raise HTTPException(422, {"mensaje": "Entrada inválida", "errores": errores})
    try:
        r = modelo.predecir(registro)
    except ModeloNoDisponible as exc:
        raise HTTPException(503, f"Modelo no disponible: {exc}") from None
    with s.begin():
        s.add(Prediccion(origen="predict", model_version=r["model_version"], entrada=registro,
                         probabilidad=r["probabilidad_incumplimiento"], decision=r["decision_riesgo"],
                         umbral=r["umbral"]))
    return {**r, "nota": "La decisión de riesgo no es la aprobación final del préstamo."}


@app.get("/modelo/info")
def modelo_info():
    try:
        return modelo.info()
    except ModeloNoDisponible as exc:
        raise HTTPException(503, f"Modelo no disponible: {exc}") from None


@app.post("/modelo/recargar")
def modelo_recargar(_p: Principal = Depends(requiere_admin)):
    """Vuelve a leer registry/active.json (después de promover o hacer rollback)."""
    anterior = modelo.manifiesto["model_version"] if modelo.listo else None
    try:
        modelo.cargar()
    except ModeloNoDisponible as exc:
        raise HTTPException(503, f"No se pudo cargar el modelo: {exc}") from None
    return {"version_anterior": anterior, "version_activa": modelo.manifiesto["model_version"]}


@app.get("/modelo/monitoreo")
def monitoreo(ultimas: int = Query(500, ge=10, le=5000), s: Session = Depends(sesion),
              _p: Principal = Depends(requiere_admin)):
    """Monitoreo básico: volumen, tasa de riesgo alto y drift (PSI) de las últimas predicciones."""
    filas = s.execute(select(Prediccion.entrada, Prediccion.probabilidad, Prediccion.decision,
                             Prediccion.model_version).order_by(Prediccion.id.desc()).limit(ultimas)).all()
    psi = modelo.psi([f.entrada for f in filas]) if len(filas) >= 10 else {}
    alertas = [f"{k}: PSI={v} (drift significativo)" for k, v in psi.items() if v >= 0.25]
    alertas += [f"{k}: PSI={v} (drift moderado)" for k, v in psi.items() if 0.1 <= v < 0.25]
    por_estado = dict(s.execute(select(Prestamo.estado, func.count()).group_by(Prestamo.estado)).all())
    return {
        "predicciones_analizadas": len(filas),
        "probabilidad_media": round(sum(f.probabilidad for f in filas) / len(filas), 4) if filas else None,
        "tasa_riesgo_alto": round(sum(f.decision == "ALTO" for f in filas) / len(filas), 4) if filas else None,
        "versiones": sorted({f.model_version for f in filas}),
        "psi": psi, "alertas_drift": alertas,
        "interpretacion_psi": "< 0.1 estable; 0.1-0.25 moderado; >= 0.25 significativo",
        "prestamos_por_estado": por_estado,
    }


# ------------------------------------------------------------------ Salud
@app.get("/health")
def health():
    return {"estado": "ok", "servicio": "prestamos"}


@app.get("/ready")
def ready(response: Response):
    bd = bd_lista(engine)
    deps = dependencias_disponibles()
    listo = bd and modelo.listo and all(deps.values())
    if not listo:
        response.status_code = 503
    return {"estado": "listo" if listo else "no disponible", "base_datos": bd, "modelo": modelo.listo,
            "modelo_version": modelo.manifiesto["model_version"] if modelo.listo else None,
            "modelo_error": modelo.error, **deps}
