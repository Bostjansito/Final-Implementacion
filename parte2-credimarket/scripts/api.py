"""Cliente HTTP mínimo (solo librería estándar) para los scripts de prueba y demostración."""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SECRETOS = REPO / ".secrets"
URL = {
    "productos": os.environ.get("PRODUCTOS_URL", "http://localhost:8001"),
    "clientes": os.environ.get("CLIENTES_URL", "http://localhost:8002"),
    "prestamos": os.environ.get("PRESTAMOS_URL", "http://localhost:8003"),
    "inventario": os.environ.get("INVENTARIO_URL", "http://localhost:8004"),
}
FINALES = {"RECHAZADA", "CANCELADA_SIN_STOCK", "COMPLETADA", "CANCELADA"}


def secreto(nombre: str) -> str:
    return (SECRETOS / nombre).read_text(encoding="utf-8").strip()


def pedir(metodo: str, servicio: str, ruta: str, token: str | None = None, cuerpo=None,
          cabeceras: dict | None = None, datos: bytes | None = None, timeout: float = 15):
    """Devuelve (status, json|texto, headers). No lanza excepción por códigos HTTP."""
    h = dict(cabeceras or {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    if cuerpo is not None:
        datos = json.dumps(cuerpo).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(URL[servicio] + ruta, data=datos, method=metodo, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            crudo, status, hdrs = r.read(), r.status, {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        crudo, status, hdrs = e.read(), e.code, {k.lower(): v for k, v in e.headers.items()}
    try:
        return status, json.loads(crudo), hdrs
    except json.JSONDecodeError:
        return status, crudo.decode(errors="replace"), hdrs


def login(email: str, password: str) -> str:
    st, r, _ = pedir("POST", "clientes", "/auth/login", cuerpo={"email": email, "password": password})
    assert st == 200, f"login {email}: {st} {r}"
    return r["access_token"]


def token_admin() -> str:
    return login("admin@credimarket.test", secreto("admin_password"))


def token_cliente(email: str) -> str:
    return login(email, secreto("demo_cliente_password"))


ANA, BRUNO, CARLA = "ana.bajo@credimarket.test", "bruno.alto@credimarket.test", "carla.otra@credimarket.test"


def clave() -> str:
    return f"demo-{uuid.uuid4()}"


def crear_producto(admin: str, precio: int, stock: int, nombre: str = "Producto de prueba") -> str:
    sku = f"TEST-{uuid.uuid4().hex[:10].upper()}"
    st, p, _ = pedir("POST", "productos", "/productos", admin,
                     {"sku": sku, "nombre": f"{nombre} {sku[-4:]}", "categoria": "pruebas", "precio": precio})
    assert st == 201, (st, p)
    if stock:
        st, r, _ = pedir("POST", "inventario", "/inventario/entradas", admin,
                         {"producto_id": p["id"], "cantidad": stock, "nota": "prueba automática"})
        assert st == 201, (st, r)
    return p["id"]


def solicitar(token: str, producto_id: str, cantidad: int = 1, plazo: int = 12, idem: str | None = None):
    return pedir("POST", "prestamos", "/prestamos", token,
                 {"producto_id": producto_id, "cantidad": cantidad, "plazo_meses": plazo},
                 cabeceras={"Idempotency-Key": idem or clave()})


def esperar_estado(token: str, prestamo_id: str, estados: set[str], timeout: float = 30) -> dict:
    fin = time.time() + timeout
    while True:
        st, p, _ = pedir("GET", "prestamos", f"/prestamos/{prestamo_id}", token)
        if st == 200 and p["estado"] in estados:
            return p
        if time.time() > fin:
            raise TimeoutError(f"{prestamo_id} sigue en {p.get('estado') if st == 200 else st}")
        time.sleep(0.5)


def existencias(admin: str, producto_id: str) -> dict:
    st, todas, _ = pedir("GET", "inventario", "/inventario/existencias", admin)
    return next((e for e in todas if e["producto_id"] == producto_id),
                {"producto_id": producto_id, "disponible": 0, "reservado": 0})


def compose(*args: str, check: bool = True, env: dict | None = None) -> str:
    entorno = {**os.environ, **(env or {})}
    r = subprocess.run(["docker", "compose", *args], cwd=REPO, capture_output=True, text=True, env=entorno)
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr)
    return r.stdout + r.stderr
