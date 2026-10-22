# Parte 1 — Arquitectura: La Gran Liga de Apuestas de Medianos EIA

> Documento de diseño. Según el enunciado, **no se implementa**; se entregan las decisiones, los diagramas y los ADR.
> Los diagramas están en Mermaid (se ven en GitHub y en VS Code con la extensión *Markdown Preview Mermaid Support*).

## Resumen de la arquitectura

**Híbrida:** un *monolito modular* (Core: usuarios, medianos, carreras, resultados, admin) + 4 componentes independientes donde la carga o la criticidad lo exigen (**Apuestas** API + Liquidador, **Billetera**, **Notificaciones**, **Auditoría y Fraude**). Usa **Kafka** como log de eventos compartido y **RabbitMQ** para repartir trabajo (lotes de liquidación y envíos de notificaciones).

## Índice (mapeado a los 16 puntos del entregable)

| # | Sección del entregable | Archivo |
|---|---|---|
| — | Análisis del problema y capacidad | [01-analisis-del-problema.md](01-analisis-del-problema.md) |
| 1 | Arquitectura seleccionada y alternativas descartadas (Decisión 1) | [02-estilo-arquitectonico.md](02-estilo-arquitectonico.md) |
| 2 | Servicios/módulos y responsabilidades (Decisión 2) | [03-servicios.md](03-servicios.md) |
| 3 | Diagrama general de arquitectura | [04-diagrama-general.md](04-diagrama-general.md) |
| 4 | Diagrama de secuencia de una apuesta | [08-diagrama-secuencia.md](08-diagrama-secuencia.md) |
| 5 | Comunicaciones síncronas (Decisión 3) | [05-comunicacion-sincrona.md](05-comunicacion-sincrona.md) |
| 6 | Eventos y comunicación asíncrona (Decisión 4) | [06-comunicacion-asincrona.md](06-comunicacion-asincrona.md) |
| 7 | Diseño de Kafka y RabbitMQ (Decisión 5) | [07-kafka-y-rabbitmq.md](07-kafka-y-rabbitmq.md) |
| 8 | Estrategia de idempotencia (Decisión 6) | [09-idempotencia.md](09-idempotencia.md) |
| 9 | Datos y consistencia (Decisión 9) | [10-datos-y-consistencia.md](10-datos-y-consistencia.md) |
| 10 | Manejo de cargas masivas (Decisión 7) | [11-cargas-masivas.md](11-cargas-masivas.md) |
| 11 | Seguridad (público vs. privado) | [13-seguridad.md](13-seguridad.md) |
| 12 | Costos | [14-costos.md](14-costos.md) |
| 13 | Manejo de fallos (Decisión 8) | [12-manejo-de-fallos.md](12-manejo-de-fallos.md) |
| 14 | ADR de las 3 decisiones más importantes | [15-adrs.md](15-adrs.md) |
| 15–16 | Pregunta final y conclusiones | [16-pregunta-final-y-conclusiones.md](16-pregunta-final-y-conclusiones.md) |
| — | Guion de 20 diapositivas + preparación del cambio en vivo | [17-guion-presentacion.md](17-guion-presentacion.md) |

## Supuestos propios (además de los del enunciado)
- Nube de referencia: AWS (cada servicio tiene un equivalente en GCP o Azure).
- Las cuotas estimadas se refrescan cada 1–3 s y se sirven desde la CDN.
- Saldo inicial de EIA Coins al registrarse (lo acredita la Billetera con el evento `UsuarioRegistrado`).
- Si nadie apostó al ganador, se devuelve el 100 %. Redondeo hacia abajo a 2 decimales; el residuo queda en la cuenta de la casa.
- Los resultados pasan por una ventana de 3–5 min como "provisionales" antes de ser oficiales.
