# 14. Consideraciones de costo

> Regla de Dyllan: *"No quiero pagar una infraestructura de Netflix para una carrera de cinco medianos."*

## 14.1 ¿Cuántos servicios necesitamos realmente?

**5 desplegables propios + 1 consumidor**, no 10 o 20:

| Desplegable | Réplicas en semana normal | Réplicas en la final de la Copa |
|---|---|---|
| Core (monolito modular) | 2 | 3 |
| Apuestas‑API | 2 | ~40 (escalado programado + HPA) |
| Apuestas‑Liquidador | **0** (KEDA) | ~30 durante ~2 min |
| Billetera | 2 | ~15 |
| Notificaciones | **0–1** (KEDA) | 5–10 |
| Auditoría y Fraude | 1 | 2–3 |

Cada servicio separado se justifica por **carga, criticidad o naturaleza asíncrona** (ver la Decisión 1). Medianos, Usuarios, Carreras y Resultados **no** pagan su propia infraestructura.

## 14.2 Qué comparte infraestructura

| Recurso compartido | Quiénes lo usan | Cómo se mantiene el aislamiento |
|---|---|---|
| **Un clúster de Kubernetes administrado** (EKS) | Todos los desplegables | *Namespaces*, cuotas de recursos, *network policies*. |
| **Una instancia PostgreSQL "Core"** | Módulos del Core + Notificaciones | Un esquema y un usuario por módulo. |
| **Un clúster Redis** | Apuestas (estado de carreras, cuotas, bloqueados), Gateway (*rate limiting*) | Prefijos de claves. Nada crítico depende de Redis. |
| **Un clúster Kafka** | Todos los productores y consumidores | Topics y ACL por servicio. |
| **Un *broker* RabbitMQ** | Liquidador y Notificaciones | *Vhosts* separados. |
| **Un *bucket*/data lake** | Analítica y Auditoría | Prefijos y políticas distintas (WORM solo para auditoría). |

**Qué NO se comparte (y por qué vale la pena pagarlo):** la **BD de la Billetera** (criticidad financiera, Multi‑AZ síncrona) y la **BD de Apuestas** (es la que recibe el pico de escrituras).

## 14.3 Dónde usar servicios administrados

| Necesidad | Servicio administrado | Por qué no autogestionarlo |
|---|---|---|
| Autenticación | Cognito / Auth0 | La seguridad de contraseñas y MFA no es nuestro negocio. |
| Bases de datos | RDS/Aurora PostgreSQL | *Backups*, PITR, Multi‑AZ y parches incluidos. |
| Kafka | MSK (Serverless en baja escala) / Confluent Cloud | Operar Kafka (discos, rebalanceos, upgrades) consume mucho tiempo del equipo. |
| RabbitMQ | Amazon MQ / CloudAMQP | Lo mismo. |
| Redis | ElastiCache | — |
| Borde | CloudFront + WAF + API Gateway | Escala de forma automática ante 100.000 usuarios sin servidores propios. |
| Notificaciones | SES (correo), FCM/APNs (*push*) | Entregabilidad y reputación de envío. |
| Analítica | S3 + Athena (pago por consulta) | Sin un *warehouse* encendido 24/7. Redshift Serverless solo para reportes premium. |
| Video en vivo | Servicio de *streaming* administrado + CDN | Fuera del núcleo del negocio. |

## 14.4 Cómo evitar infraestructura innecesaria

1. **Escalar a cero** lo que trabaja por ráfagas: Liquidador y Notificaciones (KEDA según la longitud de la cola).
2. **Escalado programado** para la Copa (el calendario de carreras se conoce) en lugar de sobredimensionar todo el año.
3. **La CDN como "servidor" de lecturas masivas**: 33.000 lecturas/s de cuotas cuestan centavos en la CDN, frente a decenas de *pods* en el origen.
4. ***Spot instances*** para los *workers* del Liquidador: si AWS los reclama, el lote vuelve a la cola y la idempotencia evita duplicados. Ahorro típico del 60–70 %.
5. **Ciclo de vida del almacenamiento**: auditoría en S3 Standard 90 días → Glacier Instant/Deep Archive hasta completar 5 años. Kafka guarda solo 30 días.
6. **Parquet comprimido + particiones por fecha** en el data lake, para que Athena escanee (y cobre) menos.
7. **Sin *service mesh* completo**: mTLS solo donde hay dinero (hacia la Billetera), con certificados emitidos por la plataforma. Se evalúa un *mesh* ligero (Linkerd) solo si el número de servicios crece.
8. **Entornos de desarrollo y pruebas efímeros** y apagados fuera de horario.
9. **Reservas o *Savings Plans*** para la capa base estable (Core, BD), una vez conocido el consumo real.

## 14.5 Perfil de costo (orden de magnitud)

| Bloque | Peso relativo | Comentario |
|---|---|---|
| Bases de datos (Billetera + Apuestas + Core) | **Alto** | Es el gasto que **sí** se justifica: integridad y cero pérdida. |
| Kafka + RabbitMQ administrados | Medio | Kafka pequeño (holgura de 10× sobre el pico). RabbitMQ con pocas colas. |
| Cómputo (EKS) | Medio en la Copa, **bajo** en semana normal | Escalado programado y a cero. |
| CDN + WAF + Gateway | Bajo–medio | Proporcional al tráfico real. |
| Almacenamiento (lake + auditoría 5 años) | Bajo | ~0,2–0,4 TB/año comprimido, mayormente en Glacier. |

> Las cifras en dinero deben calcularse con la calculadora oficial del proveedor (AWS Pricing Calculator) según la región y los tamaños elegidos. Lo importante para la arquitectura es que **el costo base es bajo y crece solo cuando hay carreras grandes**.
