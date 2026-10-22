"""Datos de demostración compartidos (catálogo inicial).

Los identificadores son deterministas (uuid5 del SKU) para que Productos e
Inventario siembren los mismos productos sin consultarse las tablas.
"""
import uuid

_NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://credimarket.test/productos")


def id_producto(sku: str) -> str:
    return str(uuid.uuid5(_NS, sku))


# sku, nombre, categoría, precio COP, existencias iniciales, descripción
CATALOGO = [
    ("PC-ULT-001", "Portátil Ultra 14", "computadores", 4_200_000, 1,
     "El último computador en bodega: sirve para probar la concurrencia."),
    ("PC-GAM-002", "Portátil Gamer 16", "computadores", 7_800_000, 5,
     "Procesador de alto rendimiento y tarjeta gráfica dedicada."),
    ("CEL-PRO-003", "Celular Pro 256 GB", "celulares", 3_600_000, 10,
     "Cámara triple y pantalla de 6,7 pulgadas."),
    ("CEL-LIT-004", "Celular Lite 128 GB", "celulares", 1_200_000, 20,
     "Batería de larga duración."),
    ("TAB-AIR-005", "Tablet Air 11", "tablets", 2_500_000, 0,
     "Sin existencias: sirve para probar CANCELADA_SIN_STOCK."),
    ("AUD-NC-006", "Audífonos con cancelación de ruido", "accesorios", 650_000, 15,
     "Bluetooth 5.3, 30 horas de batería."),
]
