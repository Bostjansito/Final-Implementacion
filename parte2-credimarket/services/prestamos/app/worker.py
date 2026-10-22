"""Proceso asíncrono de Préstamos: consume eventos de Inventario, publica el outbox y vigila tiempos de espera."""
import logging
import threading

from credimarket_common.config import entero
from credimarket_common.db import crear_engine, crear_sesiones, esperar_bd
from credimarket_common.mensajeria import COLA_PRESTAMOS, Consumidor, RelayOutbox, ejecutar_hilos
from credimarket_common.web import configurar_logging

from . import logica
from .modelos import Base, inbox, outbox

configurar_logging("prestamos-worker")
log = logging.getLogger("prestamos.worker")

engine = crear_engine(pool_size=5)
Sesiones = crear_sesiones(engine)
INTERVALO = entero("INTERVALO_TEMPORIZADOR_SEGUNDOS", 15)


def tarea_tiempos(detener: threading.Event) -> None:
    while not detener.wait(INTERVALO):
        try:
            with Sesiones() as s, s.begin():
                conteo = logica.revisar_tiempos(s)
            if any(conteo.values()):
                log.info("Temporizador: %s", conteo)
        except Exception:  # noqa: BLE001
            log.exception("Error revisando tiempos de espera")


def main() -> None:
    esperar_bd(engine)
    Base.metadata.create_all(engine)
    consumidor = Consumidor(COLA_PRESTAMOS, logica.MANEJADORES, Sesiones, inbox, "prestamos")
    relay = RelayOutbox(Sesiones, outbox, "prestamos")
    ejecutar_hilos(consumidor.ejecutar, relay.ejecutar, tarea_tiempos)


if __name__ == "__main__":
    main()
