import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.calibration import calibration_curve  # noqa: E402
from sklearn.metrics import (ConfusionMatrixDisplay, accuracy_score, average_precision_score,  # noqa: E402
                             brier_score_loss, confusion_matrix, f1_score, precision_score, recall_score,
                             roc_auc_score)


def calcular(y, proba, umbral: float, prefijo: str) -> dict:
    pred = (proba >= umbral).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {
        f"{prefijo}_precision_1": precision_score(y, pred, zero_division=0),
        f"{prefijo}_recall_1": recall_score(y, pred, zero_division=0),
        f"{prefijo}_f1_1": f1_score(y, pred, zero_division=0),
        f"{prefijo}_roc_auc": roc_auc_score(y, proba),
        f"{prefijo}_average_precision": average_precision_score(y, proba),
        f"{prefijo}_brier": brier_score_loss(y, proba),
        f"{prefijo}_accuracy": accuracy_score(y, pred),
        f"{prefijo}_tn": int(tn), f"{prefijo}_fp": int(fp), f"{prefijo}_fn": int(fn), f"{prefijo}_tp": int(tp),
    }


def figura_confusion(y, proba, umbral: float, titulo: str, ruta) -> None:
    fig, ax = plt.subplots(figsize=(4, 3.6))
    ConfusionMatrixDisplay.from_predictions(y, (proba >= umbral).astype(int), labels=[0, 1],
                                            display_labels=["0 pagó", "1 incumplió"], ax=ax, colorbar=False)
    ax.set_title(titulo, fontsize=9)
    fig.tight_layout()
    fig.savefig(ruta, dpi=110)
    plt.close(fig)


def figura_calibracion(y, proba, titulo: str, ruta) -> None:
    frac, media = calibration_curve(y, proba, n_bins=10, strategy="quantile")
    fig, ax = plt.subplots(figsize=(4, 3.6))
    ax.plot([0, 1], [0, 1], "--", color="gray", label="calibración perfecta")
    ax.plot(media, frac, "o-", label="modelo")
    ax.set_xlabel("probabilidad predicha")
    ax.set_ylabel("fracción observada de incumplimiento")
    ax.set_title(titulo, fontsize=9)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(ruta, dpi=110)
    plt.close(fig)


def curva_costo(y, proba, costo_fn: float, costo_fp: float):
    umbrales = np.round(np.arange(0.05, 0.951, 0.01), 2)
    costos = []
    for u in umbrales:
        pred = (proba >= u).astype(int)
        fn = int(((pred == 0) & (y == 1)).sum())
        fp = int(((pred == 1) & (y == 0)).sum())
        costos.append((costo_fn * fn + costo_fp * fp) / len(y))
    return umbrales, np.array(costos)
