"""Promoción explícita y rollback del modelo activo.

    python promover.py --version v1 --motivo "modelo inicial"
    python promover.py --rollback --motivo "v2 aumenta rechazos"
    python promover.py --estado

La API de Préstamos lee registry/active.json al iniciar (o con POST /modelo/recargar):
nunca usa "el último archivo exportado".
"""
import argparse
import getpass
import json
from datetime import datetime, timezone

from comun import NOMBRE_REGISTRO, REGISTRY, sha256_archivo

ACTIVO = REGISTRY / "active.json"
HISTORIAL = REGISTRY / "historial_promociones.jsonl"


def verificar(version: str) -> dict:
    carpeta = REGISTRY / "models" / version
    manifiesto = json.loads((carpeta / "manifest.json").read_text(encoding="utf-8"))
    real = sha256_archivo(carpeta / manifiesto["artefacto"]["archivo"])
    if real != manifiesto["artefacto"]["sha256"]:
        raise SystemExit(f"El artefacto de {version} no coincide con su manifiesto (hash {real[:12]}…)")
    return manifiesto


def historial() -> list[dict]:
    if not HISTORIAL.exists():
        return []
    return [json.loads(linea) for linea in HISTORIAL.read_text(encoding="utf-8").splitlines() if linea.strip()]


def activar(version: str, motivo: str, accion: str) -> None:
    manifiesto = verificar(version)
    anterior = json.loads(ACTIVO.read_text(encoding="utf-8"))["model_version"] if ACTIVO.exists() else None
    registro = {"model_version": version, "run_id": manifiesto["run_id"], "umbral": manifiesto["umbral"],
                "accion": accion, "version_anterior": anterior, "motivo": motivo,
                "realizado_por": getpass.getuser(), "fecha": datetime.now(timezone.utc).isoformat()}
    ACTIVO.write_text(json.dumps({k: registro[k] for k in ("model_version", "run_id", "umbral", "motivo", "fecha")},
                                 indent=2), encoding="utf-8")
    with HISTORIAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    try:  # alias "activo" en el Model Registry de MLflow (opcional)
        from mlflow.tracking import MlflowClient
        client = MlflowClient()
        mv = client.get_model_version_by_alias(NOMBRE_REGISTRO, f"exportado-{version}")
        client.set_registered_model_alias(NOMBRE_REGISTRO, "activo", mv.version)
    except Exception as exc:  # noqa: BLE001
        print(f"Aviso: alias de MLflow no actualizado ({exc.__class__.__name__})")
    print(f"{accion}: {anterior} -> {version}. Reinicie Préstamos o llame POST /modelo/recargar.")


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--version")
    g.add_argument("--rollback", action="store_true")
    g.add_argument("--estado", action="store_true")
    ap.add_argument("--motivo", default="sin motivo")
    args = ap.parse_args()

    if args.estado:
        print(ACTIVO.read_text(encoding="utf-8") if ACTIVO.exists() else "Sin versión activa")
        for h in historial():
            print(f"{h['fecha']}  {h['accion']:10s} {h['version_anterior']} -> {h['model_version']}  ({h['motivo']})")
        return
    if args.rollback:
        actual = json.loads(ACTIVO.read_text(encoding="utf-8"))["model_version"]
        previas = [h["version_anterior"] for h in reversed(historial())
                   if h["model_version"] == actual and h["version_anterior"]]
        if not previas:
            raise SystemExit("No hay una versión anterior a la cual volver")
        activar(previas[0], args.motivo, "rollback")
    else:
        activar(args.version, args.motivo, "promocion")


if __name__ == "__main__":
    main()
