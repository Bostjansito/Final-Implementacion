// Configuración por defecto para desarrollo local. En Docker este archivo se regenera
// al iniciar el contenedor a partir de variables de entorno (ver frontend/docker/40-config.sh).
window.__CONFIG__ = {
  PRODUCTOS_API: "/api/productos",
  CLIENTES_API: "/api/clientes",
  PRESTAMOS_API: "/api/prestamos",
  INVENTARIO_API: "/api/inventario",
  MLFLOW_URL: "http://localhost:5000",
  RABBITMQ_URL: "http://localhost:15672",
};
