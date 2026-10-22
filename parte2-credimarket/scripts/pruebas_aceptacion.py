"""Pruebas de aceptación de la sección 12 del enunciado, contra el sistema levantado con docker compose.

    python scripts/pruebas_aceptacion.py            # todos los casos (incluye caídas de servicios)
    python scripts/pruebas_aceptacion.py 1 4 5      # solo algunos casos
    python scripts/pruebas_aceptacion.py --rapido   # omite los casos que detienen contenedores (6, 8b, 11)

Solo usa la librería estándar de Python. Los casos 14 a 16 (frontend) se demuestran desde el
navegador siguiendo docs/guia-demo.md.
"""
import base64
import json
import sys
import threading
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

from api import (ANA, BRUNO, CARLA, FINALES, REPO, clave, compose, crear_producto, esperar_estado, existencias,
                 pedir, secreto, solicitar, token_admin, token_cliente)

sys.stdout.reconfigure(encoding="utf-8")
RESULTADOS: list[tuple[str, bool, str]] = []
ADMIN = token_admin()
T_ANA, T_BRUNO, T_CARLA = token_cliente(ANA), token_cliente(BRUNO), token_cliente(CARLA)


def caso(numero: str, titulo: str):
    def deco(f):
        def envoltura():
            print(f"\n=== Caso {numero}: {titulo}")
            try:
                detalle = f() or ""
                RESULTADOS.append((f"{numero}. {titulo}", True, detalle))
                print(f"    OK  {detalle}")
            except Exception as exc:  # noqa: BLE001
                RESULTADOS.append((f"{numero}. {titulo}", False, f"{type(exc).__name__}: {exc}"))
                print(f"    FALLA  {type(exc).__name__}: {exc}")
        envoltura.numero = numero
        return envoltura
    return deco


def verificar(condicion: bool, mensaje: str) -> None:
    if not condicion:
        raise AssertionError(mensaje)


# ------------------------------------------------------------------ utilidades de infraestructura
def rabbit(metodo: str, ruta: str, cuerpo=None):
    auth = base64.b64encode(f"credimarket:{secreto('rabbitmq_password')}".encode()).decode()
    req = urllib.request.Request(f"http://localhost:15672/api{ruta}", method=metodo,
                                 data=json.dumps(cuerpo).encode() if cuerpo else None,
                                 headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read() or b"null")


def publicar(exchange: str, routing_key: str, mensaje: dict) -> bool:
    r = rabbit("POST", f"/exchanges/%2F/{exchange}/publish", {
        "properties": {"message_id": mensaje["event_id"], "type": mensaje["type"], "delivery_mode": 2,
                       "content_type": "application/json"},
        "routing_key": routing_key, "payload": json.dumps(mensaje), "payload_encoding": "string"})
    return r["routed"]


def esperar_cola(nombre: str, condicion, timeout: float = 20) -> bool:
    """Las estadísticas de la API de administración se refrescan cada ~5 s."""
    fin = time.time() + timeout
    while time.time() < fin:
        if condicion(rabbit("GET", f"/queues/%2F/{nombre}").get("messages", 0)):
            return True
        time.sleep(1)
    return False


def sql(bd: str, consulta: str) -> str:
    return compose("exec", "-T", "postgres", "psql", "-U", "postgres", "-d", bd, "-At", "-c", consulta).strip()


def mensaje_outbox(bd: str, prestamo_id: str, tipo: str) -> dict:
    fila = sql(bd, f"select mensaje from outbox where mensaje->>'prestamo_id'='{prestamo_id}' "
                   f"and tipo='{tipo}' order by id limit 1")
    return json.loads(fila)


def esperar_servicio(url: str, timeout: float = 90) -> None:
    fin = time.time() + timeout
    while time.time() < fin:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except Exception:  # noqa: BLE001
            time.sleep(1)
    raise TimeoutError(url)


