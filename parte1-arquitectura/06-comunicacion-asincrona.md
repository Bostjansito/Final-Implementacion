# 6. Decisión 4 — Comunicación asíncrona (eventos)

## 6.1 Dos tipos de mensajes

| Tipo | Significado | Tiempo verbal | Broker | Ejemplo |
|---|---|---|---|---|
| **Evento** | "Esto **ya pasó**". Lo puede leer cualquiera interesado. | Pasado | **Kafka** | `ApuestaRealizada` |
| **Comando/tarea** | "**Haz** esto". Lo ejecuta un único *worker*. | Imperativo | **RabbitMQ** | `LiquidarLote` |

## 6.2 Sobre común (todos los eventos)

```json
{
  "event_id": "0b9e7c3e-5f1a-4c55-9a1d-1f0c2e7b9a11",
  "type": "ApuestaRealizada",
  "schema_version": 1,
  "occurred_at": "2026-11-04T18:59:58.412Z",
  "producer": "apuestas-api",
  "correlation_id": "op-7f3c…",
  "causation_id": null,
  "key": "usr-4821",
  "payload": { }
}
```
- `event_id` es único (UUID) y es la base de la **idempotencia** en los consumidores.
- `correlation_id` permite seguir una operación de punta a punta. Para las apuestas es la `Idempotency-Key`.
- `schema_version` permite evolucionar los contratos. Se usa un *Schema Registry* con compatibilidad *backward*.
- Los eventos **no** llevan datos personales sensibles (correo, documento). Llevan identificadores y cada consumidor busca lo que necesite.

## 6.3 Tabla de eventos (Kafka)

| Evento | Productor | Broker | Consumidores | Clave de partición |
|---|---|---|---|---|
| `UsuarioRegistrado` | Core – Usuarios | Kafka `usuarios.eventos` | Billetera (crea la cuenta con el saldo inicial), Notificaciones (bienvenida), Data lake | `usuario_id` |
| `UsuarioBloqueado` / `UsuarioDesbloqueado` | Core – Usuarios | Kafka `usuarios.eventos` | Apuestas (conjunto de bloqueados en Redis), Auditoría, Data lake | `usuario_id` |
| `CarreraProgramada` | Core – Carreras | Kafka `carreras.eventos` | Apuestas (precarga de caché), Notificaciones, Data lake | `carrera_id` |
| `CarreraAbierta` | Core – Carreras | Kafka `carreras.eventos` | Apuestas (activa la carrera en Redis), Notificaciones, Data lake | `carrera_id` |
| `CarreraCerrada` (inicio de la carrera; estado `CERRADA_EN_CURSO`) | Core – Carreras | Kafka `carreras.eventos` | Apuestas (marca la carrera como cerrada), Notificaciones ("comenzó la carrera"), Fraude (evalúa ráfagas previas al cierre), Data lake | `carrera_id` |
| `ResultadoPublicado` (estado `FINALIZADA`) | Core – Carreras | Kafka `carreras.eventos` | **Liquidador** (dispara la liquidación), Core – Medianos (victorias, derrotas), Notificaciones ("terminó la carrera"), Auditoría, Data lake | `carrera_id` |
| `ResultadoCorregido` | Core – Carreras | Kafka `carreras.eventos` | Liquidador (liquidación compensatoria), Core – Medianos, Notificaciones, Auditoría, Data lake | `carrera_id` |
| `CarreraCancelada` | Core – Carreras | Kafka `carreras.eventos` | Liquidador (devoluciones), Apuestas (rechaza nuevas apuestas), Notificaciones, Auditoría, Data lake | `carrera_id` |
| `CarreraLiquidada` | Core – Carreras (al recibir `LiquidacionCompletada`) | Kafka `carreras.eventos` | Notificaciones, Data lake | `carrera_id` |
| `ApuestaRealizada` (aceptada) | Apuestas‑API (outbox) | Kafka `apuestas.eventos` | Proyección de cuotas (Redis), Notificaciones ("apuesta aceptada"), Fraude, Auditoría, Data lake | `usuario_id` |
| `ApuestaRechazada` | Apuestas‑API | Kafka `apuestas.eventos` | Fraude (rechazos por cierre o saldo = señal de bots), Data lake | `usuario_id` |
| `MovimientoRegistrado` (débito, premio, devolución, ajuste) | Billetera (outbox) | Kafka `billetera.movimientos` | Auditoría, Notificaciones ("recibiste EIA Coins"), Fraude, Data lake | `usuario_id` |
| `LiquidacionCalculada` (equivale a `PremioCalculado` a nivel de carrera) | Liquidador | Kafka `liquidaciones.eventos` | Auditoría (reconstrucción), Data lake | `carrera_id` |
| `PremioPagado` / `DevolucionPagada` | Liquidador (outbox) | Kafka `premios.eventos` | Notificaciones ("¡ganaste!"), Auditoría, Data lake | `usuario_id` |
| `LiquidacionCompletada` | Liquidador | Kafka `liquidaciones.eventos` | Core – Carreras (pasa a `LIQUIDADA`), Auditoría, Data lake | `carrera_id` |
| `AlertaFraude` | Auditoría y Fraude | Kafka `fraude.alertas` | Core – Admin (panel de revisión y bloqueo), Data lake | `usuario_id` |
| `AccionAdministrativa` | Core – Admin (cada acción) | Kafka `admin.acciones` | Auditoría (WORM), Data lake | `actor_id` |

