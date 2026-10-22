#!/bin/sh
# Ejecuta las pruebas unitarias dentro de las mismas imágenes de los servicios (mismas dependencias).
set -eu
cd "$(dirname "$0")/.."
docker compose run --rm --no-deps -v "$(pwd)/tests/prestamos:/srv/tests" -e DB_USER=x -e DB_NAME=x \
  prestamos python -m unittest discover -s /srv/tests -v
docker compose run --rm --no-deps -v "$(pwd)/tests/clientes:/srv/tests" \
  clientes python -m unittest discover -s /srv/tests -v