# ------------------------------------------------------------------ casos
@caso("1", "Riesgo favorable con existencias: reserva, aprobación y entrega")
def caso1():
    prod = crear_producto(ADMIN, 2_000_000, 2)
    st, p, h = solicitar(T_ANA, prod, plazo=12)
    verificar(st == 202 and p["estado"] == "PENDIENTE_INVENTARIO", f"esperaba 202 PENDIENTE: {st} {p}")
    verificar(p["evaluacion"]["decision_riesgo"] == "BAJO", "riesgo debía ser BAJO")
    verificar(p["precio_unitario"] == 2_000_000 and p["monto"] == 2_000_000, "monto debe salir de la cotización")
    p = esperar_estado(T_ANA, p["id"], {"APROBADA"})
    e = existencias(ADMIN, prod)
    verificar(e["disponible"] == 1 and e["reservado"] == 1, f"existencias tras reservar: {e}")
    st, r, _ = pedir("POST", "inventario", f"/inventario/reservas/{p['reserva_id']}/confirmar-salida", ADMIN)
    verificar(st == 200 and r["estado"] == "CONFIRMADA", f"confirmar salida: {st} {r}")
    p = esperar_estado(T_ANA, p["id"], {"COMPLETADA"})
    e = existencias(ADMIN, prod)
    verificar(e["disponible"] == 1 and e["reservado"] == 0, f"existencias tras entrega: {e}")
    return f"préstamo {p['id'][:8]} PENDIENTE→APROBADA→COMPLETADA; existencias {e['disponible']}/{e['reservado']}"


@caso("2", "Solicitud rechazada: decisión y versión registradas, sin reserva")
def caso2():
    prod = crear_producto(ADMIN, 1_500_000, 3)
    st, p, _ = solicitar(T_BRUNO, prod)
    verificar(st == 201 and p["estado"] == "RECHAZADA", f"esperaba 201 RECHAZADA: {st} {p}")
    ev = p["evaluacion"]
    verificar(ev and ev["model_version"] and ev["decision_riesgo"] == "ALTO", f"evaluación: {ev}")
    time.sleep(2)
    st, reservas, _ = pedir("GET", "inventario", f"/inventario/reservas?prestamo_id={p['id']}", ADMIN)
    verificar(reservas == [], f"no debía existir reserva: {reservas}")
    verificar(existencias(ADMIN, prod)["reservado"] == 0, "no debía reservarse inventario")
    return f"prob={ev['probabilidad_incumplimiento']:.3f} umbral={ev['umbral']} modelo={ev['model_version']}"


@caso("3", "Riesgo favorable sin existencias: CANCELADA_SIN_STOCK y nunca inventario negativo")
def caso3():
    prod = crear_producto(ADMIN, 1_000_000, 0)
    st, p, _ = solicitar(T_ANA, prod)
    verificar(st == 202, f"{st} {p}")
    p = esperar_estado(T_ANA, p["id"], {"CANCELADA_SIN_STOCK"})
    e = existencias(ADMIN, prod)
    verificar(e["disponible"] == 0 and e["reservado"] == 0, f"existencias: {e}")
    return f"motivo: {p['motivo']}"


@caso("4", "Dos solicitudes simultáneas por la última unidad: solo una obtiene la reserva")
def caso4():
    prod = crear_producto(ADMIN, 3_000_000, 1, "Último computador")
    respuestas = {}

    def pedir_en_paralelo(nombre, token):
        respuestas[nombre] = solicitar(token, prod)

    hilos = [threading.Thread(target=pedir_en_paralelo, args=(n, t)) for n, t in (("ana", T_ANA), ("carla", T_CARLA))]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    finales = {}
    for nombre, token in (("ana", T_ANA), ("carla", T_CARLA)):
        st, p, _ = respuestas[nombre]
        verificar(st == 202, f"{nombre}: {st} {p}")
        finales[nombre] = esperar_estado(token, p["id"], {"APROBADA", "CANCELADA_SIN_STOCK"})["estado"]
    verificar(sorted(finales.values()) == ["APROBADA", "CANCELADA_SIN_STOCK"], f"resultado: {finales}")
    e = existencias(ADMIN, prod)
    verificar(e["disponible"] == 0 and e["reservado"] == 1, f"existencias: {e}")
    return f"{finales}; existencias disponible=0 reservado=1"


