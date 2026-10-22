import hashlib
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from credimarket_common.auth import (Principal, emitir_token_usuario, principal_actual, requiere_admin,
                                     requiere_servicio_o_admin)
from credimarket_common.config import entero, secreto
from credimarket_common.db import bd_lista, crear_engine, crear_sesiones, esperar_bd
from credimarket_common.web import configurar_cors, configurar_logging

from .importacion import importar
from .modelos import Base, Cliente, Importacion, Usuario
from .seguridad import hash_password, verificar_password

configurar_logging("clientes")
log = logging.getLogger("clientes")

engine = crear_engine()
Sesiones = crear_sesiones(engine)
TOKEN_MINUTOS = entero("TOKEN_MINUTOS", 30)
EMAIL_REGEX = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
MAX_CSV_BYTES = 5 * 1024 * 1024


def _clave_privada() -> str:
    return secreto("JWT_PRIVATE_KEY")


# Perfiles de demostración: uno de riesgo bajo, uno de riesgo alto y uno neutro.
CLIENTES_DEMO = [
    ("ana.bajo@credimarket.test", "DEMO-ANA", "Ana Bajo Riesgo", "1001001001",
     dict(ingresos_mensuales_cop=9_500_000, obligaciones_mensuales_cop=800_000, tipo_empleo="dependiente",
          antiguedad_laboral_meses=96, meses_historial_crediticio=140, creditos_previos=6,
          atrasos_previos_30d=0, porcentaje_pago_puntual=99.0)),
    ("bruno.alto@credimarket.test", "DEMO-BRUNO", "Bruno Alto Riesgo", "1002002002",
     dict(ingresos_mensuales_cop=1_600_000, obligaciones_mensuales_cop=1_000_000, tipo_empleo="temporal",
          antiguedad_laboral_meses=2, meses_historial_crediticio=6, creditos_previos=3,
          atrasos_previos_30d=6, porcentaje_pago_puntual=35.0)),
    ("carla.otra@credimarket.test", "DEMO-CARLA", "Carla Otra Cliente", "1003003003",
     dict(ingresos_mensuales_cop=6_000_000, obligaciones_mensuales_cop=900_000, tipo_empleo="dependiente",
          antiguedad_laboral_meses=48, meses_historial_crediticio=80, creditos_previos=3,
          atrasos_previos_30d=0, porcentaje_pago_puntual=95.0)),
]


def sembrar() -> None:
    with Sesiones() as s, s.begin():
        if s.scalar(select(Usuario.id).where(Usuario.email == "admin@credimarket.test")):
            return
        s.add(Usuario(id=str(uuid.uuid4()), email="admin@credimarket.test",
                      password_hash=hash_password(secreto("ADMIN_PASSWORD")), rol="ADMIN"))
        demo_pass = hash_password(secreto("DEMO_CLIENTE_PASSWORD"))
        for email, codigo, nombre, doc, fin in CLIENTES_DEMO:
            cid = str(uuid.uuid4())
            s.add(Cliente(id=cid, codigo_externo=codigo, nombre=nombre, documento=doc, email=email,
                          activo=True, origen="semilla", **fin))
            s.flush()
            s.add(Usuario(id=str(uuid.uuid4()), email=email, password_hash=demo_pass, rol="CLIENTE",
                          cliente_id=cid))
        log.info("Usuarios de demostración creados")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    esperar_bd(engine)
    Base.metadata.create_all(engine)
    sembrar()
    yield


app = FastAPI(title="CrediMarket - Clientes", version="1.0.0", lifespan=lifespan)
configurar_cors(app)


def sesion():
    with Sesiones() as s:
        yield s


