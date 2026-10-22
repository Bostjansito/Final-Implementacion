# 3. Decisión 2 — División de servicios y responsabilidades

## 3.1 Mapa de capacidades → componentes

| Capacidad del enunciado | Componente que la implementa | ¿Servicio propio? | Razón |
|---|---|---|---|
| 1. Usuarios y autenticación | **IdP administrado** (login, contraseñas, MFA, tokens) + **módulo Usuarios del Core** (perfiles, roles, bloqueo) | No (módulo) | Las contraseñas no deben ser nuestro problema: lo delegamos a un IdP probado. Los perfiles tienen poco tráfico. |
| 2. Medianos | **Módulo Medianos del Core** | No (módulo) | CRUD de muy bajo tráfico y muy cacheable. Las estadísticas históricas se calculan en la analítica. |
| 3. Carreras | **Módulo Carreras del Core** | No (módulo) | Pocas escrituras (decenas por semana). Es el dueño de la máquina de estados de la carrera y publica sus eventos. |
| 6a. Resultados oficiales | **Módulo Carreras del Core** | No (módulo) | Registrar el resultado es una transición de estado de la carrera. |
| 4. Apuestas | **Servicio Apuestas — API** | **Sí** | Es el camino caliente: 10.000/s. Escala de forma independiente. |
| 6b. Cálculo y pago de premios | **Servicio Apuestas — Liquidador** (mismo código y BD, despliegue separado) | **Sí** (como *workers*) | Necesita leer las apuestas (los datos son de Apuestas). Es trabajo por lotes: escala a N *workers* al liquidar y a 0 el resto del tiempo. |
| 5. Billetera | **Servicio Billetera (Ledger)** | **Sí** | Es el componente más crítico (doble gasto). Tiene una BD aislada, red privada y una API mínima. |
| 7. Notificaciones | **Servicio Notificaciones** (*worker*) | **Sí** | Totalmente asíncrono. Su fallo no debe afectar las apuestas. Envía a través de proveedores administrados. |
| 8. Estadísticas y analítica | **Pipeline administrado**: Kafka Connect → data lake (S3/Parquet) → motor SQL (Athena/Redshift Serverless) | No (no se escribe código de servicio) | Tolera minutos o un día de retraso, así que no requiere un servicio en tiempo real. |
| 9. Auditoría y fraude | **Servicio Auditoría y Fraude** | **Sí** | Consume todos los eventos a su propio ritmo, escribe en almacenamiento inalterable, detecta patrones y expone una API de solo lectura al auditor. |
| Cuotas estimadas | Contadores en **Redis**, actualizados por un consumidor de `ApuestaRealizada` dentro del servicio Apuestas, servidos vía CDN | No | Son una proyección derivada de las apuestas. |

**Total: 5 desplegables propios** (Core, Apuestas‑API, Apuestas‑Liquidador, Billetera, Notificaciones) **+ 1 consumidor** (Auditoría y Fraude) y el resto es infraestructura administrada.

## 3.2 Responsabilidades por componente

### Core (monolito modular)
| Módulo | Responsabilidades | Lo que **no** hace |
|---|---|---|
| **Usuarios** | Perfil, datos personales (cifrados), asignación de roles (`APOSTADOR`, `OPERADOR`, `ADMIN`, `AUDITOR`), bloqueo y desbloqueo. Publica `UsuarioBloqueado`. | No guarda contraseñas (lo hace el IdP). No maneja saldo. |
| **Medianos** | Ficha de cada competidor (nombre, edad, peso, estado). Victorias, derrotas y velocidad promedio se actualizan al consumir `ResultadoPublicado`. | No calcula estadísticas premium (eso es analítica). |
| **Carreras** | Crear, programar, inscribir participantes, abrir apuestas, cerrar (programador a la hora exacta), registrar resultados oficiales, corregirlos y cancelar. Hace cumplir la máquina de estados `PROGRAMADA → ABIERTA → CERRADA_EN_CURSO → FINALIZADA → LIQUIDADA` (+ `CANCELADA`). | No valida apuestas ni paga premios. |
| **Admin** | Backoffice de operadores y administradores, con MFA obligatorio. Cada acción genera un evento de auditoría. | — |

