"""Etapa D: seleccionar modelo y umbral, evaluar UNA vez en prueba y exportar con manifiesto.

Uso:
    python seleccionar_exportar.py --version v1                 # mejor candidato global
    python seleccionar_exportar.py --version v2 --familia logreg  # versión alternativa (para promoción/rollback)
"""
import argparse
import json
import platform
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import mlflow  # noqa: E402
import mlflow.sklearn  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import sklearn  # noqa: E402
from mlflow.tracking import MlflowClient  # noqa: E402

import metricas  # noqa: E402
from comun import (COMPLEJIDAD, COSTO_FN, COSTO_FP, CRITERIO_DESEMPATE, ENTRADAS, EXPERIMENTO,  # noqa: E402
                   METRICA_SELECCION, NOMBRE_REGISTRO, NUEVAS, REGISTRY, REPORTES, cargar_particiones,
                   commit_git, info_dataset, sha256_archivo, version_codigo)
from credimarket_ml.variables import (DERIVADAS, ENTRADAS_CATEGORICAS, ENTRADAS_NUMERICAS,  # noqa: E402
                                      ESPECIFICACION)


def elegir_run(client: MlflowClient, familia: str | None):
    exp = client.get_experiment_by_name(EXPERIMENTO)
    filtro = "tags.tipo = 'candidato'" + (f" and tags.familia = '{familia}'" if familia else "")
    runs = client.search_runs([exp.experiment_id], filtro, order_by=[f"metrics.{METRICA_SELECCION} DESC"])
    if not runs:
        raise SystemExit("No hay ejecuciones candidatas: ejecute entrenar.py")
    ap = runs[0].data.metrics[METRICA_SELECCION]
    empatados = [r for r in runs if ap - r.data.metrics[METRICA_SELECCION] < 0.005]
    auc = max(r.data.metrics["val_roc_auc"] for r in empatados)
    empatados = [r for r in empatados if auc - r.data.metrics["val_roc_auc"] < 0.005]
    empatados.sort(key=lambda r: (COMPLEJIDAD[r.data.tags["familia"]], r.data.metrics["val_brier"]))
    return empatados[0], runs


