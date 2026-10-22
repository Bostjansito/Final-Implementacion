"""Definición de variables del modelo de riesgo.

Decisiones (ver ml/reportes/informe_seleccion.md):
* ``solicitud_id`` y ``cliente_id`` -> excluidos: son identificadores de trazabilidad.
* ``incumplimiento_90d`` -> etiqueta (clase positiva = 1); nunca es entrada.
* ``tasa_mensual_simulada`` -> excluida: es constante (0,018) en todo el histórico.
* ``cuota_estimada_cop`` -> excluida como entrada: es redundante, función
  determinista de monto, plazo y tasa. Se recalcula DENTRO del pipeline, así la
  API no depende de que alguien envíe una cuota coherente.
"""
import numpy as np
import pandas as pd

TASA_MENSUAL = 0.018
ID_COLUMNAS = ["solicitud_id", "cliente_id"]
ETIQUETA = "incumplimiento_90d"
EXCLUIDAS = ["tasa_mensual_simulada", "cuota_estimada_cop"]

ENTRADAS_NUMERICAS = [
    "ingresos_mensuales_cop", "obligaciones_mensuales_cop", "antiguedad_laboral_meses",
    "meses_historial_crediticio", "creditos_previos", "atrasos_previos_30d", "porcentaje_pago_puntual",
    "monto_solicitado_cop", "plazo_meses",
]
ENTRADAS_CATEGORICAS = ["tipo_empleo"]
ENTRADAS = ENTRADAS_NUMERICAS + ENTRADAS_CATEGORICAS

DERIVADAS = ["cuota_calculada_cop", "ratio_endeudamiento", "ratio_cuota_ingreso", "carga_financiera",
             "ratio_monto_ingreso"]

CATEGORIAS_EMPLEO = ["dependiente", "independiente", "temporal"]
PLAZOS_PERMITIDOS = [6, 12, 18, 24, 36]

# Rangos y faltantes permitidos: los usa la validación de datos y la API.
ESPECIFICACION = {
    "ingresos_mensuales_cop": {"tipo": "int", "min": 100_000, "max": 200_000_000, "nulo": False},
    "obligaciones_mensuales_cop": {"tipo": "int", "min": 0, "max": 200_000_000, "nulo": False},
    "antiguedad_laboral_meses": {"tipo": "float", "min": 0, "max": 600, "nulo": True},
    "meses_historial_crediticio": {"tipo": "float", "min": 0, "max": 600, "nulo": True},
    "creditos_previos": {"tipo": "int", "min": 0, "max": 100, "nulo": False},
    "atrasos_previos_30d": {"tipo": "int", "min": 0, "max": 100, "nulo": False},
    "porcentaje_pago_puntual": {"tipo": "float", "min": 0, "max": 100, "nulo": True},
    "monto_solicitado_cop": {"tipo": "int", "min": 500_000, "max": 15_000_000, "nulo": False},
    "plazo_meses": {"tipo": "int", "valores": PLAZOS_PERMITIDOS, "nulo": False},
    "tipo_empleo": {"tipo": "categoria", "valores": CATEGORIAS_EMPLEO, "nulo": True},
}


def cuota_mensual(monto, plazo, tasa: float = TASA_MENSUAL):
    """Cuota de amortización francesa (la misma fórmula que generó el histórico)."""
    monto = np.asarray(monto, dtype=float)
    plazo = np.asarray(plazo, dtype=float)
    return monto * tasa / (1 - (1 + tasa) ** (-plazo))


def agregar_variables(X: pd.DataFrame) -> pd.DataFrame:
    """Transformación determinista (sin parámetros aprendidos) usada como primer paso del pipeline."""
    X = X.copy()
    ingresos = X["ingresos_mensuales_cop"].astype(float).clip(lower=1)
    obligaciones = X["obligaciones_mensuales_cop"].astype(float)
    cuota = cuota_mensual(X["monto_solicitado_cop"], X["plazo_meses"])
    X["cuota_calculada_cop"] = cuota
    X["ratio_endeudamiento"] = obligaciones / ingresos
    X["ratio_cuota_ingreso"] = cuota / ingresos
    X["carga_financiera"] = (obligaciones + cuota) / ingresos
    X["ratio_monto_ingreso"] = X["monto_solicitado_cop"].astype(float) / ingresos
    X["tipo_empleo"] = X["tipo_empleo"].astype(object).where(X["tipo_empleo"].notna(), np.nan)
    return X


def validar_registro(registro: dict) -> list[str]:
    """Devuelve la lista de errores de un registro de entrada (vacía si es válido)."""
    errores = []
    for campo, spec in ESPECIFICACION.items():
        valor = registro.get(campo)
        if valor is None or (isinstance(valor, float) and np.isnan(valor)):
            if not spec["nulo"]:
                errores.append(f"{campo}: es obligatorio")
            continue
        if spec["tipo"] == "categoria":
            if valor not in spec["valores"]:
                errores.append(f"{campo}: valor no permitido ({valor}); permitidos {spec['valores']}")
            continue
        if not isinstance(valor, (int, float)) or isinstance(valor, bool):
            errores.append(f"{campo}: debe ser numérico")
            continue
        if spec["tipo"] == "int" and float(valor) != int(valor):
            errores.append(f"{campo}: debe ser entero")
        if "valores" in spec and valor not in spec["valores"]:
            errores.append(f"{campo}: valor no permitido ({valor}); permitidos {spec['valores']}")
        if "min" in spec and not (spec["min"] <= valor <= spec["max"]):
            errores.append(f"{campo}: fuera de rango [{spec['min']}, {spec['max']}]")
    desconocidos = set(registro) - set(ESPECIFICACION)
    if desconocidos:
        errores.append(f"campos no permitidos: {sorted(desconocidos)}")
    return errores
