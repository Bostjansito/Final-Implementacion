# Instrucciones de reproducción

## Requisitos
* Docker Desktop (o Docker Engine) con Docker Compose v2.
* ~3 GB de RAM libres. Puertos libres: 8080, 8001–8004, 5000, 15672.
* Opcional: Python 3.10+ para los scripts de prueba (solo librería estándar) y Node 20+ para desarrollar el frontend.

## Desde un clon limpio

```bash
git clone <repositorio> credimarket && cd credimarket
docker compose up -d --build
```

Eso es todo. En el primer arranque:
1. `secrets-init` genera `./.secrets/` con:
   * las contraseñas de PostgreSQL (una por servicio), RabbitMQ y Redis;
   * el par de claves RSA para JWT y el secreto interno;
   * las cuentas de demostración.
2. PostgreSQL crea las 4 bases y los 4 usuarios restringidos (`infra/postgres/01-init.sh`).
3. Cada servicio crea sus tablas y siembra datos de demostración: catálogo, existencias, administrador y 3 clientes.
4. Préstamos carga el modelo activo de `ml/registry/active.json` (versionado en el repositorio).

Comprobar: `docker compose ps` (todo *healthy* o *running*) y abrir **http://localhost:8080**. Las credenciales están en `.secrets/cuentas-demo.txt`.

## Volúmenes y persistencia

| Dato | Dónde |
|---|---|
| PostgreSQL | volumen `credimarket_pgdata` |
| RabbitMQ (colas y mensajes) | volumen `credimarket_rabbitdata` |
| MLflow (metadatos SQLite + artefactos) | `./ml/mlflow` (carpeta del repositorio) |
| Modelos exportados y promociones | `./ml/registry` |
| Particiones e informes de ML | `./ml/artefactos`, `./ml/reportes` |
| Redis | sin persistencia (es caché) |

`docker compose down` conserva todo. `docker compose down -v` borra las bases y las colas: el siguiente arranque vuelve a sembrar los datos de demostración.

## Reentrenar (opcional)

El repositorio ya incluye el historial de MLflow y los modelos v1 y v2. Para regenerar el ciclo completo:

```bash
docker compose up -d mlflow
docker compose --profile ml run --rm ml-trainer
```
`entrenar_todo.sh` **no sobrescribe** versiones exportadas existentes, porque son inmutables. Para exportar una versión nueva:
```bash
docker compose --profile ml run --rm ml-trainer python seleccionar_exportar.py --version v3
```

### Cómo conservar los experimentos
* MLflow guarda todo en `./ml/mlflow`. Para compartir el historial, **detenga MLflow antes de copiarlo o versionarlo** (`docker compose stop mlflow`), así la base SQLite queda consistente. Luego haga commit de la carpeta.
* Los datos no se suben a MLflow en cada ejecución: cada ejecución registra la versión y el SHA-256 del CSV, y los IDs de cada partición están en `ml/artefactos/particiones/`.

## Configuración

Variables con valores por defecto en `docker-compose.yml` (pueden sobrescribirse con un archivo `.env`):

| Variable | Defecto | Uso |
|---|---|---|
| `CORS_ORIGINS` | `http://localhost:8080` | Orígenes permitidos por las APIs |
| `TOKEN_MINUTOS` | 30 | Duración de la sesión |
| `CACHE_TTL_SEGUNDOS` | 300 | TTL de la caché de productos |
| `RESERVA_TTL_SEGUNDOS` | 1800 | Vencimiento de reservas |
| `PENDIENTE_TIMEOUT_SEGUNDOS` | 600 | Espera máxima por Inventario |
| `MLFLOW_PUBLIC_URL`, `RABBITMQ_PUBLIC_URL` | localhost | Enlaces del frontend |

## Desarrollo del frontend
```bash
cd frontend && npm ci && npm run dev   # http://localhost:5173 (proxy a los servicios en :8001–8004)
```

## Problemas comunes
| Síntoma | Solución |
|---|---|
| Un puerto está ocupado | Cambie el puerto publicado en `docker-compose.yml`. |
| `prestamos` no está *ready* | `curl localhost:8003/ready` muestra `modelo_error`. Verifique que exista `ml/registry/active.json`. |
| Quiere empezar de cero, incluidas las contraseñas | `docker compose down -v` y borrar la carpeta `.secrets/`. |
