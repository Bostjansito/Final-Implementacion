"""Máquina de estados del préstamo (ver docs/maquina-estados.md).

Estados obligatorios del enunciado + dos internos:
* EVALUANDO: la solicitud quedó registrada (clave de idempotencia tomada) y se
  están reuniendo datos y ejecutando el modelo.
* CANCELANDO: se pidió la cancelación y se espera que Inventario libere la reserva
  ("una cancelación previa a la entrega debe liberar la reserva antes de finalizar").
"""
EVALUANDO = "EVALUANDO"
RECHAZADA = "RECHAZADA"
PENDIENTE_INVENTARIO = "PENDIENTE_INVENTARIO"
APROBADA = "APROBADA"
CANCELADA_SIN_STOCK = "CANCELADA_SIN_STOCK"
COMPLETADA = "COMPLETADA"
CANCELANDO = "CANCELANDO"
CANCELADA = "CANCELADA"

TRANSICIONES: dict[str, set[str]] = {
    EVALUANDO: {RECHAZADA, PENDIENTE_INVENTARIO},
    PENDIENTE_INVENTARIO: {APROBADA, CANCELADA_SIN_STOCK, CANCELANDO},
    APROBADA: {COMPLETADA, CANCELANDO, CANCELADA},  # CANCELADA directa: la reserva venció
    CANCELANDO: {CANCELADA, COMPLETADA},            # COMPLETADA: la entrega ya había ocurrido
    RECHAZADA: set(),
    CANCELADA_SIN_STOCK: set(),
    COMPLETADA: set(),
    CANCELADA: set(),
}

FINALES = {e for e, siguientes in TRANSICIONES.items() if not siguientes}
CANCELABLES = {PENDIENTE_INVENTARIO, APROBADA}


class TransicionInvalida(Exception):
    pass


def validar_transicion(actual: str, nuevo: str) -> None:
    if nuevo not in TRANSICIONES.get(actual, set()):
        raise TransicionInvalida(f"No se permite pasar de {actual} a {nuevo}")