# ------------------------------------------------------------------ Esquemas
class DatosFinancieros(BaseModel):
    ingresos_mensuales_cop: int | None = Field(default=None, gt=0, le=1_000_000_000)
    obligaciones_mensuales_cop: int | None = Field(default=None, ge=0, le=1_000_000_000)
    tipo_empleo: str | None = Field(default=None, pattern="^(dependiente|independiente|temporal)$")
    antiguedad_laboral_meses: float | None = Field(default=None, ge=0, le=720)
    meses_historial_crediticio: float | None = Field(default=None, ge=0, le=720)
    creditos_previos: int | None = Field(default=None, ge=0, le=200)
    atrasos_previos_30d: int | None = Field(default=None, ge=0, le=200)
    porcentaje_pago_puntual: float | None = Field(default=None, ge=0, le=100)


class Registro(DatosFinancieros):
    email: str = Field(pattern=EMAIL_REGEX, max_length=160)
    password: str = Field(min_length=8, max_length=128)
    nombre: str = Field(min_length=2, max_length=120)
    documento: str = Field(min_length=5, max_length=30, pattern=r"^[0-9A-Za-z-]+$")
    telefono: str | None = Field(default=None, max_length=30)


class Login(BaseModel):
    email: str = Field(pattern=EMAIL_REGEX, max_length=160)
    password: str = Field(min_length=1, max_length=128)


class ActualizacionCliente(DatosFinancieros):
    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    telefono: str | None = Field(default=None, max_length=30)
    activo: bool | None = Field(default=None, description="Solo administrador")


def _respuesta_token(u: Usuario) -> dict:
    token, exp = emitir_token_usuario(_clave_privada(), u.id, u.rol, u.cliente_id, u.email, TOKEN_MINUTOS)
    return {"access_token": token, "token_type": "bearer", "expira_en": exp,
            "usuario": {"id": u.id, "email": u.email, "rol": u.rol, "cliente_id": u.cliente_id}}


# ------------------------------------------------------------------ Autenticación
@app.post("/auth/registro", status_code=201)
def registro(datos: Registro, s: Session = Depends(sesion)):
    email = datos.email.lower()
    cid = str(uuid.uuid4())
    financieros = datos.model_dump(include=set(DatosFinancieros.model_fields))
    try:
        with s.begin():
            s.add(Cliente(id=cid, codigo_externo=f"WEB-{cid[:8].upper()}", nombre=datos.nombre,
                          documento=datos.documento, email=email, telefono=datos.telefono,
                          activo=True, origen="registro", **financieros))
            s.flush()
            u = Usuario(id=str(uuid.uuid4()), email=email, password_hash=hash_password(datos.password),
                        rol="CLIENTE", cliente_id=cid)
            s.add(u)
    except IntegrityError:
        raise HTTPException(409, "Ya existe una cuenta con ese correo") from None
    return _respuesta_token(u)


@app.post("/auth/login")
def login(datos: Login, s: Session = Depends(sesion)):
    u = s.scalar(select(Usuario).where(Usuario.email == datos.email.lower()))
    if u is None or not u.activo or not verificar_password(datos.password, u.password_hash):
        raise HTTPException(401, "Correo o contraseña incorrectos")
    return _respuesta_token(u)


@app.get("/auth/me")
def yo(p: Principal = Depends(principal_actual)):
    return {"id": p.sub, "email": p.email, "rol": p.rol, "cliente_id": p.cliente_id}


# ------------------------------------------------------------------ Clientes
def _autorizar_cliente(p: Principal, cliente_id: str) -> None:
    if not (p.es_admin or p.cliente_id == cliente_id):
        raise HTTPException(403, "No puede acceder a la información de otro cliente")


