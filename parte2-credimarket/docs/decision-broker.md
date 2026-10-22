# Decisión de arquitectura: RabbitMQ (y no Kafka)

**Decisión:** usamos **RabbitMQ 3.13** con *quorum queues*, *publisher confirms*, *acks* manuales, reintentos limitados y *dead letter*. El broker transporta los comandos y eventos reales entre Préstamos e Inventario.

## 1. Volumen, consumidores y patrón de comunicación

* **Volumen:** CrediMarket procesa decenas o cientos de solicitudes por hora en un día normal (pocos mensajes por segundo en un pico de ventas). Cada préstamo genera entre 2 y 4 mensajes.
* **Consumidores:** uno por tipo de mensaje. Inventario consume comandos y Préstamos consume eventos. No hay hoy otros sistemas leyendo el mismo flujo.
* **Patrón:** **comando → respuesta asíncrona** punto a punto ("reserva esto" → "reservado / insuficiente"). Es un patrón de **cola de trabajo**, no de difusión masiva ni *stream processing*.

## 2. ¿Hay que conservar y reproducir eventos?

**No en el broker.** La verdad de negocio vive en las bases de datos de cada servicio: préstamos, historial de estados, reservas y movimientos. El `outbox` guarda cada mensaje publicado y el `inbox` (`mensajes_procesados`) cada mensaje consumido con su resultado. Esto da trazabilidad completa de forma permanente, sin necesidad de reproducir desde el broker. Una vez confirmado, un mensaje puede desaparecer de la cola. Si se necesitara reprocesar, se reinyecta desde el outbox.

## 3. Distribución del trabajo y orden

| Cola | Tipo | Productor | Consumidor | Routing keys |
|---|---|---|---|---|
| `inventario.comandos` | quorum, durable | Préstamos (outbox) → exchange `credimarket.comandos` (**direct**) | Inventario worker | `inventario.reservar`, `inventario.liberar` |
| `prestamos.eventos-inventario` | quorum, durable | Inventario (outbox) → exchange `credimarket.eventos` (**topic**) | Préstamos worker | `inventario.*` (`reservado`, `insuficiente`, `liberada`, `vencida`, `salida_confirmada`) |
| `<cola>.retry` | clásica, durable, `x-message-ttl=5000` | el consumidor ante un error transitorio | (vence y vuelve a `<cola>` por *dead-letter* al exchange por defecto) | — |
| `<cola>.dlq` | quorum, durable | exchange `credimarket.dlx` (**direct**) | revisión manual | nombre de la cola de origen |

* Con varias réplicas del *worker*, RabbitMQ reparte los mensajes por *round-robin* (`prefetch=10`).
* **Orden:** RabbitMQ conserva el orden de una cola con un consumidor, pero los reintentos pueden reordenar. **No dependemos del orden.** La máquina de estados de Préstamos ignora eventos que no aplican al estado actual. Inventario deja una "lápida" (`LIBERADA` sin unidades) si la liberación llega antes que la reserva, así una `ReservaSolicitada` tardía no reserva nada. Ver [maquina-estados.md](maquina-estados.md).

## 4. Errores, duplicados, reintentos y mensajes imposibles

| Situación | Manejo |
|---|---|
| Caída entre guardar el estado y publicar | **Transactional outbox**: el mensaje se inserta en `outbox` en la **misma transacción** que el cambio de estado. El relay del *worker* lo publica con **publisher confirms** y solo entonces lo marca `publicado_at`. |
| Broker caído | La API sigue aceptando solicitudes (quedan en el outbox). El relay reintenta la conexión cada 3 s y publica al volver (prueba de aceptación 6). |
| Mensaje duplicado (reentrega o relay repetido) | **Inbox**: `INSERT INTO mensajes_procesados(event_id) ON CONFLICT DO NOTHING` en la **misma transacción** que el efecto. Si ya existía, se ignora. El *ack* se hace **después** del *commit*. Además, `UNIQUE(prestamo_id)` en `reservas` impide reservar dos veces aunque llegue el mismo comando con otro `event_id`. |
| Error transitorio (BD caída, *deadlock*) | Se republica en `<cola>.retry` con `x-reintentos+1`. Tras 5 s vuelve a la cola. **Máximo 3 reintentos** (`MAX_REINTENTOS`). |
| Error permanente o mensaje inválido (JSON malo, tipo desconocido, `schema_version` no soportada) | Directo a **`<cola>.dlq`** con la cabecera `x-error` (caso "DLQ" de las pruebas). |
| Persistencia | Mensajes `delivery_mode=2` y colas quorum replicadas y durables (volumen `rabbitdata`). |

> Las garantías del broker son *al menos una vez*. El efecto "exactamente una vez" lo dan la idempotencia del inbox y las restricciones únicas en la base de datos.

## 5. Costo y complejidad operativa

| | RabbitMQ (elegido) | Kafka |
|---|---|---|
| Contenedores | 1 (`rabbitmq:3.13-management`) | 1 broker en modo KRaft (o broker + ZooKeeper) |
| Memoria en reposo | 144 MB (medido con `docker stats`) | ~400 MB–1 GB por la JVM (estimado, no medido) |
| Conceptos a operar | exchanges, colas, bindings | topics, particiones, offsets, grupos, retención, rebalanceos |
| Reintentos y DLQ | Nativos (TTL + dead-letter exchange) | A construir (*topics* de reintento y DLT) |
| Interfaz de administración | Incluida (puerto 15672) | Requiere herramientas adicionales |

## 6. ¿Por qué RabbitMQ? ¿Qué nos haría cambiar a Kafka?

**Elegimos RabbitMQ** porque el problema es una **cola de comandos con respuesta** de bajo volumen. Necesitamos *ack* por mensaje, reintentos con espera y DLQ, que RabbitMQ da sin código adicional y con menos recursos.

**Cambiaríamos a Kafka si:**
1. Varios sistemas nuevos (analítica, fraude, contabilidad, notificaciones) necesitaran leer **los mismos eventos** de forma independiente y a su ritmo.
2. Se exigiera **reproducir** el historial de eventos (*event sourcing*, recalcular proyecciones o auditoría desde el log).
3. El volumen creciera a miles de eventos por segundo con necesidad de particionar por clave (`prestamo_id`) manteniendo orden.

## 7. Contrato de los mensajes

Ver [contratos/](contratos/): JSON Schema del sobre y ejemplos de cada mensaje. Campos obligatorios: `event_id`, `type`, `schema_version`, `occurred_at`, `correlation_id` (= `Idempotency-Key` de la solicitud), `prestamo_id`, `payload`. **Ningún mensaje lleva información financiera del cliente**: Inventario solo recibe producto y cantidad.
