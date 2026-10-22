# 15. Registros de decisiones arquitectónicas (ADR)

Las 3 decisiones más importantes. Formato: contexto, opciones, decisión, consecuencias.

---

## ADR‑001 — Arquitectura híbrida: monolito modular + servicios para el camino crítico

**Estado:** Aceptada

**Contexto.** La plataforma tiene 9 capacidades, pero la carga y el riesgo se concentran en pocas: apuestas (10.000/s en el pico), billetera (doble gasto) y liquidación (1 M de apuestas en < 15 min). El resto (usuarios, medianos, carreras) es CRUD de bajo tráfico. Hay restricción de costo explícita y un equipo pequeño.

**Opciones.**
1. Monolito tradicional.
2. Microservicios por capacidad (~10 servicios).
3. Monolito modular puro.
4. **Híbrida:** Core modular + servicios separados donde la carga, la criticidad o la asincronía lo exigen.

**Decisión.** Opción 4. Core (Usuarios, Medianos, Carreras/Resultados, Admin) como monolito modular. Servicios independientes: Apuestas (API + Liquidador), Billetera, Notificaciones, Auditoría y Fraude. Criterio de extracción: carga distinta, criticidad/seguridad o trabajo asíncrono.

**Consecuencias.**
- ➕ Solo escala lo que recibe el pico. Costo base bajo (5 desplegables).
- ➕ Los fallos de componentes secundarios no detienen las apuestas.
- ➕ Billetera aislada: menor superficie de ataque.
- ➖ Hay que vigilar las fronteras dentro del Core (esquemas separados, pruebas de arquitectura) para que no se convierta en un monolito enredado.
- ➖ Separar Apuestas y Billetera exige coordinación (ADR‑003).
- 🔁 Si un módulo del Core crece (p. ej., Usuarios con millones de cuentas), se puede extraer gracias a sus fronteras explícitas.

---

## ADR‑002 — Kafka para eventos de negocio y RabbitMQ para colas de trabajo

**Estado:** Aceptada

**Contexto.** Los mismos hechos (`ApuestaRealizada`, `MovimientoRegistrado`, `ResultadoPublicado`) los consumen 4–6 componentes con ritmos distintos (cuotas en segundos, analítica en minutos, auditoría con retención de 5 años y reconstrucción). Por otro lado, la liquidación necesita repartir ~1.000 lotes entre N *workers* con reintento por lote y DLQ, y las notificaciones necesitan reintentos por canal.

**Opciones.**
1. Solo RabbitMQ.
2. Solo Kafka.
3. **Kafka + RabbitMQ**, cada uno en su caso de uso.
4. Ninguno (HTTP directo).

**Decisión.** Opción 3, ambos **administrados**. Kafka: log de eventos con 30 días de retención, clave por entidad (`carrera_id`, `usuario_id`), outbox + Debezium como productor, *sink* a S3 para la historia larga. RabbitMQ: *exchanges* direct, *quorum queues*, *ack* manual, reintentos con TTL y DLQ, *workers* con escalado KEDA.

**Consecuencias.**
- ➕ *Fan-out* y reproducción de eventos (auditoría, recalcular analítica, reconstruir cuotas).
- ➕ Liquidación simple, paralela y tolerante a fallos por lote.
- ➕ Productores desacoplados: Kafka caído no detiene las apuestas (outbox).
- ➖ Dos tecnologías que aprender y monitorear (se mitiga con servicios administrados y un uso acotado de RabbitMQ: 5 colas).
- ➖ Entrega *al menos una vez* → **todos** los consumidores deben ser idempotentes.
- 🔁 Si el equipo necesita simplificar, la liquidación puede migrarse a Kafka (topic de lotes + reintentos). El cambio queda aislado en el Liquidador.

---

## ADR‑003 — Billetera como ledger independiente con débito síncrono idempotente y saga corta en Apuestas

**Estado:** Aceptada

**Contexto.** Requisitos: responder en < 1 s si la apuesta fue aceptada, no perder ninguna apuesta ni movimiento y **nunca gastar dos veces** los coins. La billetera la usan tres flujos (apuestas, premios, devoluciones). Los clientes reintentan (4 clics).

**Opciones.**
1. Apuestas y Billetera en un mismo servicio y BD (una transacción local).
2. **Billetera separada**, débito **síncrono** (gRPC) e idempotente, con estado `PENDIENTE` en la apuesta y reconciliador.
3. Billetera separada con débito **asíncrono** (apuesta encolada; débito posterior por evento).
4. Transacción distribuida (2PC/XA).

**Decisión.** Opción 2.
- Apuestas inserta `PENDIENTE` con `UNIQUE(usuario_id, idempotency_key)` → llama `Debitar(op_key)` → marca `ACEPTADA` + outbox en una transacción.
- La Billetera aplica `UPDATE … WHERE saldo >= monto`, `UNIQUE(op_key)` y `CHECK (saldo >= 0)` en una sola transacción ACID con el movimiento y el outbox.
- Un reconciliador resuelve las `PENDIENTE` consultando `ConsultarOperacion(op_key)`.
- Si la Billetera no está disponible, **no se aceptan apuestas** (*circuit breaker* → `503`).

**Consecuencias.**
- ➕ Consistencia fuerte del saldo. Sin doble gasto ni saldos negativos, ni siquiera con miles de peticiones en paralelo.
- ➕ Cumple < 1 s (~100–250 ms totales).
- ➕ Ledger aislado, *append-only* y auditable, reutilizado por premios y devoluciones.
- ➖ Dos escrituras en BD distintas por apuesta → hace falta la saga corta, el reconciliador y la "barrera de cierre" antes de liquidar.
- ➖ La BD de la Billetera es el cuello de botella del pico (~10.000 tx/s): requiere dimensionamiento y pruebas de carga. Su evolución es el *sharding* por usuario.
- ➖ Disponibilidad de apuestas = disponibilidad de la Billetera (aceptado conscientemente: consistencia > disponibilidad).
- ❌ Opción 1 descartada por mezclar el activo más sensible con la lógica de apuestas. Opción 3 por no poder responder "aceptada/rechazada" de forma fiable en < 1 s. Opción 4 por ser lenta, frágil e incompatible con los brokers.
