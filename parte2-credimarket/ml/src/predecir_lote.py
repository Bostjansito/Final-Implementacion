"""Predice con el artefacto EXPORTADO (fuera de la API) para comparar con /riesgo/predict.

    docker compose --profile ml run --rm ml-trainer python predecir_lote.py [--version v1]
Escribe ml/artefactos/predicciones_locales_<version>.json
"""
import argparse
import json

import joblib
import numpy as np
import pandas as pd

from comun import ARTEFACTOS, NUEVAS, REGISTRY
from credimarket_ml.variables import ENTRADAS, validar_registro


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=None, help="por defecto, la versión activa")
    args = ap.parse_args()
    version = args.version or json.loads((REGISTRY / "active.json").read_text())["model_version"]
    modelo = joblib.load(REGISTRY / "models" / version / "modelo.joblib")
    df = pd.read_csv(NUEVAS)
    salida = []
    for _, fila in df.iterrows():
        registro = {c: (None if pd.isna(fila[c]) else (fila[c].item() if hasattr(fila[c], "item") else fila[c]))
                    for c in ENTRADAS}
        if validar_registro(registro):
            continue  # la API rechazaría la fila; no hay predicción que comparar
        x = pd.DataFrame([{c: (np.nan if v is None else v) for c, v in registro.items()}], columns=ENTRADAS)
        salida.append({"solicitud_id": fila["solicitud_id"], "entrada": registro,
                       "probabilidad": float(modelo.predict_proba(x)[0, 1])})
    ARTEFACTOS.mkdir(parents=True, exist_ok=True)
    destino = ARTEFACTOS / f"predicciones_locales_{version}.json"
    destino.write_text(json.dumps({"model_version": version, "predicciones": salida}, indent=1), encoding="utf-8")
    print(f"{len(salida)} predicciones locales con {version} -> {destino.name} ({len(df) - len(salida)} filas inválidas)")


if __name__ == "__main__":
    main()
