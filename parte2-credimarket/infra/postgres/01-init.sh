#!/bin/sh
# Crea una base de datos lógica y un usuario restringido por servicio.
# Ningún usuario de servicio puede conectarse a la base de otro servicio.
set -eu

for svc in productos clientes prestamos inventario; do
  pass="$(cat /run/secrets/${svc}_db_password)"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
    CREATE ROLE ${svc}_user LOGIN PASSWORD '${pass}';
    CREATE DATABASE ${svc}_db OWNER ${svc}_user;
    REVOKE ALL ON DATABASE ${svc}_db FROM PUBLIC;
    GRANT CONNECT ON DATABASE ${svc}_db TO ${svc}_user;
EOSQL
  echo "Base ${svc}_db creada"
done
