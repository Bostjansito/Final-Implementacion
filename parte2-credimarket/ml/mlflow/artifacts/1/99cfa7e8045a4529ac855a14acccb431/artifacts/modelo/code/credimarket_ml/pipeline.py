"""Construcción del pipeline completo (preprocesamiento + estimador).

Todas las transformaciones aprendidas (imputación, escalado, codificación) viven
dentro del pipeline y se ajustan SOLO con el conjunto de entrenamiento.
"""
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

from .variables import DERIVADAS, ENTRADAS_CATEGORICAS, ENTRADAS_NUMERICAS, agregar_variables

PARAMETROS_PREPROCESAMIENTO = {
    "imputacion_numerica": "mediana + indicador de faltante",
    "escalado_numerico": "StandardScaler",
    "imputacion_categorica": "constante 'desconocido'",
    "codificacion_categorica": "OneHotEncoder(handle_unknown='ignore')",
    "variables_derivadas": ",".join(DERIVADAS),
}


def construir_preprocesador() -> Pipeline:
    numericas = ENTRADAS_NUMERICAS + DERIVADAS
    columnas = ColumnTransformer([
        ("num", Pipeline([
            ("imputar", SimpleImputer(strategy="median", add_indicator=True)),
            ("escalar", StandardScaler()),
        ]), numericas),
        ("cat", Pipeline([
            ("imputar", SimpleImputer(strategy="constant", fill_value="desconocido")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]), ENTRADAS_CATEGORICAS),
    ])
    return Pipeline([("variables", FunctionTransformer(agregar_variables)), ("columnas", columnas)])


def construir_modelo(estimador) -> Pipeline:
    return Pipeline([("preprocesamiento", construir_preprocesador()), ("modelo", estimador)])
