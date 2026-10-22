"""Mide el efecto de la caché Redis en GET /productos/{id} (p50, p95, tasa de aciertos y recursos).

    python scripts/medir_redis.py [--peticiones 2000] [--hilos 8]

Escenarios:
  A. Sin caché efectiva: se vacía Redis antes de CADA petición (siempre MISS -> PostgreSQL).
  B. Caché caliente: el producto ya está en Redis (HIT).
  C. Carga mixta: 6 productos al azar con caché inicialmente vacía (tasa de aciertos real).
  D. Redis caído: cada petición se responde desde PostgreSQL (BYPASS).
Escribe scripts/resultados/redis-<fecha>.md
"""
import argparse
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from api import REPO, compose, pedir, token_admin

sys.stdout.reconfigure(encoding="utf-8")


def percentil(valores, p):
    v = sorted(valores)
    return v[min(len(v) - 1, int(round(p / 100 * (len(v) - 1))))]


def medir(ids, n, hilos, antes=None):
    tiempos, estados, errores = [], {}, 0

    def una(_):
        nonlocal errores
        if antes:
            antes()
        pid = random.choice(ids)
        t = time.perf_counter()
        st, _, h = pedir("GET", "productos", f"/productos/{pid}")
        ms = (time.perf_counter() - t) * 1000
        if st != 200:
            errores += 1
        return ms, h.get("x-cache")

    inicio = time.perf_counter()
    with ThreadPoolExecutor(hilos) as ex:
        for ms, estado in ex.map(una, range(n)):
            tiempos.append(ms)
            estados[estado] = estados.get(estado, 0) + 1
    duracion = time.perf_counter() - inicio
    aciertos = estados.get("HIT", 0) / n
    return {"n": n, "p50": percentil(tiempos, 50), "p95": percentil(tiempos, 95), "media": statistics.mean(tiempos),
            "rps": n / duracion, "aciertos": aciertos, "estados": estados, "errores": errores}


def recursos() -> str:
    return compose("exec", "-T", "redis", "sh", "-c",
                   'redis-cli -a "$(cat /run/secrets/redis_password)" --no-auth-warning INFO memory | grep used_memory_human')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--peticiones", type=int, default=2000)
    ap.add_argument("--hilos", type=int, default=8)
    a = ap.parse_args()
    admin = token_admin()
    ids = [p["id"] for p in pedir("GET", "productos", "/productos")[1]][:6]
    vaciar = lambda: pedir("DELETE", "productos", "/cache", admin)  # noqa: E731
    res = {}

    print("Latencia (1 hilo): A. siempre MISS / B. siempre HIT…")
    res["A. Latencia sin caché: MISS → PostgreSQL (1 hilo)"] = medir(ids[:1], a.peticiones // 4, 1, antes=vaciar)
    pedir("GET", "productos", f"/productos/{ids[0]}")
    res["B. Latencia con caché: HIT (1 hilo)"] = medir(ids[:1], a.peticiones // 4, 1)
    print(f"Rendimiento ({a.hilos} hilos): C. mixta con caché / D. Redis caído…")
    vaciar()
    res[f"C. Carga mixta, 6 productos, caché vacía al inicio ({a.hilos} hilos)"] = medir(ids, a.peticiones, a.hilos)
    memoria = recursos().strip()
    compose("stop", "redis")
    try:
        res[f"D. Redis caído: BYPASS → PostgreSQL ({a.hilos} hilos)"] = medir(ids, a.peticiones, a.hilos)
    finally:
        compose("start", "redis")
    stats = pedir("GET", "productos", "/cache/estadisticas", admin)[1]

    lineas = ["# Mediciones de la caché Redis", "", f"Fecha: {datetime.now().isoformat()}  ",
              f"Endpoint: `GET /productos/{{id}}` · hilos concurrentes: {a.hilos} · equipo local (Docker Desktop)", "",
              "| Escenario | Peticiones | p50 (ms) | p95 (ms) | Media (ms) | Peticiones/s | Tasa de aciertos | X-Cache | Errores |",
              "|---|---|---|---|---|---|---|---|---|"]
    for nombre, r in res.items():
        lineas.append(f"| {nombre} | {r['n']} | {r['p50']:.1f} | {r['p95']:.1f} | {r['media']:.1f} | {r['rps']:.0f} | "
                      f"{r['aciertos']:.1%} | {r['estados']} | {r['errores']} |")
    lineas += ["", f"* Memoria de Redis tras la carga: `{memoria}`",
               f"* Estadísticas acumuladas del servicio: {stats}", ""]
    print("\n".join(lineas))
    salida = REPO / "scripts" / "resultados"
    salida.mkdir(exist_ok=True)
    (salida / f"redis-{datetime.now():%Y%m%d-%H%M%S}.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
