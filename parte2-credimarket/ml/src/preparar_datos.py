"""Etapa A: validar, versionar y particionar los datos + análisis exploratorio breve."""
import json
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402

from comun import (ARTEFACTOS, DATASET, ESTRATEGIA_PARTICION, ETIQUETA, FIGURAS, PARTICIONES,  # noqa: E402
                   REPORTES, SEMILLA, sha256_archivo)
from credimarket_ml.variables import (ENTRADAS_NUMERICAS, ESPECIFICACION, cuota_mensual)  # noqa: E402

TIPOS_ESPERADOS = {
    "solicitud_id": "object", "cliente_id": "object", "ingresos_mensuales_cop": "int",
    "obligaciones_mensuales_cop": "int", "tipo_empleo": "object", "antiguedad_laboral_meses": "float",
    "meses_historial_crediticio": "float", "creditos_previos": "int", "atrasos_previos_30d": "int",
    "porcentaje_pago_puntual": "float", "monto_solicitado_cop": "int", "plazo_meses": "int",
    "tasa_mensual_simulada": "float", "cuota_estimada_cop": "float", ETIQUETA: "int",
}


def validar(df: pd.DataFrame) -> dict:
    r: dict = {"filas": len(df), "columnas": list(df.columns)}
    faltan = set(TIPOS_ESPERADOS) - set(df.columns)
    r["columnas_faltantes"] = sorted(faltan)
    r["tipos"] = {}
    for col, esperado in TIPOS_ESPERADOS.items():
        if col in df:
            real = str(df[col].dtype)
            ok = (esperado == "object" and real in ("object", "str", "string")) or real.startswith(esperado)
            r["tipos"][col] = {"esperado": esperado, "real": real, "ok": bool(ok)}
    r["faltantes"] = {c: int(n) for c, n in df.isna().sum().items() if n}
    r["faltantes_pct"] = {c: round(n / len(df) * 100, 2) for c, n in r["faltantes"].items()}
    r["duplicados"] = {
        "solicitud_id": int(df["solicitud_id"].duplicated().sum()),
        "cliente_id": int(df["cliente_id"].duplicated().sum()),
        "filas_sin_ids": int(df.drop(columns=["solicitud_id", "cliente_id"]).duplicated().sum()),
    }
    fuera = {}
    for col, spec in ESPECIFICACION.items():
        serie = df[col].dropna()
        if "min" in spec:
            n = int(((serie < spec["min"]) | (serie > spec["max"])).sum())
        else:
            n = int((~serie.isin(spec["valores"])).sum())
        if n:
            fuera[col] = n
    r["fuera_de_rango"] = fuera
    r["clases"] = {str(k): int(v) for k, v in df[ETIQUETA].value_counts().sort_index().items()}
    r["tasa_incumplimiento"] = round(float(df[ETIQUETA].mean()), 4)
    r["columnas_constantes"] = [c for c in df.columns if df[c].nunique(dropna=False) == 1]
    dif = (df["cuota_estimada_cop"] - cuota_mensual(df["monto_solicitado_cop"], df["plazo_meses"])).abs()
    r["cuota_redundante"] = {"max_diferencia_cop": round(float(dif.max()), 4),
                             "conclusion": "cuota_estimada_cop = f(monto, plazo, tasa constante)"}
    r["valido"] = (not faltan and not any(r["duplicados"].values()) and not fuera
                   and set(r["clases"]) == {"0", "1"})
    return r


def eda(df: pd.DataFrame) -> list[str]:
    FIGURAS.mkdir(parents=True, exist_ok=True)
    figuras = []

    fig, ax = plt.subplots(figsize=(4, 3))
    df[ETIQUETA].value_counts().sort_index().plot.bar(ax=ax, color=["#4C78A8", "#E45756"])
    ax.set_title("Distribución de clases")
    ax.set_xticklabels(["0: pagó", "1: incumplió"], rotation=0)
    fig.tight_layout()
    fig.savefig(FIGURAS / "eda_clases.png", dpi=110)
    plt.close(fig)
    figuras.append("eda_clases.png")

    fig, axes = plt.subplots(3, 3, figsize=(12, 9))
    for ax, col in zip(axes.ravel(), ENTRADAS_NUMERICAS):
        for clase, color in ((0, "#4C78A8"), (1, "#E45756")):
            datos = df.loc[df[ETIQUETA] == clase, col].dropna()
            ax.hist(datos.clip(upper=datos.quantile(0.99)), bins=30, alpha=0.55, color=color,
                    density=True, label=str(clase))
        ax.set_title(col, fontsize=9)
    axes.ravel()[0].legend(title="incumplió")
    fig.tight_layout()
    fig.savefig(FIGURAS / "eda_distribuciones.png", dpi=110)
    plt.close(fig)
    figuras.append("eda_distribuciones.png")

    fig, ax = plt.subplots(figsize=(5, 3))
    df.assign(tipo=df["tipo_empleo"].fillna("(faltante)")).groupby("tipo")[ETIQUETA].mean().plot.bar(ax=ax)
    ax.set_title("Tasa de incumplimiento por tipo de empleo")
    fig.tight_layout()
    fig.savefig(FIGURAS / "eda_tipo_empleo.png", dpi=110)
    plt.close(fig)
    figuras.append("eda_tipo_empleo.png")
    return figuras


