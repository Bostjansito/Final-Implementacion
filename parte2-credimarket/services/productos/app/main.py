import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from credimarket_common.auth import (Principal, principal_opcional, requiere_admin,
                                     requiere_servicio_o_admin)
from credimarket_common.db import bd_lista, crear_engine, crear_sesiones, esperar_bd
from credimarket_common.semillas import CATALOGO, id_producto
from credimarket_common.web import configurar_cors, configurar_logging

from .cache import CLAVE_LISTA, TTL_DETALLE, TTL_LISTA, CacheProductos, clave_producto
from .modelos import Base, HistorialPrecio, Producto

configurar_logging("productos")
log = logging.getLogger("productos")

engine = crear_engine()
Sesiones = crear_sesiones(engine)
cache = CacheProductos()


def sembrar() -> None:
    with Sesiones() as s, s.begin():
        if s.scalar(select(Producto.id).limit(1)):
            return
        for sku, nombre, categoria, precio, _stock, desc in CATALOGO:
            pid = id_producto(sku)
            s.add(Producto(id=pid, sku=sku, nombre=nombre, categoria=categoria, precio=precio,
                           descripcion=desc, activo=True, version=1))
            s.add(HistorialPrecio(producto_id=pid, version=1, precio=precio, cambiado_por="semilla"))
        log.info("Catálogo inicial sembrado (%s productos)", len(CATALOGO))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    esperar_bd(engine)
    Base.metadata.create_all(engine)
    sembrar()
    yield


app = FastAPI(title="CrediMarket - Productos", version="1.0.0", lifespan=lifespan)
configurar_cors(app)


def sesion():
    with Sesiones() as s:
        yield s


class ProductoNuevo(BaseModel):
    sku: str = Field(min_length=3, max_length=40, pattern=r"^[A-Z0-9-]+$")
    nombre: str = Field(min_length=2, max_length=120)
    descripcion: str = Field(default="", max_length=2000)
    categoria: str = Field(min_length=2, max_length=60)
    precio: int = Field(gt=0, le=100_000_000)


