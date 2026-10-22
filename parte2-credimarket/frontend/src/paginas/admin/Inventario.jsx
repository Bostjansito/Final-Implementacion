import { useState } from "react";
import { useAuth } from "../../auth";
import { Alerta, Campo, Cargando, Estado, fecha, useDatos } from "../../componentes";

export default function AdminInventario() {
  const { llamar } = useAuth();
  const [estadoReserva, setEstadoReserva] = useState("ACTIVA");
  const { datos: productos } = useDatos(async () => (await llamar("productos", "/productos?incluir_inactivos=true")).data, [llamar]);
  const { datos: existencias, error, cargando, recargar } = useDatos(async () => (await llamar("inventario", "/inventario/existencias")).data, [llamar]);
  const { datos: reservas, recargar: recargarReservas } = useDatos(
    async () => (await llamar("inventario", `/inventario/reservas?limite=100${estadoReserva ? `&estado=${estadoReserva}` : ""}`)).data,
    [llamar, estadoReserva]);
  const { datos: movimientos, recargar: recargarMov } = useDatos(async () => (await llamar("inventario", "/inventario/movimientos?limite=50")).data, [llamar]);
  const [entrada, setEntrada] = useState({ producto_id: "", cantidad: 1, nota: "" });
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);
  const [ocupado, setOcupado] = useState(false);

  const nombre = (id) => (productos || []).find((p) => p.id === id)?.nombre || id.slice(0, 8);
  const todo = () => { recargar(true); recargarReservas(true); recargarMov(true); };

  const ejecutar = async (accion, exito) => {
    setOcupado(true);
    setErr(null);
    setMsg(null);
    try {
      await accion();
      setMsg(exito);
      // Los cambios en Préstamos llegan por mensajería: se refresca de nuevo tras un momento.
      todo();
      setTimeout(todo, 2500);
    } catch (e) {
      setErr(e.message);
    } finally {
      setOcupado(false);
    }
  };

  const registrar = (e) => {
    e.preventDefault();
    ejecutar(() => llamar("inventario", "/inventario/entradas", { method: "POST",
      body: { producto_id: entrada.producto_id, cantidad: Number(entrada.cantidad), nota: entrada.nota || null } }),
    "Entrada registrada.");
  };

  return (
    <section>
      <div className="encabezado">
        <h1>Inventario</h1>
        <button className="btn btn-secundario" onClick={todo}>Actualizar</button>
      </div>
      <Alerta tipo="exito" onCerrar={() => setMsg(null)}>{msg}</Alerta>
      <Alerta tipo="error" onCerrar={() => setErr(null)}>{err}</Alerta>

      <div className="tarjeta">
        <h2>Registrar entrada</h2>
        <form onSubmit={registrar} className="rejilla-3 formulario">
          <Campo etiqueta="Producto">
            <select required value={entrada.producto_id} onChange={(e) => setEntrada({ ...entrada, producto_id: e.target.value })}>
              <option value="">Seleccione…</option>
              {(productos || []).map((p) => <option key={p.id} value={p.id}>{p.nombre} ({p.sku})</option>)}
            </select>
          </Campo>
          <Campo etiqueta="Cantidad"><input type="number" min={1} max={10000} required value={entrada.cantidad} onChange={(e) => setEntrada({ ...entrada, cantidad: e.target.value })} /></Campo>
          <Campo etiqueta="Nota"><input value={entrada.nota} onChange={(e) => setEntrada({ ...entrada, nota: e.target.value })} /></Campo>
          <button className="btn" disabled={ocupado}>Registrar entrada</button>
        </form>
      </div>

      <h2>Existencias</h2>
      {cargando && !existencias && <Cargando />}
      {error && <Alerta tipo="error">{error}</Alerta>}
      <div className="tabla-scroll">
        <table>
          <thead><tr><th>Producto</th><th>Disponible</th><th>Reservado</th><th>Actualizado</th></tr></thead>
          <tbody>{(existencias || []).map((e) => (
            <tr key={e.producto_id}><td>{nombre(e.producto_id)}</td><td>{e.disponible}</td><td>{e.reservado}</td><td>{fecha(e.actualizado_at)}</td></tr>))}
          </tbody>
        </table>
      </div>

      <div className="encabezado">
        <h2>Reservas</h2>
        <select value={estadoReserva} onChange={(e) => setEstadoReserva(e.target.value)}>
          <option value="">Todas</option>
          {["ACTIVA", "CONFIRMADA", "LIBERADA", "VENCIDA", "RECHAZADA"].map((s) => <option key={s}>{s}</option>)}
        </select>
      </div>
      <div className="tabla-scroll">
        <table>
          <thead><tr><th>Préstamo</th><th>Producto</th><th>Cant.</th><th>Estado</th><th>Vence</th><th>Motivo</th><th>Acciones</th></tr></thead>
          <tbody>{(reservas || []).map((r) => (
            <tr key={r.id}>
              <td><code>{r.prestamo_id.slice(0, 8)}</code></td><td>{nombre(r.producto_id)}</td><td>{r.cantidad}</td>
              <td><Estado valor={r.estado} /></td><td>{fecha(r.expira_at)}</td><td>{r.motivo || "—"}</td>
              <td className="acciones">
                {r.estado === "ACTIVA" && <>
                  <button className="btn btn-pequeno" disabled={ocupado}
                          onClick={() => ejecutar(() => llamar("inventario", `/inventario/reservas/${r.id}/confirmar-salida`, { method: "POST" }),
                            "Entrega confirmada: Inventario publicó SalidaConfirmada.")}>Confirmar entrega</button>
                  <button className="btn btn-pequeno btn-peligro" disabled={ocupado}
                          onClick={() => ejecutar(() => llamar("prestamos", `/prestamos/${r.prestamo_id}/cancelar`, { method: "POST" }),
                            "Cancelación solicitada: Préstamos pidió liberar la reserva.")}>Cancelar préstamo</button>
                </>}
              </td>
            </tr>))}
          </tbody>
        </table>
      </div>

      <h2>Movimientos recientes</h2>
      <div className="tabla-scroll">
        <table>
          <thead><tr><th>Fecha</th><th>Producto</th><th>Tipo</th><th>Cantidad</th><th>Préstamo</th><th>Por</th><th>Nota</th></tr></thead>
          <tbody>{(movimientos || []).map((m) => (
            <tr key={m.id}><td>{fecha(m.creado_at)}</td><td>{nombre(m.producto_id)}</td><td>{m.tipo}</td><td>{m.cantidad}</td>
              <td>{m.prestamo_id ? <code>{m.prestamo_id.slice(0, 8)}</code> : "—"}</td><td>{m.realizado_por}</td><td>{m.nota || "—"}</td></tr>))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
