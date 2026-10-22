# Redis: diseño de la caché e informe de desempeño

## 1. Diseño (cache-aside en Productos)

| Aspecto | Decisión |
|---|---|
| Claves | `productos:v1:{producto_id}` (detalle) y `productos:v1:lista:activos` (catálogo). El prefijo `v1` permite cambiar el formato sin chocar con datos viejos. |
| Lectura | 1) `GET` en Redis → **HIT**. 2) Si no está → **MISS**: se lee PostgreSQL y se guarda con TTL. 3) Si Redis falla → **BYPASS**: se responde desde PostgreSQL. |
| TTL | Detalle **300 s** (`CACHE_TTL_SEGUNDOS`). Lista **60 s** (`CACHE_TTL_LISTA_SEGUNDOS`). |
| Invalidación | En `PUT`, `desactivar` y `activar` se borra la clave del producto **y** la de la lista, **después** del *commit* en PostgreSQL. Si se invalidara antes, una lectura concurrente podría volver a cachear el valor viejo. |
| Fallos | Toda operación de Redis tiene un **límite total de 250 ms** (incluye resolver DNS, que el `socket_timeout` no cubre). Tras un error, Redis se omite durante 5 s (*circuit breaker*) para no pagar el timeout en cada petición. Redis no participa en `/ready`. |
| Memoria | `maxmemory 64mb`, política `allkeys-lru`, sin persistencia: la caché es desechable. |
| Visibilidad | Cabecera `X-Cache` y `GET /cache/estadisticas` (hits, misses, tasa de aciertos, errores, omitidas, invalidaciones, TTL restante). |

### ¿Cuándo puede estar desactualizado un dato?
1. **Invalidación fallida:** si Redis estaba caído justo al invalidar, la clave vieja puede sobrevivir **hasta su TTL** (máximo 300 s).
2. **Carrera lectura/escritura:** una lectura que empezó antes del *commit* puede guardar el valor anterior después de la invalidación. Queda acotado por el TTL.
3. **Varias réplicas** de Productos comparten Redis, así que la invalidación es global.

**Por eso el precio del préstamo NUNCA sale de la caché:** Préstamos usa `GET /internal/productos/{id}/cotizacion`, que lee PostgreSQL y devuelve `version`. El préstamo guarda `precio_unitario`, `version_producto` y `cotizado_at` (prueba de aceptación 9).

### Límites de Redis respetados
* Redis no reemplaza ninguna base de datos.
* La deduplicación de solicitudes (`UNIQUE(usuario_id, idempotency_key)`) y de mensajes (`mensajes_procesados`) vive en **PostgreSQL**: sobrevive a la caída o al borrado de Redis.

## 2. Evidencia funcional (prueba de aceptación 8 y 9)

| Demostración | Cómo se ve |
|---|---|
| *Cache miss* → *hit* | Primera consulta `X-Cache: MISS`, segunda `X-Cache: HIT`. |
| Expiración | Se fuerza `EXPIRE` de 1 s: la siguiente consulta es `MISS`. Con el TTL normal se observa `ttl_restante_s` en `/cache/estadisticas?producto_id=`. |
| Invalidación tras cambiar un precio | `PUT` del precio → la siguiente consulta es `MISS` con el precio nuevo y `version` incrementada. |
| Caída de Redis | `docker compose stop redis` → respuestas `200` con `X-Cache: BYPASS` desde PostgreSQL (~260 ms la primera, por el límite de 250 ms; luego sin espera gracias al *circuit breaker*). |
| Desde el frontend | Admin → Productos → “Consultar (caché)” muestra `X-Cache`, y el panel muestra las estadísticas. |

## 3. Mediciones de carga (`python scripts/medir_redis.py`)

Entorno: Docker Desktop en Windows 11, 12 CPU, todos los contenedores en la misma máquina. Endpoint `GET /productos/{id}`, uvicorn con 1 proceso.

| Escenario | Peticiones | p50 (ms) | p95 (ms) | Peticiones/s | Tasa de aciertos |
|---|---|---|---|---|---|
| A. Sin caché: MISS → PostgreSQL (1 hilo) | 500 | 18,0 | 33,8 | — ¹ | 0 % |
| B. Con caché: HIT (1 hilo) | 500 | 15,9 | 31,6 | 58 | 100 % |
| C. Carga mixta, 6 productos, caché vacía al inicio (8 hilos) | 2000 | **33,3** | **51,2** | **230** | 99,6 % |
| D. Redis caído: BYPASS → PostgreSQL (8 hilos) | 2000 | 57,8 | 86,3 | 129 | 0 % |

¹ En A cada petición va precedida de un `DELETE /cache`, por lo que su rendimiento no es comparable.

**Recursos** (`docker stats`, en reposo tras la carga): Redis **3,3 MiB** de RAM (1,2 MB de datos), Productos ~66 MiB, PostgreSQL ~110 MiB.

### Análisis
* **Con concurrencia (C vs D)** la caché reduce la latencia p50 un **42 %** (57,8 → 33,3 ms) y la p95 un **41 %**, y casi **duplica el rendimiento** (129 → 230 peticiones/s). El motivo es que evita abrir y usar conexiones del *pool* de PostgreSQL por cada lectura.
* **Sin concurrencia (A vs B)** la mejora es pequeña (18,0 → 15,9 ms). Leer una fila por clave primaria en PostgreSQL local ya es muy rápido, y la latencia está dominada por HTTP y la serialización. La caché aporta sobre todo **capacidad** bajo carga y **aislamiento** de la base de datos, más que latencia individual.
* **Tasa de aciertos** del 99,6 % en carga mixta: solo fallan las primeras lecturas de cada producto (*cold start*). En las estadísticas acumuladas del servicio la tasa baja (~86 %) porque incluye las pruebas que vacían la caché a propósito.
* **Redis caído (D):** el servicio sigue respondiendo el 100 % de las peticiones sin errores. Pierde rendimiento pero no disponibilidad.
* **Limitación:** las mediciones son locales y de un solo nodo; en producción la red entre servicios agregaría latencia a ambos caminos.
