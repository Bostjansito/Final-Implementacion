"""Proceso asíncrono de Inventario: consume comandos, publica el outbox y vence reservas."""
import logging
import threading

from sqlalchemy.orm import Session

from credimarket_common.config import entero
from credimarket_common.db import crear_engine, crear_sesiones, esperar_bd
from credimarket_common.mensajeria import COLA_INVENTARIO, Consumidor, RelayOutbox, ejecutar_hilos
from credimarket_common.web import configurar_logging

from . import logica
from .modelos import Base, inbox, outbox

configurar_logging("inventario-worker")
log = logging.getLogger("inventario.worker")

engine = crear_engine(pool_size=5)
Sesiones = crear_sesiones(engine)
INTERVALO_VENCIMIENTO = entero("INTERVALO_VENCIMIENTO_SEGUNDOS", 10)


def al_reservar(m: dict, s: Session) -> str:
    p = m["payload"]
    return logica.reservar(s, m["prestamo_id"], p["producto_id"], int(p["cantidad"]), m["correlation_id"])


def al_liberar(m: dict, s: Session) -> str:
    p = m["payload"]
    return logica.liberar(s, m["prestamo_id"], p.get("producto_id", ""), m["correlation_id"],
                          p.get("motivo", "cancelación"))


def tarea_vencimientos(detener: threading.Event) -> None:
    while not detener.wait(INTERVALO_VENCIMIENTO):
        try:
            with Sesiones() as s, s.begin():
                n = logica.vencer_reservas(s)
            if n:
                log.info("%s reservas vencidas y liberadas", n)
        except Exception:  # noqa: BLE001
            log.exception("Error venciendo reservas")


def main() -> None:
    esperar_bd(engine)
    Base.metadata.create_all(engine)
    consumidor = Consumidor(COLA_INVENTARIO, {"ReservaSolicitada": al_reservar,
                                              "LiberacionSolicitada": al_liberar},
                            Sesiones, inbox, "inventario")
    relay = RelayOutbox(Sesiones, outbox, "inventario")
    ejecutar_hilos(consumidor.ejecutar, relay.ejecutar, tarea_vencimientos)


if __name__ == "__main__":
    main()
