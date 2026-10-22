import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from credimarket_common.auth import Principal, requiere_admin, token_servicio
from credimarket_common.db import bd_lista, crear_engine, crear_sesiones, esperar_bd
from credimarket_common.semillas import CATALOGO, id_producto
from credimarket_common.web import configurar_cors, configurar_logging

from . import logica
from .modelos import Base, Existencia, Movimiento, Reserva

configurar_logging("inventario")
log = logging.getLogger("inventario")

engine = crear_engine()
Sesiones = crear_sesiones(engine)
PRODUCTOS_URL = os.environ.get("PRODUCTOS_URL", "http://productos:8000")


def sembrar() -> None:
    with Sesiones() as s, s.begin():
        if s.scalar(select(Existencia.producto_id).limit(1)):
            return
        for sku, _n, _c, _p, stock, _d in CATALOGO:
            logica.registrar_entrada(s, id_producto(sku), stock, "inventario inicial", "semilla")
        log.info("Existencias iniciales sembradas")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    esperar_bd(engine)
    Base.metadata.create_all(engine)
    sembrar()
    yield


app = FastAPI(title="CrediMarket - Inventario", version="1.0.0", lifespan=lifespan)
configurar_cors(app)


def sesion():
    with Sesiones() as s:
        yield s


class Entrada(BaseModel):
    producto_id: str = Field(min_length=36, max_length=36)
    cantidad: int = Field(gt=0, le=10_000)
    nota: str | None = Field(default=None, max_length=300)


@app.get("/inventario/existencias")
def existencias(s: Session = Depends(sesion), _p: Principal = Depends(requiere_admin)):
    return [{"producto_id": e.producto_id, "disponible": e.disponible, "reservado": e.reservado,
             "actualizado_at": e.actualizado_at.isoformat()} for e in s.scalars(select(Existencia))]


@app.get("/inventario/existencias/{producto_id}")
def existencia(producto_id: str, s: Session = Depends(sesion)):
    """Disponibilidad pública (informativa: la reserva real ocurre al procesar el préstamo)."""
    e = s.get(Existencia, producto_id)
    return {"producto_id": producto_id, "disponible": e.disponible if e else 0}


@app.post("/inventario/entradas", status_code=201)
def entrada(datos: Entrada, s: Session = Depends(sesion), p: Principal = Depends(requiere_admin)):
    # Se valida por API (no por la base de datos de Productos) que el producto exista.
    try:
        r = httpx.get(f"{PRODUCTOS_URL}/internal/productos/{datos.producto_id}/cotizacion", timeout=2.0,
                      headers={"Authorization": f"Bearer {token_servicio('inventario')}"})
    except httpx.HTTPError:
        raise HTTPException(503, "No fue posible verificar el producto (servicio Productos no disponible)") from None
    if r.status_code == 404:
        raise HTTPException(404, "El producto no existe")
    r.raise_for_status()
    with s.begin():
        e = logica.registrar_entrada(s, datos.producto_id, datos.cantidad, datos.nota, p.email or p.sub)
    return {"producto_id": e.producto_id, "disponible": e.disponible, "reservado": e.reservado}


@app.get("/inventario/reservas")
def reservas(estado: str | None = None, prestamo_id: str | None = None,
             limite: int = Query(100, ge=1, le=500), s: Session = Depends(sesion),
             _p: Principal = Depends(requiere_admin)):
    q = select(Reserva).order_by(Reserva.creado_at.desc()).limit(limite)
    if estado:
        q = q.where(Reserva.estado == estado.upper())
    if prestamo_id:
        q = q.where(Reserva.prestamo_id == prestamo_id)
    return [r.a_dict() for r in s.scalars(q)]


@app.get("/inventario/movimientos")
def movimientos(producto_id: str | None = None, limite: int = Query(100, ge=1, le=500),
                s: Session = Depends(sesion), _p: Principal = Depends(requiere_admin)):
    q = select(Movimiento).order_by(Movimiento.id.desc()).limit(limite)
    if producto_id:
        q = q.where(Movimiento.producto_id == producto_id)
    return [m.a_dict() for m in s.scalars(q)]


@app.post("/inventario/reservas/{reserva_id}/confirmar-salida")
def confirmar_salida(reserva_id: str, s: Session = Depends(sesion), p: Principal = Depends(requiere_admin)):
    """Entrega simulada: descuenta la unidad reservada y publica SalidaConfirmada."""
    try:
        with s.begin():
            r = logica.confirmar_salida(s, reserva_id, p.email or p.sub)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return r.a_dict()


@app.get("/health")
def health():
    return {"estado": "ok", "servicio": "inventario"}


@app.get("/ready")
def ready(response: Response):
    bd = bd_lista(engine)
    if not bd:
        response.status_code = 503
    return {"estado": "listo" if bd else "no disponible", "base_datos": bd}
