#!/bin/sh
# Genera /config.js al iniciar el contenedor: URLs de APIs y enlaces configurables sin recompilar.
set -eu
cat > /usr/share/nginx/html/config.js <<EOF
window.__CONFIG__ = {
  PRODUCTOS_API: "${PRODUCTOS_API:-/api/productos}",
  CLIENTES_API: "${CLIENTES_API:-/api/clientes}",
  PRESTAMOS_API: "${PRESTAMOS_API:-/api/prestamos}",
  INVENTARIO_API: "${INVENTARIO_API:-/api/inventario}",
  MLFLOW_URL: "${MLFLOW_PUBLIC_URL:-http://localhost:5000}",
  RABBITMQ_URL: "${RABBITMQ_PUBLIC_URL:-http://localhost:15672}"
};
EOF
echo "config.js generado"