def main() -> None:
    df = pd.read_csv(DATASET)
    sha = sha256_archivo(DATASET)
    validacion = validar(df)
    REPORTES.mkdir(parents=True, exist_ok=True)
    (REPORTES / "validacion_datos.json").write_text(json.dumps(validacion, indent=2, ensure_ascii=False),
                                                    encoding="utf-8")
    if not validacion["valido"]:
        raise SystemExit(f"Los datos no pasaron la validación: {validacion}")

    # Partición 60/20/20 estratificada con semilla fija. Cada cliente aparece una sola vez
    # en el archivo (verificado arriba), así que ningún cliente queda en dos particiones.
    ids, y = df["solicitud_id"], df[ETIQUETA]
    ids_tmp, ids_test, y_tmp, _ = train_test_split(ids, y, test_size=0.20, stratify=y, random_state=SEMILLA)
    ids_train, ids_val, _, _ = train_test_split(ids_tmp, y_tmp, test_size=0.25, stratify=y_tmp,
                                                random_state=SEMILLA)
    PARTICIONES.mkdir(parents=True, exist_ok=True)
    resumen_part = {}
    for nombre, parte in (("train", ids_train), ("val", ids_val), ("test", ids_test)):
        parte.sort_values().to_frame().to_csv(PARTICIONES / f"{nombre}_ids.csv", index=False)
        tasa = float(df.set_index("solicitud_id").loc[parte, ETIQUETA].mean())
        resumen_part[nombre] = {"filas": len(parte), "tasa_incumplimiento": round(tasa, 4)}
    clientes = [set(df.set_index("solicitud_id").loc[p, "cliente_id"]) for p in (ids_train, ids_val, ids_test)]
    assert not (clientes[0] & clientes[1] or clientes[0] & clientes[2] or clientes[1] & clientes[2])

    info = {
        "archivo": DATASET.name, "sha256": sha, "version": f"prestamos_entrenamiento@{sha[:12]}",
        "filas": len(df), "columnas": len(df.columns), "estrategia_particion": ESTRATEGIA_PARTICION,
        "particiones": resumen_part, "generado_at": datetime.now(timezone.utc).isoformat(),
    }
    ARTEFACTOS.mkdir(parents=True, exist_ok=True)
    (ARTEFACTOS / "datos_version.json").write_text(json.dumps(info, indent=2), encoding="utf-8")

    figuras = eda(df)
    desc = df[ENTRADAS_NUMERICAS].describe().T.round(2)
    lineas = [
        "# Análisis exploratorio y validación de datos",
        "",
        f"* **Archivo:** `{DATASET.name}` — **SHA-256:** `{sha}`",
        f"* **Filas:** {len(df):,} — **Columnas:** {len(df.columns)}",
        f"* **Tasa de incumplimiento (clase 1):** {validacion['tasa_incumplimiento']:.2%} "
        "(desbalance moderado: no se selecciona por accuracy)",
        f"* **Duplicados:** {validacion['duplicados']}",
        f"* **Valores fuera de rango:** {validacion['fuera_de_rango'] or 'ninguno'}",
        f"* **Columnas constantes:** {validacion['columnas_constantes']} → se excluyen.",
        f"* **Cuota redundante:** diferencia máxima con la fórmula = "
        f"{validacion['cuota_redundante']['max_diferencia_cop']} COP → se excluye como entrada "
        "y se recalcula en el pipeline.",
        "",
        "## Faltantes",
        "",
        "| Columna | Faltantes | % | Tratamiento |",
        "|---|---|---|---|",
    ]
    tratamiento = {
        "porcentaje_pago_puntual": "mediana + indicador (faltante = sin historial previo, es informativo)",
        "tipo_empleo": "categoría 'desconocido'",
    }
    for col, n in validacion["faltantes"].items():
        lineas.append(f"| {col} | {n} | {validacion['faltantes_pct'][col]} | "
                      f"{tratamiento.get(col, 'mediana + indicador')} |")
    lineas += ["", "## Particiones", "", "| Partición | Filas | Tasa de incumplimiento |", "|---|---|---|"]
    for nombre, v in resumen_part.items():
        lineas.append(f"| {nombre} | {v['filas']} | {v['tasa_incumplimiento']:.2%} |")
    lineas += ["", "## Estadísticas descriptivas", "", desc.to_markdown(), "", "## Figuras", ""]
    lineas += [f"![{f}](figuras/{f})" for f in figuras]
    (REPORTES / "eda.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
