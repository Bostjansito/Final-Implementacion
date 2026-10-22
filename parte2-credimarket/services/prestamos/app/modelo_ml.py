"""Carga y uso del modelo de riesgo exportado.

* Se carga UNA vez al iniciar (o con POST /modelo/recargar), nunca por petición.
* La versión la decide registry/active.json (promoción explícita), no "el último archivo".
* Se verifica el hash del artefacto contra el manifiesto y que las dependencias
  coincidan con las del entrenamiento.
"""
import hashlib
import json
import logging
import math
import os
import threading
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn

from credimarket_ml.variables import ENTRADAS, ENTRADAS_CATEGORICAS, ENTRADAS_NUMERICAS

log = logging.getLogger(__name__)
REGISTRY = Path(os.environ.get("MODEL_REGISTRY", "/srv/registry"))


class ModeloNoDisponible(Exception):
    pass


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


class ModeloRiesgo:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.pipeline = None
        self.manifiesto: dict | None = None
        self.error: str | None = None

    @property
    def listo(self) -> bool:
        return self.pipeline is not None

    def cargar(self) -> None:
        try:
            activo = json.loads((REGISTRY / "active.json").read_text(encoding="utf-8"))
            carpeta = REGISTRY / "models" / activo["model_version"]
            manifiesto = json.loads((carpeta / "manifest.json").read_text(encoding="utf-8"))
            artefacto = carpeta / manifiesto["artefacto"]["archivo"]
            if _sha256(artefacto) != manifiesto["artefacto"]["sha256"]:
                raise ModeloNoDisponible("El hash del artefacto no coincide con el manifiesto")
            esperado = manifiesto["dependencias"]["scikit-learn"]
            if sklearn.__version__ != esperado:
                raise ModeloNoDisponible(f"scikit-learn {sklearn.__version__} != {esperado} del entrenamiento")
            pipeline = joblib.load(artefacto)
        except ModeloNoDisponible as exc:
            self.error = str(exc)
            log.error("Modelo no cargado: %s", exc)
            raise
        except Exception as exc:  # noqa: BLE001
            self.error = f"{type(exc).__name__}: {exc}"
            log.exception("Modelo no cargado")
            raise ModeloNoDisponible(self.error) from exc
        with self._lock:
            self.pipeline, self.manifiesto, self.error = pipeline, manifiesto, None
        log.info("Modelo %s cargado (run %s, umbral %.2f)", manifiesto["model_version"], manifiesto["run_id"],
                 manifiesto["umbral"])

    def info(self) -> dict:
        if not self.listo:
            raise ModeloNoDisponible(self.error or "Modelo no cargado")
        m = self.manifiesto
        return {"model_version": m["model_version"], "run_id": m["run_id"], "run_name": m["run_name"],
                "algoritmo": m["algoritmo"], "umbral": m["umbral"], "regla_decision": m["regla_decision"],
                "clase_positiva": m["clase_positiva"], "variables_entrada": m["variables_entrada"],
                "variables_derivadas": m["variables_derivadas"], "dataset": m["dataset"],
                "metricas_prueba": m["metricas"]["prueba"], "dependencias": m["dependencias"],
                "artefacto_sha256": m["artefacto"]["sha256"], "creado_at": m["creado_at"]}

    def predecir(self, registro: dict) -> dict:
        with self._lock:
            pipeline, m = self.pipeline, self.manifiesto
        if pipeline is None:
            raise ModeloNoDisponible(self.error or "Modelo no cargado")
        fila = {c: (np.nan if registro.get(c) is None else registro[c]) for c in ENTRADAS}
        proba = float(pipeline.predict_proba(pd.DataFrame([fila], columns=ENTRADAS))[0, 1])
        umbral = float(m["umbral"])
        return {"probabilidad_incumplimiento": round(proba, 6),
                "decision_riesgo": "ALTO" if proba >= umbral else "BAJO",
                "umbral": umbral, "model_version": m["model_version"], "run_id": m["run_id"]}

    # ------------------------------------------------------------ Monitoreo (drift)
    def psi(self, entradas: list[dict]) -> dict:
        """Population Stability Index de cada variable frente a la distribución de entrenamiento."""
        if not self.listo or not entradas:
            return {}
        ref = self.manifiesto["referencia_drift"]
        df = pd.DataFrame(entradas)
        eps = 1e-4
        resultado = {}
        for col in ENTRADAS_NUMERICAS:
            cortes = [-math.inf if c is None and i == 0 else math.inf if c is None else c
                      for i, c in enumerate(ref[col]["cortes"])]
            serie = pd.to_numeric(df.get(col), errors="coerce").dropna()
            if serie.empty:
                continue
            actual, _ = np.histogram(serie, bins=cortes)
            actual = actual / actual.sum()
            esperado = np.array(ref[col]["proporciones"])
            valor = float(np.sum((actual - esperado) * np.log((actual + eps) / (esperado + eps))))
            resultado[col] = round(valor, 4)
        for col in ENTRADAS_CATEGORICAS:
            esperado = ref[col]["categorias"]
            actual = df.get(col).fillna("desconocido").value_counts(normalize=True).to_dict()
            valor = sum((actual.get(k, 0) - v) * math.log((actual.get(k, 0) + eps) / (v + eps))
                        for k, v in esperado.items())
            resultado[col] = round(float(valor), 4)
        return resultado


modelo = ModeloRiesgo()
