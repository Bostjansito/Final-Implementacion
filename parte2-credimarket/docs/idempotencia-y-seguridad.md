# Idempotencia, consistencia e importación masiva

## Idempotencia HTTP (`POST /prestamos`)

1. El frontend genera una `Idempotency-Key` (UUID) por solicitud y la **conserva** en `sessionStorage` hasta obtener respuesta definitiva. El botón se deshabilita mientras se envía, y "Reintentar" reutiliza la clave.
2. Préstamos inserta la fila `EVALUANDO` con **`UNIQUE(usuario_id, idempotency_key)`** y guarda el SHA-256 del cuerpo (`request_hash`).
3. Si la clave ya existe:
   * **mismo contenido** → devuelve la misma solicitud (`200`, `Idempotent-Replay: true`), o reanuda la evaluación si quedó en `EVALUANDO`;
   * **contenido distinto** → `409 Conflict`.
4. Peticiones **concurrentes** con la misma clave: solo una gana el `INSERT` y la base de datos serializa el resto. Además, el paso final bloquea la fila (`SELECT … FOR UPDATE`) y solo aplica la evaluación si el estado sigue siendo `EVALUANDO`.

Demostración: prueba 5 (5 peticiones simultáneas con la misma clave → 1 préstamo; misma clave y cantidad distinta → 409).

## Idempotencia de mensajes

* Cada consumidor inserta `event_id` en `mensajes_procesados` **en la misma transacción** que el efecto de negocio, y hace el *ack* después del *commit*. Una reentrega encuentra el `event_id` y se descarta (`duplicado-ignorado`).
* Defensa adicional de dominio: `UNIQUE(prestamo_id)` en `reservas`. Un comando repetido con **otro** `event_id` no reserva de nuevo: reenvía el resultado conocido.
* Todo es **durable en PostgreSQL**; no depende de Redis.

## Publicación confiable (*transactional outbox*)

El cambio de estado y el mensaje se escriben en la **misma transacción local** (tabla `outbox`). El *relay* del *worker*:
1. lee pendientes con `FOR UPDATE SKIP LOCKED`;
2. publica con *publisher confirms* y `mandatory=True`;
3. marca `publicado_at`.

Si se cae entre 2 y 3, el mensaje se publica otra vez, y los consumidores son idempotentes. No se usan transacciones distribuidas.

## Reserva atómica sin stock negativo

```sql
UPDATE existencias SET disponible = disponible - :q, reservado = reservado + :q
WHERE producto_id = :p AND disponible >= :q;   -- 0 filas = insuficiente
```
Más `CHECK (disponible >= 0)` y `CHECK (reservado >= 0)` como última defensa. Demostración: prueba 4 (dos clientes por la última unidad: exactamente una `APROBADA`, la otra `CANCELADA_SIN_STOCK`, existencias 0/1).

## Importación CSV de clientes

* **Clave externa única:** `codigo_externo`. Se acepta `cliente_id` del histórico como alias, así que se puede importar directamente `data/solicitudes_nuevas.csv`.
* **Política:**
  * nuevo → inserta;
  * igual → `sin_cambios`;
  * distinto → actualiza (gana el último archivo);
  * inválido → se rechaza la fila con número de fila y motivo, y el resto se procesa;
  * código repetido dentro del archivo → se rechaza la segunda aparición.
* `INSERT … ON CONFLICT (codigo_externo) DO UPDATE` → dos importaciones simultáneas tampoco duplican.
* Respuesta: `filas, insertados, actualizados, sin_cambios, rechazados, errores[]`. Se guarda un historial con el SHA-256 del archivo.
* Demostración: prueba 12 con `data/clientes_demo.csv` (60 válidas + 4 inválidas). La 2ª importación da 0 insertados, 0 actualizados y 60 sin cambios.

## Seguridad

Ver la sección 4 de [arquitectura.md](arquitectura.md). Resumen:
* JWT RS256 emitido solo por Clientes.
* Roles `CLIENTE` y `ADMIN` validados en cada backend.
* Un cliente solo accede a lo suyo (prueba 13).
* Endpoints internos con token de servicio.
* Secretos generados fuera del repositorio.
* Contraseñas con scrypt.
