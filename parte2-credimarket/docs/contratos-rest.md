# Contratos REST

Cada servicio publica su documentación OpenAPI interactiva en `/docs` (p. ej. http://localhost:8003/docs) y el esquema en `/openapi.json`.
Autenticación: `Authorization: Bearer <JWT>`. Roles: **P** = público, **C** = cliente (solo lo propio), **A** = administrador, **S** = token de servicio.

## Clientes (:8002)
| Método y ruta | Rol | Descripción |
|---|---|---|
| `POST /auth/registro` | P | Crea cliente y usuario (`CLIENTE`) y devuelve un token. 409 si el correo existe. |
| `POST /auth/login` | P | `{email, password}` → `{access_token, expira_en, usuario}`. 401 si las credenciales no son válidas. |
| `GET /auth/me` | C/A | Datos del token. |
| `GET /clientes?buscar=&pagina=&tamano=` | A | Listado paginado. |
| `GET /clientes/{id}` | C (propio) / A | Ficha completa. 403 si es de otro cliente. |
| `PUT /clientes/{id}` | C (propio) / A | Nombre, teléfono, datos financieros y laborales. `activo` solo para admin. |
| `POST /clientes/importar` (multipart `archivo`) | A | Importación CSV → `{filas, insertados, actualizados, sin_cambios, rechazados, errores[{fila, codigo_externo, error}]}` |
| `GET /clientes/importaciones` | A | Historial de importaciones (archivo, SHA-256, conteos). |
| `GET /internal/clientes/{id}` | S/A | Perfil para la evaluación de riesgo. |

## Productos (:8001)
| Método y ruta | Rol | Descripción |
|---|---|---|
| `GET /productos?categoria=&incluir_inactivos=` | P (inactivos: A) | Listado (lista de activos cacheada 60 s). |
| `GET /productos/{id}` | P | Detalle **cache-aside**. Cabecera `X-Cache: HIT \| MISS \| BYPASS`. |
| `POST /productos` | A | Crea un producto (versión 1). 409 si el SKU existe. |
| `PUT /productos/{id}` | A | Cambios parciales. Incrementa `version`; acepta `version_esperada` (409 si cambió). Invalida la caché tras el *commit*. |
| `POST /productos/{id}/desactivar` · `/activar` | A | Cambia el estado e invalida la caché. |
| `GET /productos/{id}/historial-precios` | A | Precios por versión. |
| `GET /internal/productos/{id}/cotizacion` | S/A | `{precio, version, activo, cotizado_at}` leído **de PostgreSQL** (nunca de la caché). |
| `GET /cache/estadisticas?producto_id=` · `DELETE /cache` | A | Aciertos, fallos, errores, TTL restante · vaciar la caché (demo). |

## Préstamos (:8003)
| Método y ruta | Rol | Descripción |
|---|---|---|
| `POST /prestamos` + `Idempotency-Key` | C | `{producto_id, cantidad (1-5), plazo_meses (6,12,18,24,36)}`. **202** `PENDIENTE_INVENTARIO`, **201** `RECHAZADA`, **200** repetición idempotente (`Idempotent-Replay: true`), **409** misma clave con otro contenido, **400** sin clave, **422** campos inválidos o extra (p. ej. `precio`), **503** dependencia caída (reintentar con la misma clave). Cabecera `Location: /prestamos/{id}`. |
| `GET /prestamos?estado=` | C (propios) / A (todos) | Listado. |
| `GET /prestamos/{id}` | C (propio) / A | Estado, cotización usada, monto, evaluación (probabilidad, decisión, umbral, versión), motivo y reserva. 403 si es ajeno. |
| `GET /prestamos/{id}/historial` | C (propio) / A | Transiciones de estado. |
| `POST /prestamos/{id}/cancelar` | C (propio) / A | `PENDIENTE_INVENTARIO` o `APROBADA` → `CANCELANDO` (+ `LiberacionSolicitada`). Idempotente. 409 en estados finales. |
| `POST /riesgo/predict` | A/S | Prueba el pipeline con las 10 características. Valida tipos, categorías, faltantes y rangos. **No** crea préstamos ni reserva. |
| `GET /modelo/info` | P | Versión, run ID, variables, umbral, métricas de prueba, dependencias y hash. |
| `POST /modelo/recargar` | A | Vuelve a leer `registry/active.json` (tras promoción o rollback). |
| `GET /modelo/monitoreo?ultimas=` | A | Volumen, tasa de riesgo alto y **PSI** por variable frente al entrenamiento. |
| `GET /health` · `GET /ready` | P | Proceso vivo · modelo cargado, BD, Clientes y Productos disponibles (503 si no). |

## Inventario (:8004)
| Método y ruta | Rol | Descripción |
|---|---|---|
| `GET /inventario/existencias` | A | Disponible y reservado por producto. |
| `GET /inventario/existencias/{producto_id}` | P | Disponibilidad informativa. |
| `POST /inventario/entradas` | A | `{producto_id, cantidad, nota}`. Valida por API que el producto exista. |
| `GET /inventario/reservas?estado=&prestamo_id=` | A | Reservas (`ACTIVA`, `CONFIRMADA`, `LIBERADA`, `VENCIDA`, `RECHAZADA`). |
| `GET /inventario/movimientos?producto_id=` | A | `ENTRADA`, `RESERVA`, `LIBERACION`, `SALIDA`, `VENCIMIENTO`. |
| `POST /inventario/reservas/{id}/confirmar-salida` | A | Entrega simulada → `SalidaConfirmada`. 409 si la reserva no está activa o venció. |

Todos los servicios exponen `GET /health` y `GET /ready`.
