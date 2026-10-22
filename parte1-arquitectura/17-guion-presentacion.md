# 17. Guion de la presentación (máximo 20 diapositivas) y preparación de la sustentación

## 17.1 Diapositivas

| # | Título | Contenido clave | Fuente |
|---|---|---|---|
| 1 | La Gran Liga de Medianos — Arquitectura | Integrantes, idea central: "complejidad necesaria, ni más ni menos". | — |
| 2 | ¿Dónde está lo difícil? | Los 9 impulsores en 3 grupos: pico de apuestas, dinero, *fan-out* de eventos. Cálculos: 300k apuestas en 30 s, 10k tx/s en la billetera, 33k lecturas/s → CDN. | 01 |
| 3 | Decisión 1: arquitectura híbrida | Esquema Core + 4 componentes. Tabla de criterios (escalabilidad, resiliencia, consistencia, seguridad, costo). | 02 |
| 4 | Alternativas descartadas | Monolito, microservicios puros, monolito modular puro: por qué no. | 02 |
| 5 | Decisión 2: servicios y responsabilidades | Mapa capacidad → componente. Criterio de extracción. Por qué Medianos no es un servicio. | 03 |
| 6 | Diagrama general | Diagrama con líneas sólidas (síncrono) y punteadas (asíncrono), zona pública y privada. | 04 |
| 7 | Decisión 3: comunicación síncrona | Tabla resumida (S1, S2, S4, S6) + timeouts y *fallbacks*. "Lo que deliberadamente NO es síncrono". | 05 |
| 8 | Decisión 4: eventos | Tabla de eventos principales con clave de partición. Eventos fusionados (`CarreraIniciada`, `CarreraFinalizada`). | 06 |
| 9 | Decisión 5: Kafka + RabbitMQ | "Kafka recuerda lo que pasó; RabbitMQ reparte lo que hay que hacer". Por qué no uno solo. | 07, ADR‑002 |
| 10 | Diseño de Kafka | Topics, particiones, claves, grupos de consumidores, outbox + Debezium. | 07 |
| 11 | Diseño de RabbitMQ | Exchange → colas → *workers*, reintentos con TTL, DLQ, KEDA. | 07 |
| 12 | Secuencia de una apuesta | Diagrama de secuencia + presupuesto de latencia. | 08 |
| 13 | Decisión 6: idempotencia | Los 4 clics paso a paso. Tabla de 6 operaciones con su clave única. | 09 |
| 14 | Decisión 9: datos y consistencia | BD por servicio, fuerte vs. eventual, saga corta `PENDIENTE` + reconciliador, ledger. | 10 |
| 15 | Decisión 7: 10.000 apuestas/s | Cuellos de botella, qué escala, *load shedding*, cierre y saldo en paralelo. | 11 |
| 16 | Decisión 8: fallos | Caso A (sí), caso B (no, y por qué), caso C (versionar y compensar). | 12 |
| 17 | Seguridad | Diagrama público/privado, IdP + MFA, doble control, mTLS a Billetera, WORM. | 13 |
| 18 | Costos | 5 desplegables, réplicas normal vs. Copa, escalado a cero, *spot*, CDN. | 14 |
| 19 | ADRs | Las 3 decisiones en formato resumido. | 15 |
| 20 | Pregunta final y conclusiones | Hoy vs. 100× (etapas con disparadores) y 3 conclusiones clave. | 16 |

## 17.2 Preparación para el cambio de requisitos en vivo

El enunciado anticipa un cambio en la sustentación (ejemplo: **apuestas en vivo**). Respuestas preparadas:

### Cambio 1 — Permitir apuestas en vivo (durante la carrera)

| Aspecto | Impacto en la arquitectura |
|---|---|
| Estados de la carrera | Nuevo estado `EN_CURSO_APUESTAS_ABIERTAS`, o un mercado en vivo separado con su propio cierre (p. ej., a 100 m de la meta). La máquina de estados en Core se extiende. |
| Modelo de premios | La bolsa mutua no funciona igual si se apuesta conociendo posiciones. Opción: **bolsa separada por "tramo"** (cada tramo con su propio cierre y bolsa) o **cuotas fijas** al momento de apostar (la casa asume el riesgo). Es una decisión de negocio. |
| Nuevos eventos | `PosicionesActualizadas` (telemetría de la carrera, Kafka, clave `carrera_id`) y `MercadoSuspendido`/`MercadoReanudado`. |
| Riesgo de *past-posting* | El apostador ve el video antes que el sistema. Se agrega un **retraso de aceptación** de 3–5 s: la apuesta queda `PENDIENTE` y se acepta solo si el mercado no se suspendió en ese intervalo. Rompe el "< 1 s" solo para este tipo de apuesta, así que se documenta como ajuste del supuesto. |
| Tiempo real | Las cuotas cambian cada segundo: se pasa de *polling* + CDN a **WebSocket/SSE** (servicio administrado) alimentado por Kafka. |
| Carga | El pico deja de ser solo previo al cierre y se reparte durante la carrera. Apuestas y Billetera ya escalan horizontalmente. |
| Fraude | Nuevas reglas: apuestas sincronizadas con eventos de la carrera y latencia sospechosamente baja. |
| **Lo que no cambia** | Idempotencia, ledger, outbox, liquidación por lotes, auditoría. El diseño lo absorbe con cambios **locales** (Core – Carreras, Apuestas, un *push* nuevo). |

### Otros cambios probables (respuestas cortas)

| Cambio | Respuesta |
|---|---|
| Apuestas a podio (1.º, 2.º, 3.º) o exactas | Nuevo `tipo_apuesta` en Apuestas, una bolsa por tipo y el Liquidador calcula por tipo. Eventos con un campo adicional (`schema_version` 2). |
| Comprar o recargar EIA Coins | Nuevo flujo en la Billetera (`CREDITO_RECARGA`) con proveedor de pagos externo, idempotencia por `payment_id` y cumplimiento normativo. Cambia el perfil de seguridad (PCI) y se aísla todavía más la Billetera. |
| Multi‑universidad / multipaís | Arquitectura por celdas (etapa 4 de la evolución). `tenant_id` en eventos y datos. |
| Liquidación en < 1 min | Más *workers* (KEDA) y lotes más grandes con `AcreditarLote`. Hoy tarda ~2 min, así que se cumple ajustando parámetros. |
| La auditoría debe guardarse 10 años | Cambiar la política de Object Lock y el ciclo de vida a Glacier. Sin cambios en los servicios. |