@caso("5", "Misma petición y mismo evento repetidos: un préstamo y un único efecto en inventario")
def caso5():
    prod = crear_producto(ADMIN, 1_200_000, 5)
    k = clave()
    respuestas = []
    hilos = [threading.Thread(target=lambda: respuestas.append(solicitar(T_ANA, prod, idem=k))) for _ in range(5)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    ids = {r[1]["id"] for r in respuestas if r[0] in (200, 201, 202)}
    verificar(len(ids) == 1, f"5 peticiones con la misma clave generaron {len(ids)} préstamos: {[r[0] for r in respuestas]}")
    pid = ids.pop()
    st, r, _ = solicitar(T_ANA, prod, cantidad=2, idem=k)
    verificar(st == 409, f"misma clave + contenido distinto debía dar 409, dio {st}")
    esperar_estado(T_ANA, pid, {"APROBADA"})
    verificar(existencias(ADMIN, prod)["reservado"] == 1, "debía reservarse exactamente 1 unidad")

    # Reentrega del MISMO comando (mismo event_id) y de un comando repetido con event_id nuevo.
    original = mensaje_outbox("prestamos_db", pid, "ReservaSolicitada")
    verificar(publicar("credimarket.comandos", "inventario.reservar", original), "no se enrutó")
    verificar(publicar("credimarket.comandos", "inventario.reservar", original), "no se enrutó")
    nuevo = {**original, "event_id": str(uuid.uuid4())}
    verificar(publicar("credimarket.comandos", "inventario.reservar", nuevo), "no se enrutó")
    # Reentrega del evento InventarioReservado a Préstamos
    evento = mensaje_outbox("inventario_db", pid, "InventarioReservado")
    verificar(publicar("credimarket.eventos", "inventario.reservado", evento), "no se enrutó")
    time.sleep(4)
    e = existencias(ADMIN, prod)
    verificar(e["reservado"] == 1 and e["disponible"] == 4, f"el efecto se duplicó: {e}")
    n = sql("inventario_db", f"select count(*) from reservas where prestamo_id='{pid}'")
    verificar(n == "1", f"reservas para el préstamo: {n}")
    dup = sql("inventario_db", f"select resultado from mensajes_procesados where event_id='{original['event_id']}'")
    return f"1 préstamo, 409 con contenido distinto, 1 reserva; inbox del comando original: '{dup}'"


@caso("6", "Caída del consumidor y del broker: recuperación sin perder ni duplicar")
def caso6():
    prod = crear_producto(ADMIN, 900_000, 5)
    compose("stop", "inventario-worker")
    try:
        st, p1, _ = solicitar(T_ANA, prod)
        verificar(st == 202, f"{st} {p1}")
        time.sleep(3)
        verificar(esperar_estado(T_ANA, p1["id"], {"PENDIENTE_INVENTARIO"})["estado"] == "PENDIENTE_INVENTARIO",
                  "debía seguir pendiente")
        verificar(esperar_cola("inventario.comandos", lambda n: n >= 1), "el comando debía esperar en la cola")
    finally:
        compose("start", "inventario-worker")
    esperar_estado(T_ANA, p1["id"], {"APROBADA"}, timeout=60)

    compose("stop", "rabbitmq")
    try:
        st, p2, _ = solicitar(T_ANA, prod)
        verificar(st == 202, f"con el broker caído la API debe aceptar (outbox): {st} {p2}")
        pend = sql("prestamos_db", f"select count(*) from outbox where publicado_at is null "
                                   f"and mensaje->>'prestamo_id'='{p2['id']}'")
        verificar(pend == "1", f"el mensaje debía quedar en el outbox: {pend}")
    finally:
        compose("start", "rabbitmq")
    esperar_estado(T_ANA, p2["id"], {"APROBADA"}, timeout=120)
    e = existencias(ADMIN, prod)
    verificar(e["reservado"] == 2 and e["disponible"] == 3, f"existencias: {e}")
    return "worker caído: comando esperó en la cola; broker caído: mensaje esperó en el outbox; ambos APROBADA"


@caso("7", "Cancelación y evento tardío: reserva liberada y préstamo no reactivado")
def caso7():
    prod = crear_producto(ADMIN, 1_100_000, 3)
    compose("stop", "inventario-worker")
    try:
        st, p, _ = solicitar(T_ANA, prod)
        verificar(st == 202, f"{st} {p}")
        st, c, _ = pedir("POST", "prestamos", f"/prestamos/{p['id']}/cancelar", T_ANA)
        verificar(st == 200 and c["estado"] == "CANCELANDO", f"cancelar: {st} {c}")
    finally:
        compose("start", "inventario-worker")
    # Inventario procesa primero la reserva (evento tardío para Préstamos) y luego la liberación.
    final = esperar_estado(T_ANA, p["id"], {"CANCELADA"}, timeout=60)
    time.sleep(2)
    st, hist, _ = pedir("GET", "prestamos", f"/prestamos/{p['id']}/historial", T_ANA)
    verificar("APROBADA" not in [x["estado_nuevo"] for x in hist], f"el evento tardío reactivó: {hist}")
    e = existencias(ADMIN, prod)
    verificar(e["disponible"] == 3 and e["reservado"] == 0, f"la reserva no se liberó: {e}")
    # Evento tardío explícito sobre un préstamo ya CANCELADO.
    tardio = {**mensaje_outbox("inventario_db", p["id"], "InventarioReservado"), "event_id": str(uuid.uuid4())}
    publicar("credimarket.eventos", "inventario.reservado", tardio)
    time.sleep(3)
    st, p2, _ = pedir("GET", "prestamos", f"/prestamos/{p['id']}", T_ANA)
    verificar(p2["estado"] == "CANCELADA", f"un evento tardío cambió el estado a {p2['estado']}")
    return f"historial: {' → '.join(x['estado_nuevo'] for x in hist)}; existencias restauradas"


@caso("8", "Redis: miss, hit, expiración, invalidación y caída")
def caso8():
    prod = crear_producto(ADMIN, 777_000, 0)
    estados = []
    for _ in range(2):
        st, _, h = pedir("GET", "productos", f"/productos/{prod}")
        estados.append(h.get("x-cache"))
    verificar(estados == ["MISS", "HIT"], f"esperaba MISS, HIT: {estados}")
    compose("exec", "-T", "redis", "sh", "-c",
            f'redis-cli -a "$(cat /run/secrets/redis_password)" --no-auth-warning EXPIRE productos:v1:{prod} 1')
    time.sleep(2)
    _, _, h = pedir("GET", "productos", f"/productos/{prod}")
    verificar(h.get("x-cache") == "MISS", f"tras expirar esperaba MISS: {h.get('X-Cache')}")
    if "--rapido" in sys.argv:
        return "miss→hit→expiración→miss (caída de Redis omitida en modo rápido)"
    compose("stop", "redis")
    try:
        inicio = time.perf_counter()
        st, p, h = pedir("GET", "productos", f"/productos/{prod}")
        ms = (time.perf_counter() - inicio) * 1000
        verificar(st == 200 and p["precio"] == 777_000, f"con Redis caído debía responder la BD: {st}")
        verificar(h.get("x-cache") == "BYPASS", f"X-Cache={h.get('X-Cache')}")
    finally:
        compose("start", "redis")
        fin = time.time() + 60
        while time.time() < fin and not pedir("GET", "productos", "/ready")[1].get("redis"):
            time.sleep(1)
        time.sleep(6)  # deja cerrar el circuito de la caché antes del siguiente caso
    return f"MISS→HIT→(expira)→MISS; Redis caído: 200 desde PostgreSQL en {ms:.0f} ms (BYPASS)"


@caso("9", "Precio modificado: invalidación de caché y monto con la cotización vigente")
def caso9():
    prod = crear_producto(ADMIN, 1_000_000, 5)
    pedir("GET", "productos", f"/productos/{prod}")
    _, _, h = pedir("GET", "productos", f"/productos/{prod}")
    verificar(h.get("x-cache") == "HIT", "debía estar en caché")
    st, p, _ = pedir("PUT", "productos", f"/productos/{prod}", ADMIN, {"precio": 1_350_000})
    verificar(st == 200 and p["version"] == 2, f"{st} {p}")
    st, p, h = pedir("GET", "productos", f"/productos/{prod}")
    verificar(h.get("x-cache") == "MISS" and p["precio"] == 1_350_000, f"caché no invalidada: {h.get('X-Cache')} {p}")
    st, pr, _ = solicitar(T_ANA, prod, cantidad=2)
    verificar(pr["precio_unitario"] == 1_350_000 and pr["version_producto"] == 2 and pr["monto"] == 2_700_000,
              f"el préstamo no usó la cotización vigente: {pr}")
    return "caché invalidada tras el cambio; préstamo con precio 1.350.000 (versión 2), monto 2.700.000"


@caso("10", "Modelo exportado vs. API: predicciones equivalentes y versión identificable")
def caso10():
    st, info, _ = pedir("GET", "prestamos", "/modelo/info")
    version = info["model_version"]
    print(compose("--profile", "ml", "run", "--rm", "ml-trainer", "python", "predecir_lote.py",
                  "--version", version).strip().splitlines()[-1])
    datos = json.loads((REPO / "ml" / "artefactos" / f"predicciones_locales_{version}.json").read_text())
    difs = []
    for fila in datos["predicciones"]:
        st, r, _ = pedir("POST", "prestamos", "/riesgo/predict", ADMIN, fila["entrada"])
        verificar(st == 200, f"{st} {r}")
        verificar(r["model_version"] == version, "versión distinta")
        difs.append(abs(r["probabilidad_incumplimiento"] - fila["probabilidad"]))
    verificar(max(difs) < 1e-5, f"diferencia máxima {max(difs)}")
    return f"{len(difs)} solicitudes nuevas; diferencia máxima {max(difs):.2e}; versión {version} run {info['run_id'][:8]}"


@caso("11", "Promoción y rollback entre dos versiones conservando trazabilidad")
def caso11():
    def promover(*args):
        compose("--profile", "ml", "run", "--rm", "ml-trainer", "python", "promover.py", *args)
        st, r, _ = pedir("POST", "prestamos", "/modelo/recargar", ADMIN)
        verificar(st == 200, f"recargar: {st} {r}")
        return r["version_activa"]

    inicial = pedir("GET", "prestamos", "/modelo/info")[1]["model_version"]
    otra = "v2" if inicial == "v1" else "v1"
    prod = crear_producto(ADMIN, 1_000_000, 5)
    verificar(promover("--version", otra, "--motivo", "prueba de aceptación 11") == otra, "no se promovió")
    _, p, _ = solicitar(T_CARLA, prod)
    verificar(p["evaluacion"]["model_version"] == otra, f"el préstamo no usó {otra}")
    verificar(promover("--rollback", "--motivo", "rollback de la prueba 11") == inicial, "rollback falló")
    _, p2, _ = solicitar(T_CARLA, prod)
    verificar(p2["evaluacion"]["model_version"] == inicial, "tras rollback no se usó la versión inicial")
    hist = (REPO / "ml" / "registry" / "historial_promociones.jsonl").read_text(encoding="utf-8").splitlines()
    return f"{inicial}→{otra}→{inicial}; préstamos evaluados con cada versión; {len(hist)} registros en el historial"


@caso("12", "Importar el mismo CSV dos veces no duplica clientes")
def caso12():
    archivo = REPO / "data" / "clientes_demo.csv"
    contenido = archivo.read_bytes()
    limite = "----credimarket" + uuid.uuid4().hex
    cuerpo = (f"--{limite}\r\nContent-Disposition: form-data; name=\"archivo\"; filename=\"{archivo.name}\"\r\n"
              f"Content-Type: text/csv\r\n\r\n").encode() + contenido + f"\r\n--{limite}--\r\n".encode()
    resultados = []
    for _ in range(2):
        st, r, _ = pedir("POST", "clientes", "/clientes/importar", ADMIN, datos=cuerpo,
                         cabeceras={"Content-Type": f"multipart/form-data; boundary={limite}"})
        verificar(st == 200, f"{st} {r}")
        resultados.append(r)
    segundo = resultados[1]
    verificar(segundo["insertados"] == 0 and segundo["actualizados"] == 0, f"segunda importación: {segundo}")
    total = sql("clientes_db", "select count(*) - count(distinct codigo_externo) from clientes")
    verificar(total == "0", "hay códigos externos duplicados")
    r1 = {k: v for k, v in resultados[0].items() if k != "errores"}
    return f"1ª: {r1}; 2ª: insertados=0, sin_cambios={segundo['sin_cambios']}, rechazados={segundo['rechazados']}"


@caso("13", "Un cliente intenta acceder a préstamos ajenos")
def caso13():
    prod = crear_producto(ADMIN, 1_000_000, 0)
    _, p, _ = solicitar(T_ANA, prod)
    st, r, _ = pedir("GET", "prestamos", f"/prestamos/{p['id']}", T_CARLA)
    verificar(st == 403, f"esperaba 403, obtuvo {st}")
    st2, _, _ = pedir("POST", "prestamos", f"/prestamos/{p['id']}/cancelar", T_CARLA)
    verificar(st2 == 403, f"cancelar ajeno: {st2}")
    _, lista, _ = pedir("GET", "prestamos", "/prestamos", T_CARLA)
    verificar(all(x["id"] != p["id"] for x in lista), "Carla ve préstamos de Ana en su lista")
    st3, _, _ = pedir("GET", "clientes", f"/clientes/{p['cliente_id']}", T_CARLA)
    verificar(st3 == 403, f"datos de otro cliente: {st3}")
    st4, _, _ = pedir("POST", "productos", "/productos", T_CARLA, {"sku": "X-1", "nombre": "x", "categoria": "x", "precio": 1})
    verificar(st4 == 403, f"cliente creando productos: {st4}")
    st5, _, _ = pedir("GET", "clientes", "/internal/clientes/" + p["cliente_id"], T_CARLA)
    verificar(st5 == 403, f"endpoint interno: {st5}")
    return "403 en consulta, cancelación, datos de cliente, administración y endpoint interno"


@caso("16", "Entradas inválidas y token inválido devuelven errores claros")
def caso16():
    st, r, _ = pedir("POST", "prestamos", "/prestamos", T_ANA, {"producto_id": "x", "cantidad": 0, "plazo_meses": 12},
                     cabeceras={"Idempotency-Key": clave()})
    verificar(st == 422, f"formulario inválido: {st}")
    st, r, _ = pedir("POST", "prestamos", "/prestamos", T_ANA,
                     {"producto_id": str(uuid.uuid4()), "cantidad": 1, "plazo_meses": 12, "precio": 1})
    verificar(st == 422, f"precio enviado por el cliente debe rechazarse: {st}")
    st, r, _ = pedir("POST", "prestamos", "/prestamos", T_ANA,
                     {"producto_id": str(uuid.uuid4()), "cantidad": 1, "plazo_meses": 12})
    verificar(st == 400, f"sin Idempotency-Key: {st}")
    st, r, _ = pedir("GET", "prestamos", "/prestamos", "token-invalido")
    verificar(st == 401, f"token inválido: {st}")
    st, r, _ = pedir("POST", "prestamos", "/riesgo/predict", ADMIN, {"ingresos_mensuales_cop": -5})
    verificar(st == 422, f"predict inválido: {st}")
    return "422 validación, 422 precio del cliente, 400 sin clave, 401 token, 422 predict"


@caso("VEN", "Una reserva vencida libera unidades y el préstamo aprobado pasa a CANCELADA")
def caso_vencimiento():
    prod = crear_producto(ADMIN, 1_000_000, 2)
    compose("up", "-d", "inventario-worker", env={"RESERVA_TTL_SEGUNDOS": "15"})
    try:
        time.sleep(5)
        st, p, _ = solicitar(T_ANA, prod)
        verificar(st == 202, f"{st} {p}")
        esperar_estado(T_ANA, p["id"], {"APROBADA"}, timeout=60)
        verificar(existencias(ADMIN, prod)["reservado"] == 1, "debía haber 1 unidad reservada")
        final = esperar_estado(T_ANA, p["id"], {"CANCELADA"}, timeout=90)
    finally:
        compose("up", "-d", "inventario-worker")  # restaura el TTL configurado
    verificar("RESERVA_VENCIDA" in final["motivo"], f"motivo: {final['motivo']}")
    e = existencias(ADMIN, prod)
    verificar(e["disponible"] == 2 and e["reservado"] == 0, f"existencias: {e}")
    return f"APROBADA → CANCELADA ({final['motivo']}); unidades devueltas"


@caso("DLQ", "Mensaje imposible de procesar termina en la dead letter")
def caso_dlq():
    antes = rabbit("GET", "/queues/%2F/inventario.comandos.dlq")["messages"]
    malo = {"event_id": str(uuid.uuid4()), "type": "ComandoDesconocido", "schema_version": 1,
            "occurred_at": datetime.now().isoformat(), "correlation_id": "prueba-dlq",
            "prestamo_id": str(uuid.uuid4()), "payload": {}}
    publicar("credimarket.comandos", "inventario.reservar", malo)
    verificar(esperar_cola("inventario.comandos.dlq", lambda n: n == antes + 1), "el mensaje no llegó a la DLQ")
    despues = rabbit("GET", "/queues/%2F/inventario.comandos.dlq")["messages"]
    return f"inventario.comandos.dlq: {antes} → {despues}"


CASOS = [caso1, caso2, caso3, caso4, caso5, caso6, caso7, caso8, caso9, caso10, caso11, caso12, caso13, caso16,
         caso_vencimiento, caso_dlq]
LENTOS = {"6", "11", "VEN"}

if __name__ == "__main__":
    elegidos = [a for a in sys.argv[1:] if not a.startswith("--")]
    for c in CASOS:
        if elegidos and c.numero not in elegidos:
            continue
        if "--rapido" in sys.argv and c.numero in LENTOS:
            continue
        c()
    print("\n================ RESUMEN")
    for nombre, ok, detalle in RESULTADOS:
        print(f"{'OK   ' if ok else 'FALLA'} {nombre}")
    salida = REPO / "scripts" / "resultados"
    salida.mkdir(exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d-%H%M%S")
    lineas = ["# Resultado de las pruebas de aceptación", "", f"Fecha: {datetime.now().isoformat()}", "",
              "| Caso | Resultado | Detalle |", "|---|---|---|"]
    lineas += [f"| {n} | {'✅' if ok else '❌'} | {d.replace('|', '/')} |" for n, ok, d in RESULTADOS]
    (salida / f"aceptacion-{marca}.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    sys.exit(0 if all(ok for _, ok, _ in RESULTADOS) else 1)
