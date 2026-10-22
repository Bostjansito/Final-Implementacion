import { useState } from "react";
import { useAuth } from "../auth";
import { Alerta, Cargando, Estado, FINALES, cop, fecha, useDatos } from "../componentes";

export function Evaluacion({ p }) {
  const ev = p.evaluacion;
  if (!ev) return <span className="nota">Sin evaluación de riesgo</span>;
  return (
    <span>
      Riesgo <strong>{ev.decision_riesgo === "BAJO" ? "favorable" : "desfavorable"}</strong> (prob. {ev.probabilidad_incumplimiento.toFixed(3)},
      umbral {ev.umbral}) · modelo {ev.model_version}
    </span>
  );
}

export function mensajeEstado(p) {
  switch (p.estado) {
    case "EVALUANDO": return "Estamos evaluando tu solicitud.";
    case "PENDIENTE_INVENTARIO": return "Riesgo favorable. Decisión pendiente: estamos reservando el producto (aún no es una aprobación).";
    case "APROBADA": return "¡Aprobada! El producto está reservado para ti hasta la entrega.";
    case "COMPLETADA": return "Entregada. El préstamo quedó completado.";
    case "RECHAZADA": return "La solicitud fue rechazada.";
    case "CANCELADA_SIN_STOCK": return "Cancelada: no había existencias disponibles.";
    case "CANCELANDO": return "Cancelando: liberando la reserva del producto…";
    case "CANCELADA": return "Cancelada.";
    default: return p.estado;
  }
}

export default function DetallePrestamo({ prestamo, onCerrar, onCambio }) {
  const { llamar } = useAuth();
  const [error, setError] = useState(null);
  const [cancelando, setCancelando] = useState(false);
  const { datos: hist, cargando } = useDatos(
    async () => (await llamar("prestamos", `/prestamos/${prestamo.id}/historial`)).data, [prestamo.id, prestamo.estado]);

  const cancelar = async () => {
    if (!window.confirm("¿Cancelar esta solicitud? Se liberará la reserva del producto.")) return;
    setCancelando(true);
    setError(null);
    try {
      await llamar("prestamos", `/prestamos/${prestamo.id}/cancelar`, { method: "POST" });
      onCambio && onCambio();
    } catch (e) {
      setError(e.message);
    } finally {
      setCancelando(false);
    }
  };

  return (
    <div className="modal-fondo" onClick={onCerrar}>
      <div className="modal ancho" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h2>Solicitud {prestamo.id.slice(0, 8)} <Estado valor={prestamo.estado} /></h2>
        <p>{mensajeEstado(prestamo)}</p>
        {prestamo.motivo && <p className="nota">Motivo: {prestamo.motivo}</p>}
        <dl className="detalles">
          <dt>Producto</dt><dd>{prestamo.producto_nombre || prestamo.producto_id} × {prestamo.cantidad}</dd>
          <dt>Cotización usada</dt><dd>{cop(prestamo.precio_unitario)} (versión {prestamo.version_producto ?? "—"}, {fecha(prestamo.cotizado_at)})</dd>
          <dt>Monto</dt><dd>{cop(prestamo.monto)} a {prestamo.plazo_meses} meses · cuota {cop(prestamo.cuota_estimada)}</dd>
          <dt>Evaluación</dt><dd><Evaluacion p={prestamo} /></dd>
          {prestamo.reserva_expira_at && <><dt>Reserva vence</dt><dd>{fecha(prestamo.reserva_expira_at)}</dd></>}
          <dt>Clave de idempotencia</dt><dd><code>{prestamo.idempotency_key}</code></dd>
        </dl>
        <h3>Historial</h3>
        {cargando ? <Cargando /> : (
          <ol className="linea-tiempo">
            {(hist || []).map((h, i) => (
              <li key={i}><Estado valor={h.estado_nuevo} /> {fecha(h.fecha)} — {h.motivo} <small>({h.origen})</small></li>
            ))}
          </ol>
        )}
        <Alerta tipo="error">{error}</Alerta>
        <div className="acciones">
          {["PENDIENTE_INVENTARIO", "APROBADA"].includes(prestamo.estado) && (
            <button className="btn btn-peligro" onClick={cancelar} disabled={cancelando}>
              {cancelando ? "Cancelando…" : "Cancelar solicitud"}
            </button>
          )}
          <button className="btn btn-secundario" onClick={onCerrar}>Cerrar</button>
        </div>
        {!FINALES.includes(prestamo.estado) && <p className="nota">Esta vista se actualiza automáticamente.</p>}
      </div>
    </div>
  );
}