def referencia_drift(X: pd.DataFrame) -> dict:
    """Distribución de entrenamiento por variable, para calcular PSI en producción."""
    ref = {}
    for col in ENTRADAS_NUMERICAS:
        serie = X[col].dropna().astype(float)
        cortes = np.unique(np.quantile(serie, np.linspace(0, 1, 11)))
        cortes[0], cortes[-1] = -np.inf, np.inf
        conteos, _ = np.histogram(serie, bins=cortes)
        ref[col] = {"cortes": [None if np.isinf(c) else float(c) for c in cortes],
                    "proporciones": (conteos / conteos.sum()).round(6).tolist(),
                    "faltantes": round(float(X[col].isna().mean()), 6)}
    for col in ENTRADAS_CATEGORICAS:
        prop = X[col].fillna("desconocido").value_counts(normalize=True).round(6)
        ref[col] = {"categorias": prop.to_dict()}
    return ref


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--familia", default=None)
    args = ap.parse_args()

    destino = REGISTRY / "models" / args.version
    if destino.exists():
        raise SystemExit(f"La versión {args.version} ya existe; las versiones exportadas son inmutables.")

    client = MlflowClient()
    run, ranking = elegir_run(client, args.familia)
    run_id = run.info.run_id
    for otro in (REGISTRY / "models").glob("*/manifest.json"):
        if json.loads(otro.read_text(encoding="utf-8"))["run_id"] == run_id:
            raise SystemExit(f"La ejecución {run_id} ya fue exportada como {otro.parent.name}")
    nombre = run.info.run_name
    print(f"Seleccionado: {nombre} ({run_id}) {METRICA_SELECCION}={run.data.metrics[METRICA_SELECCION]:.4f}")

    datos = cargar_particiones()
    (X_tr, _y_tr), (X_va, y_va), (X_te, y_te) = datos["train"], datos["val"], datos["test"]
    modelo = mlflow.sklearn.load_model(f"runs:/{run_id}/modelo")

    # Umbral: se ajusta en validación minimizando el costo esperado y se congela ANTES de mirar prueba.
    p_va = modelo.predict_proba(X_va)[:, 1]
    umbrales, costos = metricas.curva_costo(y_va.to_numpy(), p_va, COSTO_FN, COSTO_FP)
    umbral = float(umbrales[int(np.argmin(costos))])
    costo_val = float(costos.min())
    print(f"Umbral congelado (validación): {umbral:.2f} — costo esperado {costo_val:.4f} por solicitud")

    # Evaluación final en prueba (una sola vez, con el umbral congelado).
    p_te = modelo.predict_proba(X_te)[:, 1]
    m_val = metricas.calcular(y_va, p_va, umbral, "val_umbral")
    m_test = metricas.calcular(y_te, p_te, umbral, "test")
    _, costos_te = metricas.curva_costo(y_te.to_numpy(), p_te, COSTO_FN, COSTO_FP)
    m_test["test_costo_esperado"] = float(costos_te[int(np.where(umbrales == umbral)[0][0])])

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        fig, ax = plt.subplots(figsize=(5, 3.4))
        ax.plot(umbrales, costos)
        ax.axvline(umbral, color="red", linestyle="--", label=f"umbral = {umbral:.2f}")
        ax.set_xlabel("umbral de probabilidad")
        ax.set_ylabel("costo esperado por solicitud")
        ax.set_title(f"Curva de costo en validación (FN={COSTO_FN:g}, FP={COSTO_FP:g})", fontsize=9)
        ax.legend()
        fig.tight_layout()
        fig.savefig(tmp / "curva_costo_val.png", dpi=110)
        plt.close(fig)
        metricas.figura_confusion(y_te, p_te, umbral, f"{nombre} — PRUEBA (umbral {umbral:.2f})",
                                  tmp / "matriz_confusion_test.png")
        metricas.figura_calibracion(y_te, p_te, f"{nombre} — calibración (prueba)", tmp / "calibracion_test.png")
        pd.DataFrame({"umbral": umbrales, "costo_esperado": costos}).to_csv(tmp / "curva_costo_val.csv", index=False)
        with mlflow.start_run(run_id=run_id):
            mlflow.log_metrics({**m_val, **m_test, "umbral_seleccionado": umbral, "val_costo_esperado": costo_val})
            mlflow.set_tags({f"exportado_{args.version}": "si", "umbral": f"{umbral:.2f}"})
            mlflow.log_artifacts(str(tmp), artifact_path=f"seleccion_{args.version}")
        figs = REPORTES / "figuras"
        figs.mkdir(parents=True, exist_ok=True)
        for f in ("curva_costo_val.png", "matriz_confusion_test.png", "calibracion_test.png"):
            shutil.copy(tmp / f, figs / f"{args.version}_{f}")

    # Exportación del pipeline completo + manifiesto.
    destino.mkdir(parents=True)
    ruta_modelo = destino / "modelo.joblib"
    joblib.dump(modelo, ruta_modelo, compress=3)
    info = info_dataset()
    muestra = pd.read_csv(NUEVAS).head(3)
    entrada = muestra[ENTRADAS].astype(object).where(muestra[ENTRADAS].notna(), None).to_dict(orient="records")
    proba = modelo.predict_proba(muestra[ENTRADAS])[:, 1]
    ejemplo = [{"entrada": e, "salida": {"probabilidad_incumplimiento": round(float(p), 6),
                                         "decision_riesgo": "ALTO" if p >= umbral else "BAJO",
                                         "umbral": umbral, "model_version": args.version}}
               for e, p in zip(entrada, proba)]
    (destino / "ejemplo_entrada_salida.json").write_text(json.dumps(ejemplo, indent=2, ensure_ascii=False),
                                                         encoding="utf-8")
    redondear = lambda d: {k: round(v, 6) if isinstance(v, float) else v for k, v in d.items()}  # noqa: E731
    manifiesto = {
        "model_version": args.version,
        "run_id": run_id,
        "run_name": nombre,
        "experimento": EXPERIMENTO,
        "algoritmo": run.data.params.get("algoritmo"),
        "dataset": {"archivo": info["archivo"], "version": info["version"], "sha256": info["sha256"]},
        "variables_entrada": {c: ESPECIFICACION[c] for c in ENTRADAS},
        "variables_derivadas": DERIVADAS,
        "clase_positiva": {"columna": "incumplimiento_90d", "valor": 1, "significado": "incumplió en 90 días"},
        "umbral": umbral,
        "regla_decision": "probabilidad >= umbral -> riesgo ALTO (desfavorable)",
        "costos_umbral": {"falso_negativo": COSTO_FN, "falso_positivo": COSTO_FP, "nota": "costos ficticios"},
        "seleccion": {"metrica": METRICA_SELECCION, "desempate": CRITERIO_DESEMPATE},
        "metricas": {"validacion": redondear({k: v for k, v in run.data.metrics.items() if k.startswith("val_")}
                                             | m_val | {"val_costo_esperado": costo_val}),
                     "prueba": redondear(m_test)},
        "dependencias": {"python": platform.python_version(), "scikit-learn": sklearn.__version__,
                         "pandas": pd.__version__, "numpy": np.__version__, "joblib": joblib.__version__},
        "artefacto": {"archivo": "modelo.joblib", "sha256": sha256_archivo(ruta_modelo)},
        "codigo_version": version_codigo(),
        "git_commit": commit_git(),
        "referencia_drift": referencia_drift(X_tr),
        "creado_at": datetime.now(timezone.utc).isoformat(),
    }
    (destino / "manifest.json").write_text(json.dumps(manifiesto, indent=2, ensure_ascii=False), encoding="utf-8")

    try:  # Registro de modelos de MLflow (extensión opcional): versión + alias por versión exportada
        mv = mlflow.register_model(f"runs:/{run_id}/modelo", NOMBRE_REGISTRO)
        client.set_registered_model_alias(NOMBRE_REGISTRO, f"exportado-{args.version}", mv.version)
        client.set_model_version_tag(NOMBRE_REGISTRO, mv.version, "umbral", f"{umbral:.2f}")
    except Exception as exc:  # noqa: BLE001
        print(f"Aviso: no se pudo registrar en el Model Registry: {exc}")

    # Informe de selección
    filas = [f"| {r.info.run_name} | {r.data.tags.get('familia')} | {r.data.metrics.get('val_average_precision', 0):.4f} | "
             f"{r.data.metrics.get('val_roc_auc', 0):.4f} | {r.data.metrics.get('val_f1_1', 0):.4f} | "
             f"{r.data.metrics.get('val_brier', 0):.4f} |" for r in ranking]
    informe = [
        f"# Informe de selección — modelo {args.version}",
        "",
        f"* **Ejecución seleccionada:** `{nombre}` (run `{run_id}`)"
        + (f" — restringido a la familia `{args.familia}`" if args.familia else ""),
        f"* **Métrica de selección (definida antes de comparar):** `{METRICA_SELECCION}` (average precision de la "
        "clase 1 en validación: resume precisión/recall sin depender del umbral y es sensible al desbalance).",
        f"* **Desempate:** {CRITERIO_DESEMPATE}.",
        f"* **Umbral:** {umbral:.2f}, elegido en validación minimizando el costo esperado con costos ficticios "
        f"FN={COSTO_FN:g} (aprobar a quien incumplirá) y FP={COSTO_FP:g} (rechazar a quien habría pagado). "
        "Se congeló antes de evaluar en prueba.",
        "",
        "## Ranking en validación (umbral de referencia 0,5 para precision/recall/F1)",
        "",
        "| Ejecución | Familia | AP | ROC-AUC | F1 clase 1 | Brier |",
        "|---|---|---|---|---|---|",
        *filas,
        "",
        "## Métricas finales en PRUEBA (una sola evaluación, umbral congelado)",
        "",
        "| Métrica | Valor |",
        "|---|---|",
        *[f"| {k} | {v:.4f} |" if isinstance(v, float) else f"| {k} | {v} |" for k, v in m_test.items()],
        "",
        "## Figuras",
        "",
        f"![curva de costo](figuras/{args.version}_curva_costo_val.png) "
        f"![confusión prueba](figuras/{args.version}_matriz_confusion_test.png) "
        f"![calibración](figuras/{args.version}_calibracion_test.png)",
        "",
        "> La probabilidad es una salida del modelo sobre datos sintéticos; no representa el riesgo real de personas.",
    ]
    (REPORTES / f"informe_seleccion_{args.version}.md").write_text("\n".join(informe) + "\n", encoding="utf-8")
    print(f"Exportado en {destino}")
    print(json.dumps({"umbral": umbral, **{k: round(v, 4) for k, v in m_test.items() if isinstance(v, float)}},
                     indent=2))


if __name__ == "__main__":
    main()
