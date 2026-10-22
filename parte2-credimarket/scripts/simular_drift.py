"""Simula drift: envía las solicitudes nuevas a /riesgo/predict, primero tal cual y luego con una
población desplazada (ingresos -45 %, obligaciones +60 %, más atrasos), y muestra el PSI de /modelo/monitoreo.

    python scripts/simular_drift.py
"""
import csv
import sys

from api import REPO, pedir, token_admin

sys.stdout.reconfigure(encoding="utf-8")
CAMPOS = ["ingresos_mensuales_cop", "obligaciones_mensuales_cop", "antiguedad_laboral_meses",
          "meses_historial_crediticio", "creditos_previos", "atrasos_previos_30d", "porcentaje_pago_puntual",
          "monto_solicitado_cop", "plazo_meses", "tipo_empleo"]
ENTEROS = {"ingresos_mensuales_cop", "obligaciones_mensuales_cop", "creditos_previos", "atrasos_previos_30d",
           "monto_solicitado_cop", "plazo_meses"}


def leer() -> list[dict]:
    filas = []
    with open(REPO / "data" / "solicitudes_nuevas.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = {}
            for c in CAMPOS:
                v = r[c].strip()
                d[c] = None if v == "" else (v if c == "tipo_empleo" else (int(float(v)) if c in ENTEROS else float(v)))
            filas.append(d)
    return filas


def enviar(admin: str, filas: list[dict]) -> tuple[int, int]:
    ok = altos = 0
    for f in filas:
        st, r, _ = pedir("POST", "prestamos", "/riesgo/predict", admin, f)
        if st == 200:
            ok += 1
            altos += r["decision_riesgo"] == "ALTO"
    return ok, altos


def monitoreo(admin: str, n: int) -> dict:
    return pedir("GET", "prestamos", f"/modelo/monitoreo?ultimas={n}", admin)[1]


def main() -> None:
    admin = token_admin()
    base = leer()
    ok, altos = enviar(admin, base)
    m = monitoreo(admin, ok)
    print(f"1) Población similar al entrenamiento: {ok} predicciones, riesgo alto {altos / ok:.0%}")
    print("   PSI:", m["psi"])
    desplazada = []
    for f in base:
        g = dict(f)
        g["ingresos_mensuales_cop"] = max(100_000, int(g["ingresos_mensuales_cop"] * 0.55))
        g["obligaciones_mensuales_cop"] = int(g["obligaciones_mensuales_cop"] * 1.6)
        g["atrasos_previos_30d"] = min(100, g["atrasos_previos_30d"] + 2)
        desplazada.append(g)
    ok2, altos2 = enviar(admin, desplazada)
    m2 = monitoreo(admin, ok2)
    print(f"2) Población desplazada: {ok2} predicciones, riesgo alto {altos2 / ok2:.0%}")
    print("   PSI:", m2["psi"])
    print("   Alertas:", *m2["alertas_drift"], sep="\n   - ")


if __name__ == "__main__":
    main()
