"""Llamadas síncronas a Clientes y Productos, con tiempos de espera acotados y token de servicio."""
import os

import httpx

from credimarket_common.auth import token_servicio

CLIENTES_URL = os.environ.get("CLIENTES_URL", "http://clientes:8000")
PRODUCTOS_URL = os.environ.get("PRODUCTOS_URL", "http://productos:8000")
TIMEOUT = httpx.Timeout(3.0, connect=1.0)


class DependenciaNoDisponible(Exception):
    def __init__(self, servicio: str, detalle: str):
        super().__init__(f"{servicio} no disponible: {detalle}")
        self.servicio = servicio


class NoEncontrado(Exception):
    pass


def _get(servicio: str, url: str) -> dict:
    try:
        r = httpx.get(url, timeout=TIMEOUT, headers={"Authorization": f"Bearer {token_servicio('prestamos')}"})
    except httpx.HTTPError as exc:
        raise DependenciaNoDisponible(servicio, type(exc).__name__) from None
    if r.status_code == 404:
        raise NoEncontrado(servicio)
    if r.status_code >= 500:
        raise DependenciaNoDisponible(servicio, f"HTTP {r.status_code}")
    r.raise_for_status()
    return r.json()


def obtener_cliente(cliente_id: str) -> dict:
    return _get("Clientes", f"{CLIENTES_URL}/internal/clientes/{cliente_id}")


def obtener_cotizacion(producto_id: str) -> dict:
    """La cotización se lee de la fuente de verdad de Productos (no de la caché)."""
    return _get("Productos", f"{PRODUCTOS_URL}/internal/productos/{producto_id}/cotizacion")


def dependencias_disponibles() -> dict:
    estado = {}
    for nombre, url in (("clientes", CLIENTES_URL), ("productos", PRODUCTOS_URL)):
        try:
            estado[nombre] = httpx.get(f"{url}/health", timeout=1.0).status_code == 200
        except httpx.HTTPError:
            estado[nombre] = False
    return estado