### Decisiones sobre la lista sugerida en el enunciado
| Evento del enunciado | Decisión |
|---|---|
| `CarreraIniciada` | Se fusiona con **`CarreraCerrada`**: en este negocio, las apuestas se cierran exactamente al iniciar la carrera, así que ambos hechos ocurren a la vez. |
| `CarreraFinalizada` | Se fusiona con **`ResultadoPublicado`**: una carrera finaliza oficialmente cuando se publica su resultado oficial. Dos eventos generarían estados intermedios sin utilidad. |
| `PremioCalculado` | Se emite **un evento por carrera** (`LiquidacionCalculada`, con bolsa, comisión y factor), no uno por apuesta. El detalle por apuesta ya viaja en `PremioPagado`. Esto evita duplicar un millón de eventos. |
| `ApuestaRealizada`, `ResultadoPublicado`, `PremioPagado`, `CarreraCancelada` | Se mantienen. |

## 6.4 Información mínima por evento (`payload`)

| Evento | Payload mínimo |
|---|---|
| `UsuarioRegistrado` | `usuario_id`, `rol`, `registrado_at` |
| `UsuarioBloqueado` | `usuario_id`, `motivo`, `bloqueado_por`, `at` |
| `CarreraAbierta` | `carrera_id`, `abre_at`, `cierre_at`, `pista`, `distancia`, `participantes[]` (`mediano_id`) |
| `CarreraCerrada` | `carrera_id`, `cerrada_at` |
| `ResultadoPublicado` | `carrera_id`, `version_resultado`, `ganador_mediano_id`, `posiciones[]`, `publicado_por`, `aprobado_por`, `at` |
| `ResultadoCorregido` | Lo mismo que `ResultadoPublicado`, más `version_anterior`, `motivo` |
| `CarreraCancelada` | `carrera_id`, `motivo`, `cancelada_por`, `at` |
| `ApuestaRealizada` | `apuesta_id`, `operacion_id` (idempotency key), `usuario_id`, `carrera_id`, `mediano_id`, `monto`, `recibida_at`, `dispositivo_hash` |
| `ApuestaRechazada` | `operacion_id`, `usuario_id`, `carrera_id`, `motivo` (`CIERRE`, `SALDO`, `BLOQUEADO`, …), `recibida_at`, `dispositivo_hash` |
| `MovimientoRegistrado` | `movimiento_id`, `operacion_key`, `usuario_id`, `tipo`, `monto`, `saldo_resultante`, `referencia` (apuesta, liquidación), `at` |
| `LiquidacionCalculada` | `liquidacion_id`, `carrera_id`, `version_resultado`, `bolsa_total`, `comision` (10 %), `bolsa_neta`, `total_apostado_ganador`, `factor`, `n_apuestas_ganadoras`, `hash_detalle` |
| `PremioPagado` | `liquidacion_id`, `apuesta_id`, `usuario_id`, `monto_apostado`, `factor`, `premio`, `movimiento_id` |
| `DevolucionPagada` | `carrera_id`, `apuesta_id`, `usuario_id`, `monto`, `movimiento_id` |
| `LiquidacionCompletada` | `liquidacion_id`, `carrera_id`, `total_pagado`, `n_pagos`, `residuo_redondeo`, `duracion_s` |
| `AlertaFraude` | `alerta_id`, `regla`, `usuarios[]`, `carrera_id`, `evidencia`, `severidad` |
| `AccionAdministrativa` | `accion_id`, `actor_id`, `rol`, `accion`, `recurso`, `antes`, `despues`, `ip`, `at` |

## 6.5 Mensajes de trabajo (RabbitMQ)

| Mensaje | Productor | Cola | Consumidor | Routing key | Contenido mínimo |
|---|---|---|---|---|---|
| `LiquidarLote` | Liquidador (coordinador) | `liquidacion.premios` | Liquidador (*workers*) | `premios` | `liquidacion_id`, `carrera_id`, `lote_n`, `desde_apuesta_id`, `hasta_apuesta_id`, `factor` |
| `DevolverLote` | Liquidador (coordinador) | `liquidacion.devoluciones` | Liquidador (*workers*) | `devoluciones` | `carrera_id`, `lote_n`, rango de apuestas |
| `EnviarNotificacion` | Notificaciones (traductor de eventos) | `notif.email`, `notif.push`, `notif.app` | Notificaciones (*senders* por canal) | `email` / `push` / `app` | `notificacion_id`, `usuario_id`, `plantilla`, `datos`, `expira_at` |
