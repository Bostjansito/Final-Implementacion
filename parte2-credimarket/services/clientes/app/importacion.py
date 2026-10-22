"""Importación masiva de clientes por CSV.

Política (documentada en docs/clientes-importacion.md):
* Clave externa única: ``codigo_externo`` (acepta también la columna ``cliente_id``
  del histórico entregado).
* Si el código no existe -> se inserta.
* Si existe y los datos son iguales -> "sin cambios" (importar dos veces el mismo
  archivo no duplica ni modifica nada).
* Si existe y los datos cambian -> se actualiza (gana el último archivo).
* Filas inválidas -> se rechazan con el número de fila y el motivo; el resto
  del archivo se procesa.
* Un código repetido dentro del mismo archivo -> la segunda aparición se rechaza.
* La restricción UNIQUE(codigo_externo) en la base de datos impide duplicados
  incluso si dos importaciones corren al mismo tiempo (INSERT ... ON CONFLICT).
"""
import csv
import io
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .modelos import CAMPOS_FINANCIEROS, TIPOS_EMPLEO, Cliente

COLUMNAS_OBLIGATORIAS = {"codigo_externo", "ingresos_mensuales_cop", "obligaciones_mensuales_cop"}
MAX_FILAS = 20_000


def _vacio(v: str | None) -> bool:
    return v is None or str(v).strip() == ""


def _num(fila: dict, campo: str, tipo, minimo: float, maximo: float, obligatorio: bool = False):
    v = fila.get(campo)
    if _vacio(v):
        if obligatorio:
            raise ValueError(f"{campo} es obligatorio")
        return None
    try:
        n = float(str(v).strip().replace(",", "."))
    except ValueError:
        raise ValueError(f"{campo} no es numérico ({v!r})") from None
    if not (minimo <= n <= maximo):
        raise ValueError(f"{campo} fuera de rango [{minimo}, {maximo}] ({v})")
    if tipo is int:
        if n != int(n):
            raise ValueError(f"{campo} debe ser entero ({v})")
        return int(n)
    return round(n, 4)


def validar_fila(fila: dict) -> dict:
    codigo = (fila.get("codigo_externo") or "").strip()
    if not codigo or len(codigo) > 40:
        raise ValueError("codigo_externo vacío o demasiado largo")
    tipo = (fila.get("tipo_empleo") or "").strip().lower() or None
    if tipo is not None and tipo not in TIPOS_EMPLEO:
        raise ValueError(f"tipo_empleo inválido ({tipo}); valores: {', '.join(TIPOS_EMPLEO)}")
    datos = {
        "codigo_externo": codigo,
        "nombre": (fila.get("nombre") or "").strip() or f"Cliente {codigo}",
        "documento": (fila.get("documento") or "").strip() or None,
        "email": (fila.get("email") or "").strip().lower() or None,
        "telefono": (fila.get("telefono") or "").strip() or None,
        "ingresos_mensuales_cop": _num(fila, "ingresos_mensuales_cop", int, 1, 1_000_000_000, True),
        "obligaciones_mensuales_cop": _num(fila, "obligaciones_mensuales_cop", int, 0, 1_000_000_000, True),
        "tipo_empleo": tipo,
        "antiguedad_laboral_meses": _num(fila, "antiguedad_laboral_meses", float, 0, 720),
        "meses_historial_crediticio": _num(fila, "meses_historial_crediticio", float, 0, 720),
        "creditos_previos": _num(fila, "creditos_previos", int, 0, 200),
        "atrasos_previos_30d": _num(fila, "atrasos_previos_30d", int, 0, 200),
        "porcentaje_pago_puntual": _num(fila, "porcentaje_pago_puntual", float, 0, 100),
    }
    if datos["email"] and "@" not in datos["email"]:
        raise ValueError(f"email inválido ({datos['email']})")
    return datos


CAMPOS_COMPARADOS = ("nombre", "documento", "email", "telefono") + CAMPOS_FINANCIEROS


def importar(s: Session, contenido: bytes) -> dict:
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("El archivo debe estar codificado en UTF-8") from None
    lector = csv.DictReader(io.StringIO(texto))
    if lector.fieldnames is None:
        raise ValueError("El archivo está vacío")
    columnas = {c.strip() for c in lector.fieldnames}
    alias = "cliente_id" in columnas and "codigo_externo" not in columnas
    if alias:
        columnas.add("codigo_externo")
    faltan = COLUMNAS_OBLIGATORIAS - columnas
    if faltan:
        raise ValueError(f"Faltan columnas obligatorias: {', '.join(sorted(faltan))}")

    resumen = {"filas": 0, "insertados": 0, "actualizados": 0, "sin_cambios": 0, "rechazados": 0,
               "errores": []}
    vistos: set[str] = set()
    validas: list[tuple[int, dict]] = []
    for numero, fila in enumerate(lector, start=2):  # la fila 1 es el encabezado
        resumen["filas"] += 1
        if resumen["filas"] > MAX_FILAS:
            raise ValueError(f"El archivo supera el máximo de {MAX_FILAS} filas")
        fila = {(k or "").strip(): v for k, v in fila.items()}
        if alias:
            fila["codigo_externo"] = fila.get("cliente_id")
        try:
            datos = validar_fila(fila)
            if datos["codigo_externo"] in vistos:
                raise ValueError(f"codigo_externo repetido en el archivo ({datos['codigo_externo']})")
            vistos.add(datos["codigo_externo"])
            validas.append((numero, datos))
        except ValueError as exc:
            resumen["rechazados"] += 1
            resumen["errores"].append({"fila": numero, "codigo_externo": fila.get("codigo_externo"),
                                       "error": str(exc)})

    existentes = {c.codigo_externo: c for c in s.scalars(
        select(Cliente).where(Cliente.codigo_externo.in_([d["codigo_externo"] for _, d in validas])))}
    for _numero, datos in validas:
        actual = existentes.get(datos["codigo_externo"])
        if actual is not None and all(getattr(actual, c) == datos[c] for c in CAMPOS_COMPARADOS):
            resumen["sin_cambios"] += 1
            continue
        stmt = insert(Cliente).values(id=str(uuid.uuid4()), origen="importacion", activo=True, **datos)
        stmt = stmt.on_conflict_do_update(
            index_elements=["codigo_externo"],
            set_={c: stmt.excluded[c] for c in CAMPOS_COMPARADOS},
        )
        s.execute(stmt)
        resumen["actualizados" if actual is not None else "insertados"] += 1
    return resumen