class ProductoCambios(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    descripcion: str | None = Field(default=None, max_length=2000)
    categoria: str | None = Field(default=None, min_length=2, max_length=60)
    precio: int | None = Field(default=None, gt=0, le=100_000_000)
    version_esperada: int | None = Field(default=None, description="Control de concurrencia optimista")


def _buscar(s: Session, producto_id: str) -> Producto:
    p = s.get(Producto, producto_id)
    if p is None:
        raise HTTPException(404, "Producto no encontrado")
    return p


# ------------------------------------------------------------------ Consultas
@app.get("/productos")
def listar(response: Response, categoria: str | None = None, incluir_inactivos: bool = False,
           s: Session = Depends(sesion), p: Principal | None = Depends(principal_opcional)):
    if incluir_inactivos and not (p and p.es_admin):
        raise HTTPException(403, "Solo un administrador puede ver productos inactivos")
    usa_cache = not incluir_inactivos and categoria is None
    if usa_cache:
        datos, estado = cache.obtener(CLAVE_LISTA)
        response.headers["X-Cache"] = estado
        if datos is not None:
            return datos
    consulta = select(Producto).order_by(Producto.categoria, Producto.nombre)
    if not incluir_inactivos:
        consulta = consulta.where(Producto.activo.is_(True))
    if categoria:
        consulta = consulta.where(Producto.categoria == categoria)
    datos = [x.a_dict() for x in s.scalars(consulta)]
    if usa_cache:
        cache.guardar(CLAVE_LISTA, datos, TTL_LISTA)
    return datos


@app.get("/productos/{producto_id}")
def detalle(producto_id: str, response: Response, s: Session = Depends(sesion)):
    """Cache-aside: Redis primero; si falla o no está, PostgreSQL y se guarda con TTL."""
    clave = clave_producto(producto_id)
    datos, estado = cache.obtener(clave)
    response.headers["X-Cache"] = estado
    if datos is None:
        datos = _buscar(s, producto_id).a_dict()
        cache.guardar(clave, datos, TTL_DETALLE)
    return datos


@app.get("/internal/productos/{producto_id}/cotizacion")
def cotizacion(producto_id: str, s: Session = Depends(sesion),
               _p: Principal = Depends(requiere_servicio_o_admin)):
    """Cotización vigente leída SIEMPRE de la fuente de verdad (nunca de la caché)."""
    p = _buscar(s, producto_id)
    return {"producto_id": p.id, "nombre": p.nombre, "categoria": p.categoria, "precio": p.precio,
            "version": p.version, "activo": p.activo,
            "cotizado_at": datetime.now(timezone.utc).isoformat()}


@app.get("/productos/{producto_id}/historial-precios")
def historial(producto_id: str, s: Session = Depends(sesion), _p: Principal = Depends(requiere_admin)):
    filas = s.scalars(select(HistorialPrecio).where(HistorialPrecio.producto_id == producto_id)
                      .order_by(HistorialPrecio.version))
    return [{"version": h.version, "precio": h.precio, "cambiado_por": h.cambiado_por,
             "cambiado_at": h.cambiado_at.isoformat()} for h in filas]


# ------------------------------------------------------------------ Escrituras (admin)
@app.post("/productos", status_code=201)
def crear(datos: ProductoNuevo, s: Session = Depends(sesion), p: Principal = Depends(requiere_admin)):
    nuevo = Producto(id=id_producto(datos.sku), version=1, activo=True, **datos.model_dump())
    try:
        with s.begin():
            s.add(nuevo)
            s.add(HistorialPrecio(producto_id=nuevo.id, version=1, precio=nuevo.precio,
                                  cambiado_por=p.email or p.sub))
    except IntegrityError:
        raise HTTPException(409, "Ya existe un producto con ese SKU") from None
    cache.invalidar(CLAVE_LISTA)
    return nuevo.a_dict()


@app.put("/productos/{producto_id}")
def actualizar(producto_id: str, cambios: ProductoCambios, s: Session = Depends(sesion),
               p: Principal = Depends(requiere_admin)):
    with s.begin():
        prod = s.get(Producto, producto_id, with_for_update=True)
        if prod is None:
            raise HTTPException(404, "Producto no encontrado")
        if cambios.version_esperada is not None and cambios.version_esperada != prod.version:
            raise HTTPException(409, f"El producto cambió (versión actual {prod.version})")
        valores = cambios.model_dump(exclude_unset=True, exclude={"version_esperada"})
        if not valores:
            return prod.a_dict()
        for campo, valor in valores.items():
            setattr(prod, campo, valor)
        prod.version += 1
        if "precio" in valores:
            s.add(HistorialPrecio(producto_id=prod.id, version=prod.version, precio=prod.precio,
                                  cambiado_por=p.email or p.sub))
    # La escritura ya está confirmada: ahora sí se invalida la caché.
    cache.invalidar(clave_producto(producto_id), CLAVE_LISTA)
    log.info("Producto %s actualizado a versión %s por %s", producto_id, prod.version, p.email)
    return prod.a_dict()


def _cambiar_estado(producto_id: str, activo: bool, s: Session) -> dict:
    with s.begin():
        prod = s.get(Producto, producto_id, with_for_update=True)
        if prod is None:
            raise HTTPException(404, "Producto no encontrado")
        if prod.activo != activo:
            prod.activo = activo
            prod.version += 1
    cache.invalidar(clave_producto(producto_id), CLAVE_LISTA)
    return prod.a_dict()


@app.post("/productos/{producto_id}/desactivar")
def desactivar(producto_id: str, s: Session = Depends(sesion), _p: Principal = Depends(requiere_admin)):
    return _cambiar_estado(producto_id, False, s)


@app.post("/productos/{producto_id}/activar")
def activar(producto_id: str, s: Session = Depends(sesion), _p: Principal = Depends(requiere_admin)):
    return _cambiar_estado(producto_id, True, s)


# ------------------------------------------------------------------ Caché y salud
@app.get("/cache/estadisticas")
def estadisticas(producto_id: str | None = Query(default=None), _p: Principal = Depends(requiere_admin)):
    resumen = cache.resumen()
    if producto_id:
        resumen["ttl_restante_s"] = cache.ttl(clave_producto(producto_id))
    return resumen


@app.delete("/cache")
def vaciar_cache(_p: Principal = Depends(requiere_admin)):
    return {"claves_borradas": cache.vaciar()}


@app.get("/health")
def health():
    return {"estado": "ok", "servicio": "productos"}


@app.get("/ready")
def ready(response: Response):
    bd = bd_lista(engine)
    redis_ok = cache.disponible()
    if not bd:
        response.status_code = 503
    # Redis no es crítico: sin él se sigue respondiendo desde la base de datos.
    return {"estado": "listo" if bd else "no disponible", "base_datos": bd, "redis": redis_ok}
