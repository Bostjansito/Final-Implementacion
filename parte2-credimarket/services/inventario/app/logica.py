"""Reglas de negocio de Inventario, compartidas por la API y el worker.

Cada función recibe una sesión con una transacción abierta: el cambio de
existencias, la reserva, el movimiento y el mensaje del outbox se confirman
juntos o no se confirma ninguno.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from credimarket_common.config import entero
from credimarket_common.mensajeria import EX_EVENTOS, crear_mensaje, encolar

from .modelos import Existencia, Movimiento, Reserva, outbox

RESERVA_TTL = entero("RESERVA_TTL_SEGUNDOS", 1800)

ACTIVA, CONFIRMADA, LIBERADA, VENCIDA, RECHAZADA = "ACTIVA", "CONFIRMADA", "LIBERADA", "VENCIDA", "RECHAZADA"


def _publicar(s: Session, tipo: str, rk: str, prestamo_id: str, correlation_id: str, payload: dict) -> None:
    encolar(s, outbox, EX_EVENTOS, rk, crear_mensaje(tipo, prestamo_id, correlation_id, payload))


def _evento_reservado(s: Session, r: Reserva, correlation_id: str) -> None:
    _publicar(s, "InventarioReservado", "inventario.reservado", r.prestamo_id, correlation_id, {
        "reserva_id": r.id, "producto_id": r.producto_id, "cantidad": r.cantidad,
        "expira_at": r.expira_at.isoformat(),
    })


def _evento_liberada(s: Session, r: Reserva, correlation_id: str, liberado: int) -> None:
    _publicar(s, "ReservaLiberada", "inventario.liberada", r.prestamo_id, correlation_id, {
        "reserva_id": r.id, "producto_id": r.producto_id, "cantidad_liberada": liberado,
        "estado_reserva": r.estado,
    })


def _evento_salida(s: Session, r: Reserva, correlation_id: str) -> None:
    _publicar(s, "SalidaConfirmada", "inventario.salida_confirmada", r.prestamo_id, correlation_id, {
        "reserva_id": r.id, "producto_id": r.producto_id, "cantidad": r.cantidad,
    })


def _mover(s: Session, producto_id: str, d_disponible: int, d_reservado: int) -> bool:
    """Ajusta existencias de forma atómica. Devuelve False si dejaría valores negativos."""
    condiciones = [Existencia.producto_id == producto_id]
    if d_disponible < 0:
        condiciones.append(Existencia.disponible >= -d_disponible)
    if d_reservado < 0:
        condiciones.append(Existencia.reservado >= -d_reservado)
    res = s.execute(update(Existencia).where(*condiciones).values(
        disponible=Existencia.disponible + d_disponible, reservado=Existencia.reservado + d_reservado))
    return res.rowcount == 1


def reservar(s: Session, prestamo_id: str, producto_id: str, cantidad: int, correlation_id: str) -> str:
    existente = s.scalar(select(Reserva).where(Reserva.prestamo_id == prestamo_id).with_for_update())
    if existente is not None:
        # Comando repetido: no se vuelve a reservar; se reenvía el resultado ya conocido.
        if existente.estado == ACTIVA:
            _evento_reservado(s, existente, correlation_id)
            return "reserva-existente-reenviada"
        if existente.estado == RECHAZADA:
            _publicar(s, "InventarioInsuficiente", "inventario.insuficiente", prestamo_id, correlation_id,
                      {"producto_id": producto_id, "cantidad_solicitada": cantidad, "disponible": None})
            return "rechazo-existente-reenviado"
        return f"ignorado-reserva-{existente.estado.lower()}"

    if cantidad > 0 and _mover(s, producto_id, -cantidad, +cantidad):
        r = Reserva(id=str(uuid.uuid4()), prestamo_id=prestamo_id, producto_id=producto_id, cantidad=cantidad,
                    estado=ACTIVA, correlation_id=correlation_id,
                    expira_at=datetime.now(timezone.utc) + timedelta(seconds=RESERVA_TTL))
        s.add(r)
        s.add(Movimiento(producto_id=producto_id, tipo="RESERVA", cantidad=cantidad, reserva_id=r.id,
                         prestamo_id=prestamo_id, realizado_por="sistema"))
        s.flush()
        _evento_reservado(s, r, correlation_id)
        return "reservado"

    disponible = s.scalar(select(Existencia.disponible).where(Existencia.producto_id == producto_id))
    s.add(Reserva(id=str(uuid.uuid4()), prestamo_id=prestamo_id, producto_id=producto_id, cantidad=cantidad,
                  estado=RECHAZADA, motivo="existencias insuficientes", correlation_id=correlation_id))
    _publicar(s, "InventarioInsuficiente", "inventario.insuficiente", prestamo_id, correlation_id,
              {"producto_id": producto_id, "cantidad_solicitada": cantidad, "disponible": disponible or 0})
    return "insuficiente"


def liberar(s: Session, prestamo_id: str, producto_id: str, correlation_id: str, motivo: str) -> str:
    r = s.scalar(select(Reserva).where(Reserva.prestamo_id == prestamo_id).with_for_update())
    if r is None:
        # La liberación llegó antes que la reserva: se deja una "lápida" para que una
        # ReservaSolicitada tardía no reserve unidades de un préstamo ya cancelado.
        r = Reserva(id=str(uuid.uuid4()), prestamo_id=prestamo_id, producto_id=producto_id, cantidad=0,
                    estado=LIBERADA, motivo=f"liberada antes de reservar: {motivo}", correlation_id=correlation_id)
        s.add(r)
        s.flush()
        _evento_liberada(s, r, correlation_id, 0)
        return "lapida-creada"
    if r.estado == ACTIVA:
        if not _mover(s, r.producto_id, +r.cantidad, -r.cantidad):
            raise RuntimeError("Inconsistencia: unidades reservadas menores que la reserva")
        r.estado, r.motivo = LIBERADA, motivo
        s.add(Movimiento(producto_id=r.producto_id, tipo="LIBERACION", cantidad=r.cantidad, reserva_id=r.id,
                         prestamo_id=prestamo_id, nota=motivo, realizado_por="sistema"))
        s.flush()
        _evento_liberada(s, r, correlation_id, r.cantidad)
        return "liberada"
    if r.estado == CONFIRMADA:
        # La entrega ya ocurrió: se informa a Préstamos para que el estado sea coherente.
        _evento_salida(s, r, correlation_id)
        return "ya-entregada"
    _evento_liberada(s, r, correlation_id, 0)
    return f"sin-unidades-que-liberar-{r.estado.lower()}"


def confirmar_salida(s: Session, reserva_id: str, por: str) -> Reserva:
    r = s.get(Reserva, reserva_id, with_for_update=True)
    if r is None:
        raise LookupError("Reserva no encontrada")
    if r.estado != ACTIVA:
        raise ValueError(f"La reserva está {r.estado}; solo se entrega una reserva ACTIVA")
    if r.expira_at and r.expira_at <= datetime.now(timezone.utc):
        raise ValueError("La reserva venció; no puede entregarse")
    if not _mover(s, r.producto_id, 0, -r.cantidad):
        raise RuntimeError("Inconsistencia: unidades reservadas menores que la reserva")
    r.estado, r.motivo = CONFIRMADA, f"entregada por {por}"
    s.add(Movimiento(producto_id=r.producto_id, tipo="SALIDA", cantidad=r.cantidad, reserva_id=r.id,
                     prestamo_id=r.prestamo_id, realizado_por=por))
    s.flush()
    _evento_salida(s, r, r.correlation_id or r.prestamo_id)
    return r


def vencer_reservas(s: Session, limite: int = 100) -> int:
    vencidas = s.scalars(select(Reserva).where(Reserva.estado == ACTIVA,
                                               Reserva.expira_at < datetime.now(timezone.utc))
                         .limit(limite).with_for_update(skip_locked=True)).all()
    for r in vencidas:
        if not _mover(s, r.producto_id, +r.cantidad, -r.cantidad):
            raise RuntimeError("Inconsistencia al vencer reserva")
        r.estado, r.motivo = VENCIDA, "tiempo de reserva agotado"
        s.add(Movimiento(producto_id=r.producto_id, tipo="VENCIMIENTO", cantidad=r.cantidad, reserva_id=r.id,
                         prestamo_id=r.prestamo_id, realizado_por="sistema"))
        _publicar(s, "ReservaVencida", "inventario.vencida", r.prestamo_id, r.correlation_id or r.prestamo_id,
                  {"reserva_id": r.id, "producto_id": r.producto_id, "cantidad": r.cantidad})
    return len(vencidas)


def registrar_entrada(s: Session, producto_id: str, cantidad: int, nota: str | None, por: str) -> Existencia:
    e = s.get(Existencia, producto_id, with_for_update=True)
    if e is None:
        e = Existencia(producto_id=producto_id, disponible=0, reservado=0)
        s.add(e)
        s.flush()
    e.disponible += cantidad
    s.add(Movimiento(producto_id=producto_id, tipo="ENTRADA", cantidad=cantidad, nota=nota, realizado_por=por))
    return e
