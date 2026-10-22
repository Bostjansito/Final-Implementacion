"""Genera data/clientes_demo.csv a partir de solicitudes_nuevas.csv (campos de cliente del histórico).

Incluye 4 filas inválidas a propósito para demostrar el reporte de errores por fila.
"""
import csv
import random
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NOMBRES = ["Andrés", "Beatriz", "Camilo", "Daniela", "Esteban", "Felipe", "Gabriela", "Héctor", "Isabel", "Julián",
           "Karen", "Luis", "Mariana", "Nicolás", "Olga", "Pablo", "Quintín", "Rosa", "Santiago", "Tatiana"]
APELLIDOS = ["Gómez", "Restrepo", "Zapata", "Vélez", "Mejía", "Ospina", "Arango", "Cardona", "Henao", "Londoño"]
CAMPOS = ["codigo_externo", "nombre", "documento", "email", "ingresos_mensuales_cop", "obligaciones_mensuales_cop",
          "tipo_empleo", "antiguedad_laboral_meses", "meses_historial_crediticio", "creditos_previos",
          "atrasos_previos_30d", "porcentaje_pago_puntual"]


def main() -> None:
    rnd = random.Random(7)
    filas = []
    with open(REPO / "data" / "solicitudes_nuevas.csv", encoding="utf-8") as f:
        for i, r in enumerate(csv.DictReader(f)):
            if i == 60:
                break
            nombre = f"{rnd.choice(NOMBRES)} {rnd.choice(APELLIDOS)}"
            filas.append({"codigo_externo": r["cliente_id"], "nombre": nombre,
                          "documento": str(1_020_000_000 + i * 7919),
                          "email": f"{r['cliente_id'].lower()}@correo.test",
                          **{c: r[c] for c in CAMPOS[4:]}})
    # Filas inválidas para el reporte de errores
    filas.append({**filas[0], "codigo_externo": "CLI-ERR-0001", "ingresos_mensuales_cop": "-100"})
    filas.append({**filas[1], "codigo_externo": "CLI-ERR-0002", "tipo_empleo": "astronauta"})
    filas.append({**filas[2], "codigo_externo": "CLI-ERR-0003", "ingresos_mensuales_cop": ""})
    filas.append({**filas[3]})  # código repetido dentro del mismo archivo
    with open(REPO / "data" / "clientes_demo.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(filas)
    print(f"{len(filas)} filas escritas en data/clientes_demo.csv (4 inválidas)")


if __name__ == "__main__":
    main()
