# 1. Análisis del problema

Antes de elegir tecnologías, identificamos **qué es realmente difícil** en la plataforma. La mayoría de capacidades (medianos, perfiles, programación de carreras) son CRUD de bajo tráfico. La dificultad está concentrada en muy pocos puntos.

## 1.1 Impulsores arquitectónicos (lo que manda en el diseño)

| # | Impulsor | Fuente en el enunciado | Consecuencia en el diseño |
|---|---|---|---|
| D1 | **Pico de 10.000 apuestas/s durante 30 s** | Supuestos de diseño | El flujo de apuestas debe escalar horizontalmente y por separado del resto. |
| D2 | **Respuesta < 1 s** sobre si la apuesta fue aceptada | Supuestos de diseño | La validación de saldo y el descuento son **síncronos**: no podemos responder "recibida, ya veremos". |
| D3 | **Cero pérdida** de apuestas aceptadas y movimientos de billetera | Supuestos de diseño | Escritura durable antes de responder + *transactional outbox* para eventos. |
| D4 | **Nunca gastar dos veces** los mismos EIA Coins | Billetera | Ledger con consistencia fuerte, operaciones atómicas e idempotentes. |
| D5 | **Liquidar hasta 1.000.000 de apuestas en < 15 min** | Resultados y premios | Procesamiento por lotes en paralelo con *workers*, no una petición HTTP. |
| D6 | **Muchos consumidores** de los mismos hechos (analítica, fraude, auditoría, notificaciones) | Capacidades 7, 8, 9 | Un log de eventos compartido (Kafka) en lugar de llamadas punto a punto. |
| D7 | **Auditoría inalterable 5 años** y reconstrucción de premios | Capacidad 9 | Almacenamiento WORM (*write once, read many*) y eventos reproducibles. |
| D8 | **Costo**: "no quiero una infraestructura de Netflix" | Costos | Pocos servicios desplegables, servicios administrados y escalado a cero donde se pueda. |
| D9 | **Tráfico muy variable** (500 → 100.000 usuarios) | Cargas masivas | Autoescalado y caché en el borde (CDN) para las lecturas masivas. |

## 1.2 Atributos de calidad priorizados

1. **Consistencia/Integridad** de saldos y apuestas (no negociable).
2. **Disponibilidad y latencia** del flujo de apuesta en los picos.
3. **Seguridad** (dinero virtual, roles, operaciones administrativas).
4. **Auditabilidad**.
5. **Costo y mantenibilidad**.
6. Frescura de la analítica (la menos exigente: minutos o un día).

> Cuando dos atributos chocan, gana el de arriba. Ejemplo: si la billetera está caída, **no se aceptan apuestas** (gana la consistencia sobre la disponibilidad).

## 1.3 Estimación de capacidad (cálculos de servilleta)

| Magnitud | Cálculo | Resultado |
|---|---|---|
| Apuestas en la ventana pico | 10.000/s × 30 s | **300.000 apuestas** en 30 s |
| Volumen del evento `ApuestaRealizada` | 10.000/s × ~1 KB | **~10 MB/s** hacia Kafka en el pico (holgado para un clúster pequeño) |
| Escrituras en la billetera en el pico | 1 débito por apuesta | **~10.000 transacciones/s** → es el **cuello de botella principal** |
| Lecturas de cuotas en vivo (final de la Copa) | 100.000 usuarios refrescando cada 3 s | **~33.000 lecturas/s** → se sirven desde la **CDN** con TTL de 1–2 s; el origen recibe ~1 petición/s por carrera |
| Liquidación de una carrera masiva | 1.000.000 apuestas / 900 s | **~1.100 créditos/s** (o ~3 llamadas/s en lotes de 500) |
| Eventos por día | Apuestas + movimientos + cambios de estado | **Millones de registros/día** |
| Auditoría a 5 años | ~5 GB/día sin comprimir → Parquet comprimido ~5–10× | **~0,2–0,4 TB/año** en almacenamiento de objetos (barato) |

**Conclusión del análisis:** el problema **no** pide 20 microservicios. Pide aislar y escalar **un camino caliente** (apostar → descontar saldo), procesar en paralelo **un trabajo pesado y puntual** (liquidación), y distribuir **eventos a varios consumidores**. Todo lo demás puede vivir junto.

## 1.4 Supuestos adicionales que fijamos

| Supuesto | Justificación |
|---|---|
| Las transmisiones de video en vivo usan un servicio administrado de *streaming*/CDN y quedan fuera del alcance de la arquitectura de negocio. | No es una capacidad diferenciadora; construirla sería caro. |
| Las cuotas estimadas se actualizan cada 1–3 s (no por cada apuesta). | El enunciado dice "aproximada"; esto permite cachearlas en la CDN. |
| El cierre de apuestas usa el reloj del servidor de Apuestas (sincronizado por NTP), comparado contra `cierre_at` de la carrera. | Regla de negocio: "según el reloj del servidor". |
| Nube de referencia: AWS, solo para dar nombres concretos. Cada servicio tiene un equivalente en GCP o Azure. | Permite estimar costos; la arquitectura no depende del proveedor. |
