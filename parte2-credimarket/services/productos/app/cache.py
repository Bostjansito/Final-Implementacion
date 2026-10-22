"""Caché cache-aside de productos sobre Redis.

Reglas:
* Redis nunca es la fuente de verdad: ante cualquier error se responde desde
  PostgreSQL con un tiempo de espera acotado (200 ms).
* Tras un error, Redis se omite durante unos segundos (circuit breaker simple)
  para no pagar el timeout en cada petición.
* La invalidación se hace DESPUÉS de confirmar la escritura en la base de datos.
"""
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturoVencido

import redis

from credimarket_common.config import entero, secreto

log = logging.getLogger(__name__)

PREFIJO = "productos:v1"
TTL_DETALLE = entero("CACHE_TTL_SEGUNDOS", 300)
TTL_LISTA = entero("CACHE_TTL_LISTA_SEGUNDOS", 60)
PAUSA_TRAS_ERROR = entero("CACHE_PAUSA_TRAS_ERROR_SEGUNDOS", 5)
# Tiempo máximo TOTAL de una operación de Redis (incluye resolver DNS, que el
# socket_timeout no cubre: si el contenedor de Redis no existe, resolver el nombre tarda segundos).
LIMITE_OPERACION_S = entero("CACHE_LIMITE_OPERACION_MS", 250) / 1000


def clave_producto(producto_id: str) -> str:
    return f"{PREFIJO}:{producto_id}"


CLAVE_LISTA = f"{PREFIJO}:lista:activos"


class CacheProductos:
    def __init__(self) -> None:
        self.cliente = redis.Redis(
            host=secreto("REDIS_HOST", "redis"), port=6379, password=secreto("REDIS_PASSWORD"),
            socket_timeout=0.2, socket_connect_timeout=0.2, decode_responses=True,
        )
        self._omitir_hasta = 0.0
        self._lock = threading.Lock()
        self._hilos = ThreadPoolExecutor(max_workers=8, thread_name_prefix="redis")
        self.stats = {"hits": 0, "misses": 0, "errores": 0, "omitidas": 0, "invalidaciones": 0}

    def _acotado(self, operacion, *args, **kwargs):
        """Ejecuta la operación con un límite de tiempo total; si se vence, se trata como error de Redis."""
        try:
            return self._hilos.submit(operacion, *args, **kwargs).result(timeout=LIMITE_OPERACION_S)
        except FuturoVencido:
            raise redis.TimeoutError(f"Redis no respondió en {LIMITE_OPERACION_S * 1000:.0f} ms") from None

    def _contar(self, campo: str) -> None:
        with self._lock:
            self.stats[campo] += 1

    def _disponible(self) -> bool:
        if time.monotonic() < self._omitir_hasta:
            self._contar("omitidas")
            return False
        return True

    def _fallo(self, exc: Exception) -> None:
        self._contar("errores")
        self._omitir_hasta = time.monotonic() + PAUSA_TRAS_ERROR
        log.warning("Redis no disponible, se responde desde la base de datos: %s", exc)

    def obtener(self, clave: str):
        """Devuelve (valor | None, estado) con estado HIT, MISS o BYPASS."""
        if not self._disponible():
            return None, "BYPASS"
        try:
            crudo = self._acotado(self.cliente.get, clave)
        except redis.RedisError as exc:
            self._fallo(exc)
            return None, "BYPASS"
        if crudo is None:
            self._contar("misses")
            return None, "MISS"
        self._contar("hits")
        return json.loads(crudo), "HIT"

    def guardar(self, clave: str, valor, ttl: int) -> None:
        if not self._disponible():
            return
        try:
            self._acotado(self.cliente.set, clave, json.dumps(valor), ex=ttl)
        except redis.RedisError as exc:
            self._fallo(exc)

    def invalidar(self, *claves: str) -> None:
        # Se intenta aunque el circuito esté abierto: invalidar es más importante que leer.
        try:
            self._acotado(self.cliente.delete, *claves)
            self._contar("invalidaciones")
        except redis.RedisError as exc:
            # Si falla, el TTL acota cuánto tiempo puede quedar el dato desactualizado.
            self._fallo(exc)

    def vaciar(self) -> int:
        borradas = 0
        for clave in self.cliente.scan_iter(f"{PREFIJO}:*"):
            borradas += self.cliente.delete(clave)
        return borradas

    def ttl(self, clave: str) -> int | None:
        try:
            return self._acotado(self.cliente.ttl, clave)
        except redis.RedisError:
            return None

    def disponible(self) -> bool:
        try:
            return bool(self._acotado(self.cliente.ping))
        except redis.RedisError:
            return False

    def resumen(self) -> dict:
        consultas = self.stats["hits"] + self.stats["misses"]
        return {
            **self.stats,
            "tasa_aciertos": round(self.stats["hits"] / consultas, 4) if consultas else None,
            "ttl_detalle_s": TTL_DETALLE, "ttl_lista_s": TTL_LISTA,
            "redis_disponible": self.disponible(),
        }