### Servicio Apuestas
| Despliegue | Responsabilidades |
|---|---|
| **Apuestas‑API** | Recibir `POST /apuestas` con `Idempotency-Key`. Validar: usuario activo (token + caché de bloqueados), carrera `ABIERTA` y `ahora < cierre_at`, mediano inscrito, monto válido, sin duplicado. Pedir el débito a la Billetera (gRPC). Persistir la apuesta + outbox. Responder en menos de 1 s. Exponer las cuotas estimadas y "mis apuestas". |
| **Apuestas‑Liquidador** | Al recibir `ResultadoPublicado`: calcular la bolsa (total − 10 % de comisión), dividirla entre las apuestas ganadoras de forma proporcional, partir el trabajo en lotes (RabbitMQ), acreditar premios en la Billetera de forma idempotente, registrar cada cálculo para auditoría y marcar la carrera como liquidada. En caso de `CarreraCancelada`: devolver el 100 % de cada apuesta. |

### Servicio Billetera (Ledger)
- Dueño **único** del saldo de EIA Coins.
- Ledger de doble entrada, *append-only*: cada movimiento (`DEBITO_APUESTA`, `CREDITO_PREMIO`, `DEVOLUCION`, `AJUSTE`) es una fila inmutable. El saldo es una vista materializada que se actualiza en la misma transacción.
- Débito atómico que nunca deja saldo negativo, con clave de idempotencia única por operación.
- API **solo interna** (gRPC) para Apuestas y el Liquidador; consulta de saldo y movimientos para el usuario a través del Gateway (solo lectura).

### Servicio Notificaciones
- Consume eventos (`ApuestaAceptada`, `CarreraIniciada`, `CarreraFinalizada`, `PremioPagado`, `CarreraCancelada`, …).
- Aplica preferencias del usuario y plantillas, y envía por correo, *push* o app a través de proveedores administrados (SES, FCM/APNs).
- Reintentos con *backoff* y cola de mensajes muertos. Si se cae, **nadie más se entera**.

### Servicio Auditoría y Fraude
- Consume **todos** los eventos de negocio desde Kafka y los escribe en almacenamiento **WORM** (S3 con Object Lock, 5 años).
- Reglas de fraude en *streaming* (ventanas de tiempo): muchas cuentas por dispositivo, ráfagas de apuestas en los últimos segundos, montos atípicos. Publica `AlertaFraude`.
- API de **solo lectura** para el rol `AUDITOR`: trazabilidad de una apuesta, de un movimiento y la reconstrucción completa de la liquidación de una carrera.

## 3.3 ¿Por qué Apuestas y Billetera están separados (y Liquidación va junto a Apuestas)?

| Pregunta | Respuesta |
|---|---|
| ¿Por qué no unir Apuestas y Billetera en un servicio, ya que siempre escalan juntos? | La Billetera la usan **tres flujos** (apuestas, premios, devoluciones) y es el activo más sensible. Aislarla reduce su superficie de ataque y permite reglas de acceso y auditoría más estrictas. El costo es un salto de red de ~1–3 ms dentro de la red privada y coordinar dos escrituras (resuelto con idempotencia y reconciliación). |
| ¿Por qué el Liquidador vive con Apuestas y no es un servicio de "Premios" aparte? | Para calcular premios hay que leer **todas las apuestas de la carrera**. Si fuera otro servicio, necesitaría copiar o consultar por API un millón de apuestas. Al compartir código y BD (leyendo desde una réplica), evita ese acoplamiento sin mezclar cargas, porque se despliega por separado. |
| ¿Por qué Medianos no es un microservicio? | El enunciado lo deja abierto. Tiene poco tráfico, pocos cambios y sus lecturas se cachean en la CDN. Un servicio independiente solo agregaría costo. |
