# 9. Decisión 6 — Estrategia de idempotencia

> Objetivo: **una misma operación lógica produce exactamente un efecto**, aunque llegue 4 veces por doble clic, reintentos del cliente, reintentos internos o reentregas del broker.

## 9.1 Principio general: idempotencia en capas

| Capa | Mecanismo | Qué evita |
|---|---|---|
| **Cliente** | La app genera **una `Idempotency-Key` (UUID) por intención** de apostar y la reutiliza en cada reintento. El botón se deshabilita tras el primer clic. | El 90 % de los duplicados nunca llega al servidor, y los que llegan traen la misma clave. |
| **API (HTTP)** | Restricción **UNIQUE** en BD sobre `(usuario_id, idempotency_key)` + hash del cuerpo de la petición. | Doble clic, reintentos por *timeout*, *retries* del Gateway. |
| **Servicio interno (gRPC)** | La Billetera exige `op_key` en toda operación que modifica saldo, con tabla `operaciones` y `UNIQUE(op_key)`. | Reintentos de Apuestas o del Liquidador hacia la Billetera. |
| **Mensajería** | Los consumidores registran el `event_id` / `message_id` procesado **en la misma transacción** que el efecto (*inbox*). | Reentregas de Kafka (*offset* no confirmado) y de RabbitMQ (*ack* perdido). |
| **Dominio** | Claves naturales únicas: un premio por `(liquidacion_id, apuesta_id)`, una liquidación por `(carrera_id, version_resultado)`, una devolución por `apuesta_id`. | Errores lógicos: aunque falle todo lo demás, la BD rechaza el segundo premio. |

> **Redis no es la fuente de verdad de la idempotencia.** Puede usarse como atajo rápido, pero la garantía está en restricciones **durables** de PostgreSQL. Si se borra Redis, no se duplica nada.

## 9.2 Operaciones con riesgo de duplicación (al menos 3 exigidas; identificamos 6)

### ① Realizar una apuesta (el caso de los 4 clics)
- **Riesgo:** 4 solicitudes generan 4 apuestas y 4 débitos de 500 coins.
- **Solución:**
  1. La app envía la **misma** `Idempotency-Key` en los 4 intentos.
  2. Apuestas‑API hace `INSERT … (usuario_id, idempotency_key, hash_cuerpo, estado='PENDIENTE')` con **UNIQUE(usuario_id, idempotency_key)**.
  3. Solo una petición gana el INSERT. Las otras 3 reciben un conflicto y devuelven **la respuesta almacenada** (o `202 PENDIENTE` si la primera aún está en curso).
  4. Si llega la misma clave con **otro contenido** (otro monto o mediano), responde `409 Conflict`.
- **Dónde y por qué:** en el servicio dueño de la apuesta, porque es el único punto por el que pasan todos los intentos y porque la BD serializa las inserciones concurrentes.

### ② Débito en la billetera
- **Riesgo:** Apuestas reintenta `Debitar` tras un *timeout*, pero el primer débito sí se había aplicado.
- **Solución:** `op_key = "apuesta:" + idempotency_key`. La Billetera hace `INSERT INTO operaciones(op_key) …` **dentro de la misma transacción** que el `UPDATE` del saldo y el `INSERT` del movimiento. Ante un conflicto, devuelve el **resultado original** (mismo `movimiento_id` y saldo) sin volver a debitar.
- **Defensa final:** `CHECK (saldo >= 0)` en la tabla `cuentas`.

### ③ Acreditación de premios
- **Riesgo:** un *worker* acredita un lote, se cae antes del *ack* y RabbitMQ reentrega el lote a otro *worker* → doble premio. (*"Ningún mediano debe recibir dos premios"*.)
- **Solución:**
  - `op_key = "premio:" + liquidacion_id + ":" + apuesta_id` en cada ítem de `AcreditarLote`. La Billetera ignora los ítems ya aplicados y devuelve su resultado previo.
  - En la BD de Apuestas: `UNIQUE(liquidacion_id, apuesta_id)` en la tabla `premios`.
  - El lote se marca `COMPLETADO` en la tabla `lotes` y luego se hace el *ack*. Si se reentrega, los ítems ya pagados se saltan.

### ④ Disparo de la liquidación
- **Riesgo:** `ResultadoPublicado` se entrega dos veces (Kafka *at-least-once*) → dos liquidaciones de la misma carrera.
- **Solución:** `UNIQUE(carrera_id, version_resultado)` en la tabla `liquidaciones`. El segundo intento encuentra la liquidación existente y **continúa** la que esté en curso, en lugar de crear otra. Una corrección del resultado (versión 2) es una liquidación **distinta y legítima** (ver Decisión 8, caso C).

### ⑤ Devoluciones por cancelación
- **Riesgo:** `CarreraCancelada` se procesa dos veces, o se cancela una carrera ya en proceso de reembolso → doble devolución.
- **Solución:** `op_key = "devolucion:" + apuesta_id` en la Billetera y `UNIQUE(apuesta_id)` en la tabla `devoluciones`. Además, la máquina de estados de la carrera impide pasar de `CANCELADA` a `CANCELADA`.

### ⑥ Consumo de eventos (notificaciones, auditoría, cuotas, estadísticas)
- **Riesgo:** al reiniciar un consumidor se reprocesan eventos desde el último *offset* confirmado → notificaciones duplicadas, cuotas infladas, registros de auditoría repetidos.
- **Solución por consumidor:**

| Consumidor | Técnica |
|---|---|
| Notificaciones | Tabla `notificaciones_enviadas(event_id, canal)` UNIQUE. Antes de encolar el envío, verifica e inserta. |
| Auditoría (WORM) | El objeto se nombra con `event_id`: escribir dos veces el mismo objeto es inofensivo y la deduplicación se hace al consultar. |
| Proyección de cuotas | Redis: `SADD procesados:{carrera} event_id` + `HINCRBY` en un script Lua atómico. Como son aproximadas, si Redis se pierde se **reconstruyen** desde la BD de Apuestas. |
| Core – Medianos (victorias) | `UNIQUE(carrera_id, version_resultado)` en la tabla de resultados aplicados. |
| Data lake | Deduplicación por `event_id` en la capa de consulta (vista *latest by event_id*). |

## 9.3 ¿Cuánto tiempo se guardan las claves?

| Clave | Retención | Motivo |
|---|---|---|
| `Idempotency-Key` de apuestas | **Permanente** (forma parte de la fila de la apuesta) | Es parte de la evidencia de auditoría. |
| `op_key` en Billetera | **Permanente** (forma parte del ledger) | Trazabilidad de cada movimiento. |
| `event_id` en las tablas *inbox* de consumidores | 30 días (= retención de Kafka) | Pasado ese tiempo, Kafka ya no puede reentregar el evento. |
