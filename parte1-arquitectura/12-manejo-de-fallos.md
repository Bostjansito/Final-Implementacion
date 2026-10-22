# 12. Decisión 8 — Manejo de fallos

## Caso A — El sistema de notificaciones está caído. ¿Se puede seguir apostando?

**Sí.** Notificaciones no está en el camino de la apuesta.

| Aspecto | Comportamiento |
|---|---|
| Apuestas | Funcionan igual: Apuestas publica en Kafka a través del outbox y no sabe si Notificaciones existe. |
| Eventos pendientes | Se acumulan en Kafka (30 días de retención). El grupo `notificaciones` tiene un *lag* creciente. |
| Recuperación | Al volver, el servicio continúa desde su último *offset* confirmado. Los envíos ya hechos no se repiten gracias a `notificaciones_enviadas(event_id, canal)`. |
| Mensajes obsoletos | Cada notificación tiene `expira_at`. "La carrera comenzó" de hace 2 horas se **descarta**. "Ganaste 1.200 coins" **siempre** se envía. |
| Fallo parcial (solo el proveedor de correo) | Solo se llena `notif.email` y se reintenta con *backoff*. `notif.push` sigue funcionando. |
| Experiencia de usuario | La app muestra el estado de la apuesta y el saldo directamente desde las APIs: el usuario no depende de la notificación para saber qué pasó. |

## Caso B — La billetera está caída. ¿Se puede seguir apostando?

**No.** Es una decisión deliberada: **consistencia por encima de disponibilidad** (atributo de calidad #1).

| Aspecto | Comportamiento |
|---|---|
| Por qué no | Sin la billetera no se puede verificar ni descontar el saldo. Aceptar la apuesta "a crédito" y debitar después permitiría **gastar dos veces los mismos coins** o dejar saldos negativos, que el enunciado prohíbe. |
| Detección rápida | *Circuit breaker* en Apuestas‑API: tras N fallos o *timeouts* se abre y se responde **`503` en milisegundos** con el mensaje "Las apuestas están temporalmente suspendidas. Tu saldo no ha sido afectado". |
| Lo que sigue funcionando | Login, consulta de carreras, cuotas (desde caché/CDN), medianos, "mis apuestas" (réplica de Apuestas), panel de administración. |
| Apuestas en vuelo | Quedan `PENDIENTE` y las resuelve el reconciliador cuando la billetera vuelve (sección 10.3). |
| Liquidación en curso | Los lotes no reciben *ack* y RabbitMQ los reintenta con *backoff*. Si la caída amenaza el SLA de 15 min, salta una alerta. Al volver, todo se paga sin duplicados. |
| Si la caída coincide con el cierre de una carrera importante | Decisión del operador desde el panel: **posponer la carrera** (cambia `cierre_at` y emite un evento). Es una decisión de negocio y la arquitectura la soporta. |
| Cómo se reduce la probabilidad | Billetera con ≥ 2 réplicas en distintas zonas, BD Multi‑AZ con *failover* automático (~30–60 s), despliegues graduales (*canary*). |

**Alternativa evaluada y descartada:** asignar a cada usuario un "cupo pre‑reservado" por carrera para apostar sin la billetera. Funcionaría, pero agrega complejidad que hoy no se justifica. Queda como evolución para crecer 100× (ver la pregunta final).

## Caso C (opcional) — Diez minutos después del resultado oficial, se corrige el ganador

**Principio: nunca se borra ni se sobrescribe; se agrega una nueva versión y se compensa.**

1. **Corrección autorizada:** un operador registra la corrección con motivo y **un administrador la aprueba** (doble control, ambos con MFA). Queda `AccionAdministrativa` en el registro WORM.
2. **Nueva versión:** Core guarda `resultado v2` (la v1 se conserva) y emite `ResultadoCorregido(carrera, v2, v1, motivo)`.
3. **Liquidación compensatoria:** el Liquidador crea `liquidaciones(carrera, v2)` (otra clave única, así que es legítima y no un duplicado) y calcula la diferencia por apuesta: `ajuste = premio_v2 − premio_v1`.
   - `ajuste > 0` (nuevos ganadores): crédito con `op_key = "premio:<liq_v2>:<apuesta>"`.
   - `ajuste < 0` (cobraron por error): débito de corrección `AJUSTE_CORRECCION`. **Si el usuario ya gastó los coins**, se debita lo disponible y el resto queda como **deuda registrada** que se descuenta de sus próximos créditos. El saldo **nunca** queda negativo.
4. **Notificación** a los afectados explicando la corrección.
5. **Trazabilidad completa:** resultado v1 y v2, ambos snapshots de liquidación, cada movimiento original y su ajuste, con quién lo hizo y quién lo aprobó.

> Política alternativa válida (decisión de negocio): **la casa absorbe** los premios pagados por error y solo paga a los nuevos ganadores. Es más simple y más amable con el usuario. La arquitectura soporta ambas; se elige por configuración.

**Prevención:** el resultado entra como **provisional** y pasa a oficial tras un control de 3–5 min (revisión del video). La liquidación tarda ~2 min, así que el SLA de 15 min se sigue cumpliendo.

## Otros fallos analizados

| Componente caído | ¿Se sigue apostando? | Comportamiento |
|---|---|---|
| **Kafka** | **Sí** | Los eventos esperan en el outbox de cada BD. Cuotas y notificaciones se retrasan. No se pierde nada. |
| **RabbitMQ** | Sí | Solo afecta a la liquidación y a las notificaciones. La tabla `lotes` guarda el trabajo pendiente y se republica al volver. |
| **Redis** | Sí, degradado | Fallback a la caché local en memoria y a la API interna de Core (llamada S3 de la Decisión 3) con *timeout* corto. Las cuotas se muestran desde la CDN (`stale-if-error`). |
| **Core** | Sí, para carreras ya abiertas | Los datos de la carrera están en Redis. No se pueden crear carreras ni publicar resultados hasta que vuelva. |
| **IdP** | Sí, para sesiones activas | Los JWT siguen siendo válidos hasta su expiración (15 min). No hay nuevos logins. |
| **BD Apuestas (*failover*)** | No durante ~30–60 s | `503` + reintento automático del cliente con la misma clave. |
| **Auditoría y Fraude** | Sí | Se acumula *lag* en Kafka y se pone al día después. |
| **Un *worker* del Liquidador muere** | — | Su lote vuelve a la cola y lo toma otro *worker*. La idempotencia evita el doble pago. |
| **Una zona de disponibilidad completa** | Sí | Todo está en ≥ 2 zonas (Multi‑AZ). Pérdida de una región: fuera del alcance, con *backups* replicados a otra región. |

## Observabilidad (cómo nos enteramos)
- **Métricas**: latencia p99 de `POST /apuestas`, tasa de `503`, apuestas `PENDIENTE` > 5 s, *lag* por grupo de Kafka, longitud de colas y DLQ, duración de la liquidación frente al SLA.
- **Trazas distribuidas** (OpenTelemetry) con `correlation_id` = `Idempotency-Key`.
- **Alertas** al operador de guardia ante: *circuit breaker* abierto, DLQ con mensajes, liquidación > 10 min, descuadre en la reconciliación contable.
