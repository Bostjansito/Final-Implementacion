# Guía de demostración

## Cuentas de prueba

Las contraseñas se **generan** la primera vez que se levanta el sistema y **no están en el repositorio**:

```bash
cat .secrets/cuentas-demo.txt
```

| Cuenta | Rol | Perfil |
|---|---|---|
| `admin@credimarket.test` | ADMIN | Catálogo, clientes, inventario, todos los préstamos y modelo. |
| `ana.bajo@credimarket.test` | CLIENTE | Riesgo **bajo** (probabilidad ≈ 0,05) → aprobación. |
| `bruno.alto@credimarket.test` | CLIENTE | Riesgo **alto** (≈ 0,97) → rechazo por riesgo. |
| `carla.otra@credimarket.test` | CLIENTE | Riesgo bajo; sirve para probar acceso a préstamos ajenos y concurrencia. |

Catálogo inicial: *Portátil Ultra 14* (**1 unidad**, el "último computador"), *Tablet Air 11* (**0 unidades**) y otros 4 productos con existencias.

## Recorrido desde el navegador (http://localhost:8080)

| # | Demostración | Pasos | Resultado esperado |
|---|---|---|---|
| 1 | **Préstamo aprobado** | Ana → Catálogo → *Celular Lite* → cantidad 1, plazo 12 → Solicitar. | Confirmación con identificador y "decisión pendiente". En *Mis solicitudes* pasa sola de *Pendiente de inventario* a **Aprobada** (polling cada 3 s). |
| 2 | **Entrega** | Admin → Inventario → Reservas ACTIVA → *Confirmar entrega*. | La reserva pasa a CONFIRMADA y el préstamo de Ana a **Entregada** (COMPLETADA). Movimiento `SALIDA`. |
| 3 | **Rechazo por riesgo** | Bruno → solicita cualquier producto. | **Rechazada** con motivo `RIESGO_ALTO`, probabilidad, umbral y versión del modelo. No aparece ninguna reserva en Inventario. |
| 4 | **Falta de inventario** | Ana → *Tablet Air 11*. | Pendiente → **Cancelada sin stock**. Existencias siguen en 0. |
| 5 | **Cancelación** | Ana solicita otro producto y, ya Aprobada, abre el detalle → *Cancelar solicitud*. | *Cancelando* → **Cancelada** con "reserva liberada". En Inventario la reserva queda LIBERADA y las unidades vuelven. |
| 6 | **Actualización de precio** | Admin → Productos → *Consultar (caché)* (`X-Cache: HIT`) → *Editar* precio → *Consultar (caché)*. | Tras editar: `MISS`, precio nuevo y versión +1. Una nueva solicitud usa ese precio y esa versión (detalle → "Cotización usada"). |
| 7 | **Importación de clientes** | Admin → Clientes → seleccionar `data/clientes_demo.csv` → Importar. Repetir. | 1ª: 60 insertados, 4 rechazados con su fila y motivo. 2ª: **0 insertados**, 60 sin cambios. |
| 8 | **Versión del modelo** | Admin → Modelo. | Versión activa, run ID, umbral, métricas, enlace a MLflow y monitoreo (PSI). |
| 9 | **Promoción / rollback** | Terminal: `docker compose --profile ml run --rm ml-trainer python promover.py --version v2` → Admin → Modelo → *Recargar modelo*. Luego `--rollback` y recargar. | La versión activa cambia a v2 y vuelve a v1. Las nuevas solicitudes registran la versión usada. |
| 10 | **Último computador** | Ana y Carla (dos navegadores o ventanas privadas) solicitan *Portátil Ultra 14* casi a la vez. | Una **Aprobada** y otra **Cancelada sin stock**. Nunca hay existencias negativas. |
| 11 | **Errores y sesión** | a) Enviar un formulario incompleto. b) `docker compose stop prestamos` e intentar solicitar. c) Esperar a que venza el token (`TOKEN_MINUTOS=1` para demostrarlo rápido). | a) Validación del formulario. b) "El servicio Préstamos no está disponible…" y botón **Reintentar (misma solicitud)**, que reutiliza la clave. c) Aviso "Tu sesión expiró" y regreso al login. |
| 12 | **Responsive** | Reducir la ventana o usar el modo móvil del navegador. | Menú colapsable ☰, formularios en una columna y tablas con scroll horizontal. |

## Pruebas automáticas (casos de fallo, concurrencia, caché y reentrega)

```bash
python scripts/pruebas_aceptacion.py          # 16 casos; tarda ~4 min porque detiene y reinicia contenedores
python scripts/pruebas_aceptacion.py --rapido # sin los casos que detienen contenedores
python scripts/medir_redis.py                 # mediciones p50/p95/tasa de aciertos
python scripts/simular_drift.py               # alerta de drift en /modelo/monitoreo
sh scripts/pruebas_unitarias.sh               # pruebas unitarias dentro de las imágenes
```
Requieren Python 3.10+ en el equipo (solo librería estándar). Cada ejecución deja un resumen en `scripts/resultados/`.

| Caso del enunciado | Prueba automática |
|---|---|
| 1 Riesgo favorable con existencias | `1` |
| 2 Solicitud rechazada | `2` |
| 3 Sin existencias | `3` |
| 4 Dos solicitudes por la última unidad | `4` |
| 5 Misma petición y mismo evento repetidos | `5` |
| 6 Caída del consumidor o del broker | `6` (detiene `inventario-worker` y luego `rabbitmq`) |
| 7 Cancelación y evento tardío | `7` |
| 8 Redis vacío, expirado o caído | `8` |
| 9 Precio modificado | `9` |
| 10 Modelo exportado vs. API | `10` (200 solicitudes nuevas, diferencia < 1e-5) |
| 11 Promoción y rollback | `11` |
| 12 Importar el mismo CSV dos veces | `12` |
| 13 Cliente accede a préstamos ajenos | `13` |
| 14–15 Flujo y estado pendiente desde el frontend | Recorrido 1–10 de esta guía |
| 16 Formulario inválido, sesión vencida o API caída | `16` + recorrido 11 |
| Vencimiento de reservas | `VEN` |
| Dead letter | `DLQ` |

## Herramientas de observación

* **RabbitMQ:** http://localhost:15672 (usuario `credimarket`; contraseña en `.secrets/cuentas-demo.txt`). Pestaña *Queues*: `inventario.comandos`, `prestamos.eventos-inventario`, `*.retry`, `*.dlq`.
* **MLflow:** http://localhost:5000 → experimento `credimarket-riesgo-incumplimiento` (comparar ejecuciones) y *Models* → `credimarket-riesgo` (alias `exportado-v1`, `exportado-v2`, `activo`).
* **Logs:** `docker compose logs -f prestamos-worker inventario-worker` muestra cada mensaje con su resultado (`aprobada`, `duplicado-ignorado`, `tardio-ignorado…`).
