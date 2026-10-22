# 5. Decisión 3 — Comunicación síncrona

## Regla que usamos para decidir

> Una llamada es **síncrona solo si quien llama no puede continuar ni responder al usuario sin la respuesta**. Todo lo demás se comunica con eventos.

Protocolos:
- **HTTPS/REST** entre el cliente y la plataforma (a través del API Gateway), porque es universal y cacheable en la CDN.
- **gRPC** entre servicios internos del camino caliente (Apuestas/Liquidador → Billetera). Usa contratos tipados (Protobuf), conexiones HTTP/2 persistentes, baja latencia y *deadlines* nativos.

## Tabla de comunicaciones síncronas

| # | Servicio origen | Servicio destino | Protocolo | Información solicitada | ¿Por qué debe ser síncrona? |
|---|---|---|---|---|---|
| S1 | App (vía Gateway) | Apuestas‑API | HTTPS REST `POST /apuestas` | Crear una apuesta (carrera, mediano, monto, `Idempotency-Key`) | El usuario debe saber en < 1 s si fue **aceptada o rechazada**. |
| S2 | Apuestas‑API | Billetera | gRPC `Debitar(op_key, usuario, monto, ref_apuesta)` | Descontar el monto si hay saldo suficiente | No se puede aceptar la apuesta sin saber si el débito se realizó. Es la garantía contra el doble gasto. |
| S3 | Apuestas‑API | Core (Carreras) | HTTPS REST interno `GET /internal/carreras/{id}` | Estado, `cierre_at` y participantes | **Solo ante un fallo de caché** (*cache miss*) de Redis. Sin estos datos no se puede validar la apuesta. |
| S4 | Apuestas‑Liquidador | Billetera | gRPC `AcreditarLote([op_key, usuario, monto]…)` | Acreditar premios o devoluciones de un lote | El *worker* necesita la confirmación para hacer el *ack* del lote en RabbitMQ. Sin confirmación, el lote se reintenta. |
| S5 | Apuestas (reconciliador) | Billetera | gRPC `ConsultarOperacion(op_key)` | ¿Se aplicó este débito? | Para resolver apuestas que quedaron en `PENDIENTE` tras un fallo. |
| S6 | App (vía Gateway) | Billetera | HTTPS REST `GET /billetera/saldo`, `GET /billetera/movimientos` | Saldo y movimientos propios (solo lectura) | El usuario consulta su saldo y espera el dato al instante. |
| S7 | App (vía CDN/Gateway) | Core | HTTPS REST `GET /carreras`, `GET /medianos/{id}` | Catálogo de carreras y medianos | Consulta directa del usuario. Es **cacheable en la CDN**. |
| S8 | App (vía CDN/Gateway) | Apuestas‑API | HTTPS REST `GET /carreras/{id}/cuotas` | Cuotas estimadas | Consulta directa. Se cachea en la CDN 1–2 s. |
| S9 | Panel admin (vía Gateway) | Core (Admin/Carreras) | HTTPS REST | Crear carreras, publicar o corregir resultados, bloquear usuarios | El operador necesita confirmación inmediata de la acción administrativa. |
| S10 | Core (Usuarios) | IdP | HTTPS (API de administración del IdP) | Revocar sesiones al bloquear un usuario | El bloqueo debe ser efectivo de inmediato. |
| S11 | App | IdP | OIDC (Authorization Code + PKCE) | Login y emisión de tokens | Flujo estándar de autenticación. |
| S12 | Panel auditor (vía Gateway) | Auditoría y Fraude | HTTPS REST | Consultas de trazabilidad y reconstrucción de liquidaciones | El auditor consulta el resultado. Las consultas pesadas se ejecutan como trabajo asíncrono (`202` + consulta posterior). |

### Lo que deliberadamente **no** es síncrono
| Posible llamada | Por qué no |
|---|---|
| Apuestas → Usuarios ("¿existe el usuario?") | El JWT firmado por el IdP ya prueba que el usuario existe. El estado de **bloqueado** llega por el evento `UsuarioBloqueado` y se guarda en un conjunto en Redis. Se ahorra un salto de red en cada apuesta. |
| Apuestas → Notificaciones | Una falla de notificaciones **no debe** impedir una apuesta. Se resuelve con eventos. |
| Core → Liquidador ("liquida esta carrera") | 1 M de apuestas no caben en una petición HTTP. El evento `ResultadoPublicado` dispara el trabajo. |
| Cualquiera → Analítica/Auditoría | Toleran retraso. Consumen de Kafka. |

## ¿Qué pasa si el destino no responde a tiempo?

| # | Timeout | Reintento | Respuesta alternativa |
|---|---|---|---|
| S1 | Cliente: 3 s | El cliente reintenta **con la misma `Idempotency-Key`** (nunca crea una nueva), con *backoff* y *jitter*. El botón queda deshabilitado mientras tanto. | Muestra "Verificando tu apuesta…" y consulta `GET /apuestas/{key}`. **Nunca** muestra un éxito falso. |
| S2 | *Deadline* gRPC de 300 ms | 1 reintento inmediato con la **misma `op_key`** (el débito es idempotente). | *Circuit breaker*: si se abre, Apuestas responde `503` en milisegundos ("Apuestas temporalmente no disponibles"). La apuesta queda `PENDIENTE` y la resuelve el reconciliador (ver Decisión 9). **No** se acepta la apuesta sin débito. |
| S3 | 200 ms | 1 reintento | Usa la caché local en memoria (los datos de una carrera `ABIERTA` casi no cambian). Si no hay ningún dato, rechaza con `503`: nunca se acepta una apuesta sin verificar la carrera. |
| S4 | 2 s por lote | No se hace *ack*, así que RabbitMQ reentrega con *backoff* (máximo 5 intentos). | Tras 5 fallos el lote va a la DLQ y salta una alerta al operador. Reprocesarlo es seguro gracias a la idempotencia. |
| S5 | 1 s | El reconciliador reintenta en su siguiente ciclo (cada 10 s). | La apuesta sigue `PENDIENTE` hasta que la Billetera responda. Bloquea el inicio de la liquidación de esa carrera (ver la "barrera de cierre"). |
| S6 | 1 s | 1 reintento | Mensaje "Saldo no disponible en este momento". No afecta las apuestas ya aceptadas. |
| S7 / S8 | 2 s | Lo gestiona la CDN | La CDN sirve contenido **obsoleto** (`stale-if-error`): mejor una cuota de hace 30 s que un error. |
| S9 / S10 | 5 s | No hay reintento automático en acciones administrativas | Error visible al operador. La acción es idempotente (lleva su propio `request_id`), así que el operador puede reintentar sin duplicarla. |
| S12 | 10 s | — | Las consultas largas devuelven `202` con un `job_id`. |

Todos los clientes internos usan **timeouts explícitos**, **circuit breakers** (por ejemplo, con Resilience4j o la librería equivalente del lenguaje) y **reintentos solo sobre operaciones idempotentes**.
