import os
from functools import lru_cache


def secreto(nombre: str, defecto: str | None = None) -> str:
    """Lee NOMBRE del entorno o, si existe NOMBRE_FILE, del archivo indicado.

    Así los secretos viven en archivos montados (./.secrets) y nunca en el
    repositorio ni en el docker-compose.
    """
    valor = os.environ.get(nombre)
    if valor:
        return valor
    ruta = os.environ.get(f"{nombre}_FILE")
    if ruta and os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            return f.read().strip()
    if defecto is not None:
        return defecto
    raise RuntimeError(f"Falta la configuración obligatoria {nombre} (o {nombre}_FILE)")


def entero(nombre: str, defecto: int) -> int:
    return int(os.environ.get(nombre, defecto))


def lista(nombre: str, defecto: str = "") -> list[str]:
    return [v.strip() for v in os.environ.get(nombre, defecto).split(",") if v.strip()]


@lru_cache
def database_url() -> str:
    usuario = os.environ["DB_USER"]
    host = os.environ.get("DB_HOST", "postgres")
    nombre = os.environ["DB_NAME"]
    password = secreto("DB_PASSWORD")
    return f"postgresql+psycopg://{usuario}:{password}@{host}:5432/{nombre}"


@lru_cache
def rabbitmq_url() -> str:
    usuario = os.environ.get("RABBITMQ_USER", "credimarket")
    host = os.environ.get("RABBITMQ_HOST", "rabbitmq")
    password = secreto("RABBITMQ_PASSWORD")
    return f"amqp://{usuario}:{password}@{host}:5672/%2F?heartbeat=30&blocked_connection_timeout=30"
