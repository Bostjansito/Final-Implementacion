# CrediMarket — microservicios, mensajería, Redis y MLOps

Plataforma de venta a crédito de productos tecnológicos (datos ficticios). Tiene:
* **4 microservicios** (Productos, Clientes, Préstamos, Inventario);
* un **frontend web**;
* un **modelo de riesgo** con ciclo MLOps completo en **MLflow**;
* **RabbitMQ** en el flujo real de reservas y caché **Redis** *cache-aside*.

```bash
docker compose up -d --build      # desde un clon limpio; luego abrir http://localhost:8080
cat .secrets/cuentas-demo.txt     # cuentas de prueba (generadas, no versionadas)
```

## Integrantes

| Integrante | Responsabilidades principales |
|---|---|
| Pedro Rueda | Productos + Inventario + Redis (caché, invalidación, mediciones) |
| Samuel Ramírez | Clientes + seguridad (JWT, roles, importación CSV) + frontend |
| Sebastian Pérez | Préstamos + RabbitMQ (outbox, consumidores, máquina de estados) + modelo y MLOps (MLflow, exportación, promoción) |

> El historial de commits debe mostrar contribuciones de los tres integrantes.

## Arquitectura en una imagen

```
Navegador ──► Frontend (nginx :8080) ──/api/*──► Productos :8001 ──► Redis + productos_db
                                              ├► Clientes  :8002 ──► clientes_db (emite JWT)
                                              ├► Préstamos :8003 ──► prestamos_db + modelo (ml/registry)
                                              │      │ REST: perfil del cliente y cotización vigente
                                              │      └─ outbox ──► RabbitMQ ──► Inventario worker
                                              └► Inventario :8004 ─► inventario_db ◄─┘ (eventos de vuelta)
```

## Documentación

| Tema | Documento |
|---|---|
| Arquitectura, secuencia, seguridad, puertos | [docs/arquitectura.md](docs/arquitectura.md) |
| Máquina de estados, tiempos de espera, eventos tardíos | [docs/maquina-estados.md](docs/maquina-estados.md) |
| Decisión RabbitMQ vs Kafka (6 preguntas) y configuración | [docs/decision-broker.md](docs/decision-broker.md) |
| Contratos REST | [docs/contratos-rest.md](docs/contratos-rest.md) |
| Contratos de mensajes (JSON Schema + ejemplos) | [docs/contratos/](docs/contratos/) |
| Redis: diseño, invalidación, fallos y **mediciones** | [docs/redis.md](docs/redis.md) |
| Ciclo MLOps A–F, selección, umbral y resultados | [docs/ml-mlops.md](docs/ml-mlops.md) |
| Idempotencia, outbox, reserva atómica, importación CSV | [docs/idempotencia-y-seguridad.md](docs/idempotencia-y-seguridad.md) |
| **Guía de demostración** (cuentas y pasos en el navegador) | [docs/guia-demo.md](docs/guia-demo.md) |
| **Instrucciones de reproducción** | [docs/reproduccion.md](docs/reproduccion.md) |

## Estructura

```
docker-compose.yml        Todo el sistema (y el perfil "ml" para entrenar)
infra/                    Generación de secretos e inicialización de PostgreSQL
libs/common/              Librería compartida: auth JWT, outbox, consumidor con reintentos y DLQ
services/{productos,clientes,prestamos,inventario}/   Microservicios (FastAPI)
frontend/                 React + Vite, servido por nginx (proxy a las APIs)
ml/                       Paquete del modelo, scripts del ciclo MLOps, registry, reportes, historial MLflow
data/                     prestamos_entrenamiento.csv, solicitudes_nuevas.csv, clientes_demo.csv
scripts/                  Pruebas de aceptación, mediciones de Redis, drift, pruebas unitarias
tests/                    Pruebas unitarias
docs/                     Documentación
```

## Requisitos obligatorios → evidencia

| Requisito | Evidencia |
|---|---|
| 4 microservicios con bases separadas | 4 bases lógicas con usuarios restringidos (`infra/postgres/01-init.sh`). Comunicación solo por API o mensajes. |
| Flujo completo con estados | `services/prestamos/app/estados.py`, [maquina-estados.md](docs/maquina-estados.md), pruebas 1–7 y VEN |
| RabbitMQ en el flujo real + decisión | `libs/common/credimarket_common/mensajeria.py`, [decision-broker.md](docs/decision-broker.md), pruebas 5, 6 y DLQ |
| Redis cache-aside con mediciones | `services/productos/app/cache.py`, [redis.md](docs/redis.md), pruebas 8 y 9 |
| MLOps A–F con MLflow | `ml/`, [ml-mlops.md](docs/ml-mlops.md), http://localhost:5000, pruebas 10 y 11 |
| Seguridad, idempotencia y outbox | [idempotencia-y-seguridad.md](docs/idempotencia-y-seguridad.md), pruebas 5, 12 y 13 |
| Frontend integrado con roles | `frontend/`, [guia-demo.md](docs/guia-demo.md) |
| Docker Compose reproducible | `docker compose up -d --build` desde un clon limpio |

**Extensiones opcionales incluidas:** registro de modelos con alias en MLflow, monitoreo de drift (PSI) y CI con GitHub Actions (`.github/workflows/ci.yml` en la raíz del repositorio).
