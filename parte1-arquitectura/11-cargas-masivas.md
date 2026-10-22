# 11. Decisión 7 — Grandes volúmenes: 10.000 apuestas/s en los 30 s previos al cierre

## 11.1 El pico en números

| Métrica | Valor |
|---|---|
| Apuestas en la ventana | 300.000 en 30 s |
| Escrituras en BD Apuestas | ~20.000/s (INSERT `PENDIENTE` + UPDATE `ACEPTADA`) |
| Transacciones en BD Billetera | ~10.000/s (cada una: 1 UPDATE + 3 INSERT cortos) |
| Eventos hacia Kafka | ~20.000/s (apuesta + movimiento) ≈ 10–20 MB/s |
| Lecturas de cuotas y carreras | ~33.000/s, **absorbidas por la CDN** |

## 11.2 Cuellos de botella y cómo se atacan

| # | Cuello de botella | Mitigación |
|---|---|---|
| 1 | **BD de la Billetera** (~10.000 transacciones/s) | Transacciones muy cortas (≈1 ms de bloqueo). **No hay filas calientes**: cada usuario bloquea solo su fila, y la cuenta de la casa **no** se toca por apuesta (la comisión se registra al liquidar). Instancia grande con almacenamiento de IOPS provisionadas. *Pooling* de conexiones (RDS Proxy / PgBouncer). Validado con pruebas de carga a 15.000/s. Plan de evolución: *sharding* por `usuario_id` (ver la pregunta final). |
| 2 | **BD de Apuestas** (~20.000 escrituras/s) | Tabla particionada, índices mínimos, `fillfactor` reducido para que los UPDATE sean HOT. La réplica de lectura absorbe "mis apuestas" y la liquidación. |
| 3 | **Conexiones a BD** (cientos de *pods*) | *Pooler* de conexiones delante de cada PostgreSQL. |
| 4 | **Lecturas de cuotas y carreras** | **CDN** con `Cache-Control: max-age=1–2`, `stale-while-revalidate`. El origen recibe ~1 petición/s por recurso, sin importar si hay 500 o 100.000 usuarios. |
| 5 | **Validaciones por apuesta** | Todo desde **Redis** o desde la caché local en memoria: estado de la carrera, `cierre_at`, participantes, bloqueados. Ninguna llamada a Core en el camino caliente. |
| 6 | **Publicación de eventos** | Outbox leído por **Debezium desde el WAL**: no compite con las peticiones ni hace *polling* sobre la tabla. |
| 7 | **Bots que inundan** | WAF + *bot control* + **rate limit por usuario, IP y dispositivo** en el Gateway (p. ej., 5 apuestas/s por usuario). |

## 11.3 Qué escala y qué no

| Componente | ¿Escala con el pico? | Cómo |
|---|---|---|
| Apuestas‑API | **Sí, mucho** (2 → ~40 *pods*) | HPA por CPU/RPS + **escalado programado** 30 min antes de carreras importantes (el calendario se conoce). |
| Billetera (*pods*) | **Sí** (2 → ~15) | HPA. Su límite real es la BD, no los *pods*. |
| BD Billetera / BD Apuestas | Verticalmente, planificado | Tamaño dimensionado para el pico conocido (la Copa está en el calendario). La escala horizontal es la evolución futura. |
| Liquidador *workers* | **Sí, a demanda** (0 → ~30) | **KEDA** según la longitud de la cola de RabbitMQ. En 0 entre carreras. |
| Notificaciones *senders* | Sí, a demanda (0 → N) | KEDA según la cola por canal. |
| Kafka | No en el pico (ya tiene holgura de 10×) | Particiones preasignadas. |
| Core | **No** (2–3 réplicas fijas) | Sus lecturas se sirven desde la CDN y Redis. |
| Auditoría y Fraude | Poco | Si se atrasa, solo aumenta su *lag* en Kafka y luego se pone al día. |
| Redis | No | Un clúster pequeño aguanta cientos de miles de operaciones/s. |

## 11.4 ¿Cómo se absorben los picos y qué pasa si se supera la capacidad?

1. **Preparación (antes del pico):** escalado programado, *warm-up* de Redis con la carrera y sus participantes al abrirla (`CarreraAbierta`), prueba de humo.
2. **Durante el pico:** el CDN quita la carga de lectura. El Gateway recorta abusos. La API valida en memoria o Redis y hace dos escrituras cortas.
3. **Si aun así se satura (*load shedding*):** cuando la latencia p99 de la Billetera supera un umbral, Apuestas‑API responde **`503 Retry-After`** de inmediato, en lugar de encolar sin límite. La app reintenta automáticamente **con la misma `Idempotency-Key`** y con *jitter*. Es mejor un rechazo rápido y reintentable que una petición colgada que deja al usuario sin respuesta.

> **¿Por qué no encolamos las apuestas (RabbitMQ/Kafka) y respondemos "recibida"?** Porque el requisito exige que el usuario sepa **en menos de 1 s si fue aceptada o rechazada**, y la aceptación depende del saldo. Una cola solo aplazaría la respuesta. Las colas se usan **después** de aceptar (eventos) y para la liquidación, no en la decisión.

## 11.5 ¿Cómo se evita perder información?

| Punto | Garantía |
|---|---|
| Antes de responder `201` | La apuesta y el débito ya están **confirmados en disco** en PostgreSQL Multi‑AZ con réplica síncrona (RPO = 0). |
| Eventos | Outbox en la misma transacción → Debezium → Kafka con `acks=all`, RF = 3. Si Kafka cae, los eventos esperan en el outbox. |
| Tareas de liquidación | La tabla `lotes` en BD es la fuente de verdad. RabbitMQ usa *quorum queues* + *publisher confirms*. Un lote "publicado y no completado" se vuelve a publicar. |
| Respuesta perdida en la red | El cliente consulta o reintenta con su clave y obtiene el resultado real. |

## 11.6 Validar el cierre y evitar saldos negativos en paralelo

**Cierre (40 *pods* en paralelo, sin coordinación entre ellos):**
- `cierre_at` se fija al abrir la carrera y viaja en `CarreraAbierta`. Cada *pod* lo tiene en Redis o en memoria.
- Cada *pod* toma `recibida_at` de **su reloj, sincronizado por NTP** (Amazon Time Sync, error < 1 ms) al **recibir** la petición, y rechaza si `recibida_at >= cierre_at`.
- La apuesta guarda `recibida_at`. Un **CHECK en BD** (`recibida_at < cierre_at` copiado en la fila) es una segunda barrera.
- Si se **cancela** una carrera, las apuestas aceptadas en los milisegundos que tarda el evento en llegar se reembolsan con el flujo de cancelación: no hay pérdida.

**Saldos negativos (miles de débitos en paralelo):**
- `UPDATE … WHERE saldo >= monto` es atómico: PostgreSQL bloquea la fila del usuario, así que dos débitos del mismo usuario se **serializan**. El segundo ve el saldo ya reducido.
- `CHECK (saldo >= 0)` es la defensa final, aunque haya un error en el código.
- No se usan cachés de saldo para decidir: **el saldo solo se lee y escribe en la BD de la Billetera**.
