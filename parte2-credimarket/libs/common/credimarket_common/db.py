import time
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from .config import database_url

log = logging.getLogger(__name__)


def crear_engine(pool_size: int = 10) -> Engine:
    return create_engine(database_url(), pool_size=pool_size, max_overflow=10, pool_pre_ping=True)


def crear_sesiones(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)


def esperar_bd(engine: Engine, intentos: int = 30) -> None:
    for i in range(intentos):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("Base de datos no disponible (%s/%s): %s", i + 1, intentos, exc)
            time.sleep(2)
    raise RuntimeError("No fue posible conectar con la base de datos")


def bd_lista(engine: Engine) -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False
