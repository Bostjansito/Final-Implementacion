"""Etapas B y C: entrenar baseline + candidatos y registrar cada ejecución en MLflow.

La selección usa SOLO validación. La métrica de selección y el desempate se
definen antes de comparar (ver comun.METRICA_SELECCION y CRITERIO_DESEMPATE).
"""
import json
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import mlflow
import mlflow.sklearn
import pandas as pd
from mlflow.models import infer_signature
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier

import metricas
from comun import (COSTO_FN, COSTO_FP, CRITERIO_DESEMPATE, ENTRADAS, ESTRATEGIA_PARTICION, EXPERIMENTO,
                   METRICA_SELECCION, ML_DIR, REPORTES, SEMILLA, cargar_particiones, commit_git, info_dataset,
                   version_codigo)
from credimarket_ml.pipeline import PARAMETROS_PREPROCESAMIENTO, construir_modelo
from credimarket_ml.variables import DERIVADAS, EXCLUIDAS

UMBRAL_REFERENCIA = 0.5  # solo para reportar métricas por umbral antes de elegir el umbral definitivo

CANDIDATOS = [
    ("baseline_prior", "baseline", DummyClassifier(strategy="prior"),
     "Baseline trivial: predice la tasa base de incumplimiento para todos."),
    ("logreg_C1_balanced", "logreg",
     LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000, random_state=SEMILLA),
     "Modelo lineal interpretable; class_weight compensa el desbalance 70/30."),
    ("logreg_C1_sin_pesos", "logreg",
     LogisticRegression(C=1.0, max_iter=2000, random_state=SEMILLA),
     "Sin class_weight: conserva la calibración de las probabilidades (comparar Brier con la versión balanceada)."),
    ("logreg_C0.05_balanced", "logreg",
     LogisticRegression(C=0.05, class_weight="balanced", max_iter=2000, random_state=SEMILLA),
     "Más regularización L2 para evaluar si el modelo lineal sobreajusta."),
    ("arbol_d4_hoja50", "arbol",
     DecisionTreeClassifier(max_depth=4, min_samples_leaf=50, class_weight="balanced", random_state=SEMILLA),
     "Árbol poco profundo: reglas simples y explicables."),
    ("arbol_d8_hoja20", "arbol",
     DecisionTreeClassifier(max_depth=8, min_samples_leaf=20, class_weight="balanced", random_state=SEMILLA),
     "Árbol más profundo para capturar interacciones; hoja mínima limita el sobreajuste."),
    ("rf_200_d8", "rf",
     RandomForestClassifier(n_estimators=200, max_depth=8, min_samples_leaf=10, class_weight="balanced_subsample",
                            n_jobs=-1, random_state=SEMILLA),
     "Bosque con profundidad moderada: reduce varianza respecto al árbol individual."),
    ("rf_200_d12", "rf",
     RandomForestClassifier(n_estimators=200, max_depth=12, min_samples_leaf=5, class_weight="balanced_subsample",
                            n_jobs=-1, random_state=SEMILLA),
     "Bosque más profundo para comprobar si más capacidad mejora AP en validación."),
    ("hgb_lr0.05_hojas15", "hgb",
     HistGradientBoostingClassifier(learning_rate=0.05, max_iter=300, max_leaf_nodes=15, l2_regularization=1.0,
                                    random_state=SEMILLA),
     "Boosting con tasa de aprendizaje baja y regularización L2."),
    ("hgb_lr0.1_prof4", "hgb",
     HistGradientBoostingClassifier(learning_rate=0.1, max_iter=200, max_depth=4, random_state=SEMILLA),
     "Boosting con árboles poco profundos (menor riesgo de sobreajuste)."),
]


def parametros_simples(estimador) -> dict:
    return {f"modelo__{k}": v for k, v in estimador.get_params().items()
            if isinstance(v, (int, float, str, bool)) or v is None}


def dependencias() -> str:
    return subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)


