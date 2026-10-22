# Contratos de mensajes (RabbitMQ)

* Esquema del sobre y de cada `payload`: [sobre.schema.json](sobre.schema.json) (JSON Schema 2020-12).
* Ejemplos reales extraídos del outbox durante las pruebas: [ejemplos/](ejemplos/).

| Mensaje | Tipo | Productor → consumidor | Exchange / routing key | Payload |
|---|---|---|---|---|
| `ReservaSolicitada` | comando | Préstamos → Inventario | `credimarket.comandos` / `inventario.reservar` | `producto_id`, `cantidad` |
| `LiberacionSolicitada` | comando | Préstamos → Inventario | `credimarket.comandos` / `inventario.liberar` | `producto_id`, `motivo` |
| `InventarioReservado` | evento | Inventario → Préstamos | `credimarket.eventos` / `inventario.reservado` | `reserva_id`, `producto_id`, `cantidad`, `expira_at` |
| `InventarioInsuficiente` | evento | Inventario → Préstamos | `credimarket.eventos` / `inventario.insuficiente` | `producto_id`, `cantidad_solicitada`, `disponible` |
| `ReservaLiberada` | evento | Inventario → Préstamos | `credimarket.eventos` / `inventario.liberada` | `reserva_id`, `producto_id`, `cantidad_liberada`, `estado_reserva` |
| `ReservaVencida` | evento | Inventario → Préstamos | `credimarket.eventos` / `inventario.vencida` | `reserva_id`, `producto_id`, `cantidad` |
| `SalidaConfirmada` | evento | Inventario → Préstamos | `credimarket.eventos` / `inventario.salida_confirmada` | `reserva_id`, `producto_id`, `cantidad` |

**Versionado:** `schema_version` empieza en 1. Un cambio compatible (agregar un campo opcional) mantiene la versión. Un cambio incompatible sube la versión, y los consumidores aceptan ambas durante la transición. Hoy un consumidor envía a *dead letter* cualquier versión que no soporte.

**Privacidad:** los mensajes **no** transportan ingresos, obligaciones ni otros datos financieros del cliente. Inventario no los necesita.

Las propiedades AMQP replican el sobre: `message_id = event_id`, `type`, `correlation_id`, `delivery_mode = 2` (persistente) y `content_type = application/json`.
