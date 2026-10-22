"""Mensajería confiable con RabbitMQ.

Piezas:
* ``crear_mensaje``: sobre (envelope) común de comandos y eventos.
* Tablas ``outbox`` y ``mensajes_procesados`` (inbox) para cada servicio.
* ``RelayOutbox``: publica lo que está en el outbox con *publisher confirms*.
* ``Consumidor``: ack manual, idempotencia por ``event_id`` en la misma
  transacción que el efecto de negocio, reintentos limitados y dead letter.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Callable

import pika
from pika.exceptions import AMQPError, NackError, UnroutableError
from sqlalchemy import (BigInteger, Column, DateTime, Integer, MetaData, String, Table, Text,
                        func, select, update)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Session, sessionmaker

from .config import entero, rabbitmq_url

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- Topología
EX_COMANDOS = "credimarket.comandos"   # direct: comandos para Inventario
EX_EVENTOS = "credimarket.eventos"     # topic: eventos publicados por Inventario
EX_DLX = "credimarket.dlx"             # direct: mensajes que no pudieron procesarse

COLA_INVENTARIO = "inventario.comandos"
COLA_PRESTAMOS = "prestamos.eventos-inventario"

RK_RESERVAR = "inventario.reservar"
RK_LIBERAR = "inventario.liberar"

MAX_REINTENTOS = entero("MAX_REINTENTOS", 3)
RETRY_TTL_MS = entero("RETRY_TTL_MS", 5000)


def declarar_topologia(canal) -> None:
    canal.exchange_declare(EX_COMANDOS, exchange_type="direct", durable=True)
    canal.exchange_declare(EX_EVENTOS, exchange_type="topic", durable=True)
    canal.exchange_declare(EX_DLX, exchange_type="direct", durable=True)

    def cola_con_reintentos(nombre: str, bindings: list[tuple[str, str]]) -> None:
        canal.queue_declare(nombre, durable=True, arguments={
            "x-queue-type": "quorum",
            "x-dead-letter-exchange": EX_DLX,
            "x-dead-letter-routing-key": nombre,
        })
        for exchange, rk in bindings:
            canal.queue_bind(nombre, exchange, routing_key=rk)
        # Cola de espera: el mensaje vence tras RETRY_TTL_MS y vuelve a la cola principal
        canal.queue_declare(f"{nombre}.retry", durable=True, arguments={
            "x-message-ttl": RETRY_TTL_MS,
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": nombre,
        })
        canal.queue_declare(f"{nombre}.dlq", durable=True, arguments={"x-queue-type": "quorum"})
        canal.queue_bind(f"{nombre}.dlq", EX_DLX, routing_key=nombre)

    cola_con_reintentos(COLA_INVENTARIO, [(EX_COMANDOS, RK_RESERVAR), (EX_COMANDOS, RK_LIBERAR)])
    cola_con_reintentos(COLA_PRESTAMOS, [(EX_EVENTOS, "inventario.*")])


def conectar(nombre: str) -> pika.BlockingConnection:
    params = pika.URLParameters(rabbitmq_url())
    params.client_properties = {"connection_name": nombre}
    return pika.BlockingConnection(params)


# ---------------------------------------------------------------- Contrato
def crear_mensaje(tipo: str, prestamo_id: str, correlation_id: str, payload: dict,
                  schema_version: int = 1) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "type": tipo,
        "schema_version": schema_version,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
        "prestamo_id": prestamo_id,
        "payload": payload,
    }


# ---------------------------------------------------------------- Tablas
def tabla_outbox(metadata: MetaData) -> Table:
    return Table(
        "outbox", metadata,
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column("event_id", String(36), nullable=False, unique=True),
        Column("tipo", String(60), nullable=False),
        Column("exchange", String(60), nullable=False),
        Column("routing_key", String(80), nullable=False),
        Column("mensaje", JSONB, nullable=False),
        Column("creado_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("publicado_at", DateTime(timezone=True)),
        Column("intentos", Integer, nullable=False, server_default="0"),
    )


def tabla_inbox(metadata: MetaData) -> Table:
    return Table(
        "mensajes_procesados", metadata,
        Column("event_id", String(36), primary_key=True),
        Column("tipo", String(60), nullable=False),
        Column("procesado_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("resultado", Text),
    )


def encolar(session: Session, outbox: Table, exchange: str, routing_key: str, mensaje: dict) -> None:
    """Guarda el mensaje en el outbox dentro de la transacción del llamador."""
    session.execute(outbox.insert().values(
        event_id=mensaje["event_id"], tipo=mensaje["type"], exchange=exchange,
        routing_key=routing_key, mensaje=mensaje,
    ))


# ---------------------------------------------------------------- Relay
class RelayOutbox:
    """Publica los mensajes pendientes del outbox. Si se cae entre publicar y
    marcar, el mensaje se publica dos veces: los consumidores son idempotentes."""

    def __init__(self, sesiones: sessionmaker, outbox: Table, nombre: str, lote: int = 50):
        self.sesiones = sesiones
        self.outbox = outbox
        self.nombre = nombre
        self.lote = lote

    def _ciclo(self, canal) -> int:
        with self.sesiones() as s, s.begin():
            filas = s.execute(
                select(self.outbox.c.id, self.outbox.c.exchange, self.outbox.c.routing_key,
                       self.outbox.c.mensaje)
                .where(self.outbox.c.publicado_at.is_(None))
                .order_by(self.outbox.c.id).limit(self.lote).with_for_update(skip_locked=True)
            ).all()
            for fila in filas:
                m = fila.mensaje
                canal.basic_publish(
                    exchange=fila.exchange, routing_key=fila.routing_key,
                    body=json.dumps(m).encode(), mandatory=True,
                    properties=pika.BasicProperties(
                        delivery_mode=pika.DeliveryMode.Persistent, content_type="application/json",
                        message_id=m["event_id"], type=m["type"], correlation_id=m["correlation_id"],
                        headers={"schema_version": m["schema_version"]},
                    ),
                )  # con confirm_delivery, retorna solo cuando el broker confirmó
                s.execute(update(self.outbox).where(self.outbox.c.id == fila.id)
                          .values(publicado_at=func.now(), intentos=self.outbox.c.intentos + 1))
            return len(filas)

    def ejecutar(self, detener: threading.Event) -> None:
        while not detener.is_set():
            try:
                conexion = conectar(f"{self.nombre}-outbox-relay")
                canal = conexion.channel()
                declarar_topologia(canal)
                canal.confirm_delivery()
                log.info("Relay de outbox conectado a RabbitMQ")
                while not detener.is_set():
                    if self._ciclo(canal) == 0:
                        conexion.sleep(0.5)
            except (UnroutableError, NackError) as exc:
                log.error("El broker no confirmó una publicación, se reintentará: %s", exc)
                time.sleep(2)
            except AMQPError as exc:
                log.warning("RabbitMQ no disponible para el relay: %s. Reintentando...", exc)
                time.sleep(3)
            except Exception:  # noqa: BLE001
                log.exception("Error en el relay de outbox")
                time.sleep(3)


# ---------------------------------------------------------------- Consumidor
Manejador = Callable[[dict, Session], str | None]


class MensajeInvalido(Exception):
    """El mensaje nunca podrá procesarse: va directo a la dead letter."""


class Consumidor:
    def __init__(self, cola: str, manejadores: dict[str, Manejador], sesiones: sessionmaker,
                 inbox: Table, nombre: str, prefetch: int = 10):
        self.cola = cola
        self.manejadores = manejadores
        self.sesiones = sesiones
        self.inbox = inbox
        self.nombre = nombre
        self.prefetch = prefetch

    def _procesar(self, mensaje: dict) -> str:
        manejador = self.manejadores.get(mensaje.get("type"))
        if manejador is None:
            raise MensajeInvalido(f"tipo de mensaje desconocido: {mensaje.get('type')}")
        for campo in ("event_id", "type", "schema_version", "prestamo_id", "payload"):
            if campo not in mensaje:
                raise MensajeInvalido(f"falta el campo {campo}")
        if mensaje["schema_version"] != 1:
            raise MensajeInvalido(f"schema_version no soportada: {mensaje['schema_version']}")

        with self.sesiones() as s, s.begin():
            nuevo = s.execute(
                insert(self.inbox).values(event_id=mensaje["event_id"], tipo=mensaje["type"])
                .on_conflict_do_nothing(index_elements=["event_id"])
                .returning(self.inbox.c.event_id)
            ).first()
            if nuevo is None:
                return "duplicado-ignorado"
            resultado = manejador(mensaje, s) or "ok"
            s.execute(update(self.inbox).where(self.inbox.c.event_id == mensaje["event_id"])
                      .values(resultado=resultado))
            return resultado  # el commit ocurre al salir del bloque, antes del ack

    def _al_recibir(self, canal, metodo, props, cuerpo: bytes) -> None:
        headers = dict(props.headers or {})
        reintentos = int(headers.get("x-reintentos", 0))
        try:
            mensaje = json.loads(cuerpo)
            resultado = self._procesar(mensaje)
            log.info("%s %s prestamo=%s -> %s", mensaje["type"], mensaje["event_id"],
                     mensaje["prestamo_id"], resultado)
            canal.basic_ack(metodo.delivery_tag)
        except (json.JSONDecodeError, MensajeInvalido) as exc:
            log.error("Mensaje inválido enviado a dead letter: %s", exc)
            headers["x-error"] = str(exc)[:500]
            self._publicar(canal, EX_DLX, self.cola, cuerpo, props, headers)
            canal.basic_ack(metodo.delivery_tag)
        except Exception as exc:  # noqa: BLE001  error transitorio: reintento limitado
            headers["x-error"] = str(exc)[:500]
            if reintentos < MAX_REINTENTOS:
                headers["x-reintentos"] = reintentos + 1
                log.warning("Fallo procesando mensaje (intento %s/%s): %s",
                            reintentos + 1, MAX_REINTENTOS, exc)
                self._publicar(canal, "", f"{self.cola}.retry", cuerpo, props, headers)
            else:
                log.error("Mensaje agotó %s reintentos, enviado a dead letter: %s", MAX_REINTENTOS, exc)
                self._publicar(canal, EX_DLX, self.cola, cuerpo, props, headers)
            canal.basic_ack(metodo.delivery_tag)

    @staticmethod
    def _publicar(canal, exchange: str, rk: str, cuerpo: bytes, props, headers: dict) -> None:
        canal.basic_publish(exchange, rk, cuerpo, properties=pika.BasicProperties(
            delivery_mode=pika.DeliveryMode.Persistent, content_type="application/json",
            message_id=props.message_id, type=props.type, correlation_id=props.correlation_id,
            headers=headers,
        ))

    def ejecutar(self, detener: threading.Event) -> None:
        while not detener.is_set():
            try:
                conexion = conectar(f"{self.nombre}-consumidor")
                canal = conexion.channel()
                declarar_topologia(canal)
                canal.basic_qos(prefetch_count=self.prefetch)
                canal.basic_consume(self.cola, self._al_recibir, auto_ack=False)
                log.info("Consumiendo la cola %s", self.cola)
                while not detener.is_set():
                    conexion.process_data_events(time_limit=1)
                conexion.close()
            except AMQPError as exc:
                log.warning("RabbitMQ no disponible para el consumidor: %s. Reintentando...", exc)
                time.sleep(3)
            except Exception:  # noqa: BLE001
                log.exception("Error en el consumidor")
                time.sleep(3)


def ejecutar_hilos(*objetivos: Callable[[threading.Event], None]) -> None:
    """Ejecuta cada tarea en un hilo y espera hasta recibir una señal de parada."""
    import signal

    detener = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: detener.set())
    signal.signal(signal.SIGINT, lambda *_: detener.set())
    hilos = [threading.Thread(target=o, args=(detener,), daemon=True) for o in objetivos]
    for h in hilos:
        h.start()
    while not detener.is_set():
        detener.wait(1)
    for h in hilos:
        h.join(timeout=5)
