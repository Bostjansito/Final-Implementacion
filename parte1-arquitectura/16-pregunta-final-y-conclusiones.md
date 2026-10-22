# 16. Pregunta final y conclusiones

## Pregunta final

> *Si ustedes fueran los responsables técnicos de Salchipapa Maker Racing S.A.S., ¿qué arquitectura implementarían hoy y cómo permitirían que evolucionara si la plataforma creciera 100 veces?*

### Hoy

Implementaríamos la **arquitectura híbrida** descrita: un **monolito modular** para el núcleo de bajo tráfico y **cuatro componentes independientes** (Apuestas con su Liquidador, Billetera, Notificaciones, Auditoría y Fraude) sobre **servicios administrados**, con **Kafka** como log de eventos y **RabbitMQ** para el trabajo por lotes.

| Criterio | Cómo lo cumple la arquitectura de hoy |
|---|---|
| **Complejidad** | 5 desplegables. Cada separación tiene una razón medible. El Core evita sagas innecesarias. |
| **Escalabilidad** | Solo escalan Apuestas, Billetera y el Liquidador. La CDN absorbe las lecturas masivas. Escalado programado para la Copa. |
| **Resiliencia** | Asincronía donde se tolera retraso. Outbox ante caídas de Kafka. Colas con reintentos y DLQ. *Circuit breakers*. Multi‑AZ. |
| **Consistencia** | Ledger ACID, débito atómico, idempotencia en 5 capas, saga corta con reconciliador, barrera de cierre. |
| **Seguridad** | IdP + MFA, RBAC con doble control, Billetera aislada con mTLS, WAF y *rate limiting*, auditoría WORM a 5 años. |
| **Costo** | Base pequeña, escalado a cero y por calendario, almacenamiento barato por niveles. |
| **Mantenibilidad** | Módulos con fronteras explícitas, contratos versionados (*Schema Registry*), ADRs. |

### Si la plataforma crece 100×

100× significa ~10 M de usuarios concurrentes en un gran evento y ~1 M de apuestas/s en el pico. **No se rediseña todo de golpe**: se evoluciona por etapas, activadas por **métricas concretas** (*fitness functions*), no por moda.

| Etapa | Disparador (métrica) | Cambio |
|---|---|---|
| **1. Escalar lo existente (≈10×)** | CPU de la BD de la Billetera > 60 % en el pico; p99 de apuesta > 400 ms | Aumentar el tamaño de las BD, más réplicas de lectura, más particiones en Kafka, pasar a Aurora PostgreSQL. **Sin cambios de código.** |
| **2. Particionar los datos calientes** | La BD de la Billetera no escala verticalmente | ***Sharding* de la Billetera por `usuario_id`** (N *shards*; el débito de un usuario siempre va al mismo *shard*, sin transacciones entre *shards*). La BD de Apuestas se particiona por `carrera_id`/`usuario_id` (Citus o Aurora Limitless). |
| **3. Sacar a la Billetera del camino caliente** | Incluso con *shards*, la llamada síncrona por apuesta limita | **Cupo pre‑reservado por carrera**: el usuario "carga" un monto para la carrera (un único débito en la Billetera) y Apuestas descuenta localmente de ese cupo en su propio *shard*. Al cerrar, el sobrante se devuelve. Mantiene "nunca gastar dos veces" con menos llamadas. |
| **4. Arquitectura por celdas** | Picos regionales; radio de explosión de un fallo demasiado grande | **Celdas** (Apuestas + Billetera + BD por grupo de usuarios), enrutadas en el Gateway por `usuario_id`. Un fallo afecta solo a una celda. Multirregión activa‑activa por celdas. |
| **5. Extraer módulos del Core** | Equipos que se bloquean entre sí; Usuarios con decenas de millones de cuentas | Extraer **Usuarios** y **Carreras** como servicios (sus fronteras y esquemas ya están separados). |
| **6. Tiempo real y datos** | Cuotas por *polling* demasiado caras; analítica más exigente | Servicio de *push* (WebSocket/SSE administrado) para cuotas. Kafka con *tiered storage*. Procesamiento de *streams* (Flink) para cuotas y fraude. *Lakehouse* (Iceberg) para analítica. |
| **7. Simplificar mensajería (opcional)** | El costo de operar dos brokers supera su beneficio | Migrar la liquidación a Kafka. El cambio queda aislado en el Liquidador (ADR‑002). |

**Lo que no cambia aunque crezca 100×:** contratos de eventos versionados, idempotencia por clave, ledger *append-only*, outbox, auditoría WORM. **Por eso son las decisiones que tomamos con más cuidado hoy.**

## Conclusiones

1. **La complejidad se concentra donde está el riesgo.** De 9 capacidades, solo 3 (apostar, billetera, liquidar) justifican infraestructura independiente. Las demás viven en un monolito modular barato y simple.
2. **Síncrono solo donde el usuario espera una respuesta definitiva**: aceptar la apuesta y descontar el saldo. Todo lo demás es asíncrono, y eso hace que la caída de notificaciones, analítica o auditoría **no detenga las apuestas**.
3. **Kafka y RabbitMQ no compiten: se complementan.** Kafka recuerda lo que pasó (*fan-out*, historia, reproducción). RabbitMQ reparte lo que hay que hacer (lotes, reintentos, DLQ). Ambos administrados, para que la complejidad sea de configuración y no de operación.
4. **La idempotencia es la garantía más importante del sistema.** Los brokers entregan *al menos una vez*. Solo restricciones únicas durables y claves de operación convierten eso en "exactamente un efecto". **Ningún mediano recibe dos premios porque alguien presionó cuatro veces el botón.**
5. **Consistencia por encima de disponibilidad para el dinero.** Si la Billetera no responde, no se apuesta. Es una decisión explícita, defendible y comunicada al usuario.
6. **El costo es un requisito de arquitectura**: escalado a cero, escalado programado, CDN para lecturas y almacenamiento por niveles. No es una "infraestructura de Netflix".
7. **La arquitectura está preparada para evolucionar, no sobredimensionada.** Cada paso hacia 100× tiene un disparador medible y aprovecha fronteras que ya existen hoy.
