import { useEffect, useState } from "react";
import { useAuth } from "../../auth";
import { Alerta, Cargando, Estado, FINALES, cop, fecha, useDatos } from "../../componentes";
import DetallePrestamo, { Evaluacion } from "../DetallePrestamo";

const ESTADOS = ["", "EVALUANDO", "PENDIENTE_INVENTARIO", "APROBADA", "COMPLETADA", "RECHAZADA", "CANCELADA_SIN_STOCK", "CANCELANDO", "CANCELADA"];

export default function AdminPrestamos() {
  const { llamar } = useAuth();
  const [estado, setEstado] = useState("");
  const { datos, error, cargando, recargar } = useDatos(
    async () => (await llamar("prestamos", `/prestamos?limite=200${estado ? `&estado=${estado}` : ""}`)).data, [llamar, estado]);
  const [abierto, setAbierto] = useState(null);

  const hayPendientes = (datos || []).some((p) => !FINALES.includes(p.estado));
  useEffect(() => {
    if (!hayPendientes) return undefined;
    const t = setInterval(() => recargar(true), 3000);
    return () => clearInterval(t);
  }, [hayPendientes, recargar]);

  const seleccionado = (datos || []).find((p) => p.id === abierto);

  return (
    <section>
      <div className="encabezado">
        <h1>Préstamos</h1>
        <select value={estado} onChange={(e) => setEstado(e.target.value)} aria-label="Estado">
          {ESTADOS.map((s) => <option key={s} value={s}>{s || "Todos los estados"}</option>)}
        </select>
      </div>
      {hayPendientes && <p className="nota">⟳ Actualización automática cada 3 s</p>}
      {cargando && !datos && <Cargando />}
      {error && <Alerta tipo="error">{error}</Alerta>}
      <div className="tabla-scroll">
        <table>
          <thead><tr><th>Fecha</th><th>Id</th><th>Producto</th><th>Monto</th><th>Evaluación</th><th>Estado</th><th>Motivo</th></tr></thead>
          <tbody>{(datos || []).map((p) => (
            <tr key={p.id} className="clicable" onClick={() => setAbierto(p.id)}>
              <td>{fecha(p.creado_at)}</td><td><code>{p.id.slice(0, 8)}</code></td>
              <td>{p.producto_nombre || "—"} × {p.cantidad}</td><td>{cop(p.monto)}</td>
              <td><Evaluacion p={p} /></td><td><Estado valor={p.estado} /></td><td className="nota">{p.motivo}</td>
            </tr>))}
          </tbody>
        </table>
      </div>
      {seleccionado && <DetallePrestamo prestamo={seleccionado} onCerrar={() => setAbierto(null)} onCambio={() => recargar(true)} />}
    </section>
  );
}