@app.get("/clientes")
def listar(buscar: str | None = None, pagina: int = Query(1, ge=1), tamano: int = Query(20, ge=1, le=100),
           s: Session = Depends(sesion), _p: Principal = Depends(requiere_admin)):
    consulta = select(Cliente)
    if buscar:
        patron = f"%{buscar}%"
        consulta = consulta.where(or_(Cliente.nombre.ilike(patron), Cliente.codigo_externo.ilike(patron),
                                      Cliente.email.ilike(patron), Cliente.documento.ilike(patron)))
    total = s.scalar(select(func.count()).select_from(consulta.subquery()))
    filas = s.scalars(consulta.order_by(Cliente.creado_at.desc(), Cliente.codigo_externo)
                      .offset((pagina - 1) * tamano).limit(tamano))
    return {"total": total, "pagina": pagina, "tamano": tamano, "items": [c.a_dict() for c in filas]}


@app.get("/clientes/importaciones")
def importaciones(s: Session = Depends(sesion), _p: Principal = Depends(requiere_admin)):
    filas = s.scalars(select(Importacion).order_by(Importacion.id.desc()).limit(20))
    return [{"id": i.id, "archivo": i.archivo, "sha256": i.sha256, "filas": i.filas,
             "insertados": i.insertados, "actualizados": i.actualizados, "sin_cambios": i.sin_cambios,
             "rechazados": i.rechazados, "realizada_por": i.realizada_por,
             "creado_at": i.creado_at.isoformat()} for i in filas]


@app.post("/clientes/importar")
async def importar_csv(archivo: UploadFile = File(...), s: Session = Depends(sesion),
                       p: Principal = Depends(requiere_admin)):
    contenido = await archivo.read(MAX_CSV_BYTES + 1)
    if len(contenido) > MAX_CSV_BYTES:
        raise HTTPException(413, "El archivo supera 5 MB")
    try:
        with s.begin():
            resumen = importar(s, contenido)
            s.add(Importacion(archivo=archivo.filename or "sin-nombre.csv",
                              sha256=hashlib.sha256(contenido).hexdigest(), filas=resumen["filas"],
                              insertados=resumen["insertados"], actualizados=resumen["actualizados"],
                              sin_cambios=resumen["sin_cambios"], rechazados=resumen["rechazados"],
                              errores=resumen["errores"][:500], realizada_por=p.email or p.sub))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    log.info("Importación %s: %s", archivo.filename, {k: v for k, v in resumen.items() if k != "errores"})
    return resumen


@app.get("/clientes/{cliente_id}")
def detalle(cliente_id: str, s: Session = Depends(sesion), p: Principal = Depends(principal_actual)):
    _autorizar_cliente(p, cliente_id)
    c = s.get(Cliente, cliente_id)
    if c is None:
        raise HTTPException(404, "Cliente no encontrado")
    return c.a_dict()


@app.put("/clientes/{cliente_id}")
def actualizar(cliente_id: str, cambios: ActualizacionCliente, s: Session = Depends(sesion),
               p: Principal = Depends(principal_actual)):
    _autorizar_cliente(p, cliente_id)
    valores = cambios.model_dump(exclude_unset=True)
    if "activo" in valores and not p.es_admin:
        raise HTTPException(403, "Solo un administrador puede activar o desactivar clientes")
    with s.begin():
        c = s.get(Cliente, cliente_id, with_for_update=True)
        if c is None:
            raise HTTPException(404, "Cliente no encontrado")
        for campo, valor in valores.items():
            setattr(c, campo, valor)
    return c.a_dict()


@app.get("/internal/clientes/{cliente_id}")
def interno(cliente_id: str, s: Session = Depends(sesion),
            _p: Principal = Depends(requiere_servicio_o_admin)):
    """Perfil para evaluación de riesgo. Solo para servicios internos o administradores."""
    c = s.get(Cliente, cliente_id)
    if c is None:
        raise HTTPException(404, "Cliente no encontrado")
    return c.a_dict()


# ------------------------------------------------------------------ Salud
@app.get("/health")
def health():
    return {"estado": "ok", "servicio": "clientes"}


@app.get("/ready")
def ready(response: Response):
    bd = bd_lista(engine)
    if not bd:
        response.status_code = 503
    return {"estado": "listo" if bd else "no disponible", "base_datos": bd}
