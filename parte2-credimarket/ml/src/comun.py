import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

ML_DIR = Path(__file__).resolve().parents[1]
REPO = ML_DIR.parent
sys.path.insert(0, str(ML_DIR))  # para importar credimarket_ml

from credimarket_ml.variables import ENTRADAS, ETIQUETA, ID_COLUMNAS  # noqa: E402

DATASET = Path(os.environ.get("DATASET", REPO / "data" / "prestamos_entrenamiento.csv"))
NUEVAS = Path(os.environ.get("DATASET_NUEVAS", REPO / "data" / "solicitudes_nuevas.csv"))
ARTEFACTOS = ML_DIR / "artefactos"
PARTICIONES = ARTEFACTOS / "particiones"
REGISTRY = ML_DIR / "registry"
REPORTES = ML_DIR / "reportes"
FIGURAS = REPORTES / "figuras"

SEMILLA = 42
ESTRATEGIA_PARTICION = "estratificada por incumplimiento_90d, 60/20/20, semilla 42, un registro por cliente"
EXPERIMENTO = "credimarket-riesgo-incumplimiento"
NOMBRE_REGISTRO = "credimarket-riesgo"
METRICA_SELECCION = "val_average_precision"
CRITERIO_DESEMPATE = ("si |ΔAP| < 0.005 se consideran empatados; entre ellos, los que estén a < 0.005 del mayor "
                      "val_roc_auc; si persiste: menor complejidad (logreg < arbol < hgb < rf); si persiste: "
                      "menor val_brier (mejor calibración)")
COMPLEJIDAD = {"baseline": 0, "logreg": 1, "arbol": 2, "hgb": 3, "rf": 4}

# Costos ficticios para elegir el umbral (no son recomendaciones financieras).
COSTO_FN = 3.0  # aprobar a quien incumplirá (falso negativo de la clase 1)
COSTO_FP = 1.0  # rechazar a quien habría pagado (falso positivo de la clase 1)


def sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def version_codigo() -> str:
    """Hash del código de entrenamiento y del paquete del modelo (identifica la versión del código)."""
    h = hashlib.sha256()
    for carpeta in (ML_DIR / "src", ML_DIR / "credimarket_ml"):
        for archivo in sorted(carpeta.glob("*.py")):
            h.update(archivo.name.encode())
            h.update(archivo.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


def commit_git() -> str:
    if os.environ.get("GIT_COMMIT"):
        return os.environ["GIT_COMMIT"]
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:  # noqa: BLE001
        return "sin-git"


def info_dataset() -> dict:
    return json.loads((ARTEFACTOS / "datos_version.json").read_text(encoding="utf-8"))


def cargar_dataset() -> pd.DataFrame:
    return pd.read_csv(DATASET)


def cargar_particiones() -> dict[str, tuple[pd.DataFrame, pd.Series]]:
    df = cargar_dataset().set_index("solicitud_id")
    info = info_dataset()
    if sha256_archivo(DATASET) != info["sha256"]:
        raise SystemExit("El dataset cambió desde que se generaron las particiones: ejecute preparar_datos.py")
    salida = {}
    for nombre in ("train", "val", "test"):
        ids = pd.read_csv(PARTICIONES / f"{nombre}_ids.csv")["solicitud_id"]
        parte = df.loc[ids]
        salida[nombre] = (parte[ENTRADAS].copy(), parte[ETIQUETA].astype(int))
    return salida


__all__ = ["ENTRADAS", "ETIQUETA", "ID_COLUMNAS"]