def main() -> None:
    datos = cargar_particiones()
    (X_tr, y_tr), (X_va, y_va) = datos["train"], datos["val"]
    info = info_dataset()
    mlflow.set_experiment(EXPERIMENTO)
    deps = dependencias()
    filas = []

    for nombre, familia, estimador, justificacion in CANDIDATOS:
        modelo = construir_modelo(estimador)
        with mlflow.start_run(run_name=nombre) as run, tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            mlflow.set_tags({"familia": familia, "tipo": "baseline" if familia == "baseline" else "candidato",
                             "justificacion": justificacion, "metrica_seleccion": METRICA_SELECCION,
                             "criterio_desempate": CRITERIO_DESEMPATE})
            mlflow.log_params({
                "algoritmo": type(estimador).__name__, "semilla": SEMILLA,
                "estrategia_particion": ESTRATEGIA_PARTICION, "dataset_archivo": info["archivo"],
                "dataset_version": info["version"], "dataset_sha256": info["sha256"],
                "variables_entrada": ",".join(ENTRADAS), "variables_derivadas": ",".join(DERIVADAS),
                "variables_excluidas": ",".join(EXCLUIDAS) + ",solicitud_id,cliente_id",
                "codigo_version": version_codigo(), "git_commit": commit_git(),
                "python": platform.python_version(), "costo_fn": COSTO_FN, "costo_fp": COSTO_FP,
                **{f"prep__{k}": v for k, v in PARAMETROS_PREPROCESAMIENTO.items()},
                **parametros_simples(estimador),
            })
            inicio = time.perf_counter()
            modelo.fit(X_tr, y_tr)
            duracion = time.perf_counter() - inicio
            p_tr, p_va = modelo.predict_proba(X_tr)[:, 1], modelo.predict_proba(X_va)[:, 1]
            m = {**metricas.calcular(y_tr, p_tr, UMBRAL_REFERENCIA, "train"),
                 **metricas.calcular(y_va, p_va, UMBRAL_REFERENCIA, "val"),
                 "duracion_entrenamiento_s": duracion}
            mlflow.log_metrics(m)

            metricas.figura_confusion(y_va, p_va, UMBRAL_REFERENCIA, f"{nombre} — validación (umbral 0.5)",
                                      tmp / "matriz_confusion_val.png")
            metricas.figura_calibracion(y_va, p_va, f"{nombre} — calibración (validación)",
                                        tmp / "calibracion_val.png")
            (tmp / "reporte_evaluacion.json").write_text(json.dumps(
                {"modelo": nombre, "familia": familia, "justificacion": justificacion,
                 "umbral_referencia": UMBRAL_REFERENCIA, "metricas": m}, indent=2), encoding="utf-8")
            (tmp / "requirements.txt").write_text(deps, encoding="utf-8")
            mlflow.log_artifacts(str(tmp), artifact_path="evaluacion")
            mlflow.sklearn.log_model(
                modelo, artifact_path="modelo", code_paths=[str(ML_DIR / "credimarket_ml")],
                signature=infer_signature(X_va.head(50), p_va[:50]), input_example=X_va.head(3),
            )
            filas.append({"run_id": run.info.run_id, "modelo": nombre, "familia": familia,
                          **{k: round(v, 4) for k, v in m.items() if k.startswith("val_") or k.startswith("train_a")}})
            print(f"{nombre:28s} val_AP={m['val_average_precision']:.4f} val_AUC={m['val_roc_auc']:.4f} "
                  f"({duracion:.1f}s)")

    REPORTES.mkdir(parents=True, exist_ok=True)
    tabla = pd.DataFrame(filas).sort_values("val_average_precision", ascending=False)
    tabla.to_csv(REPORTES / "comparacion_modelos.csv", index=False)
    print(tabla[["modelo", "val_average_precision", "val_roc_auc", "val_f1_1", "val_brier"]].to_string(index=False))


if __name__ == "__main__":
    main()
