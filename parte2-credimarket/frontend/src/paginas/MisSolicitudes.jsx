import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { useAuth } from "../auth";
import { Alerta, Cargando, Estado, FINALES, cop, fecha, useDatos } from "../componentes";
import DetallePrestamo, { Evaluacion, mensajeEstado } from "./DetallePrestamo";

const INTERVALO_MS = 3000;

export default function MisSolicitudes() {
  const { llamar } = useAuth();
  const location = useLocation();
  const { datos, error, cargando, recargar } = useDatos(async () => (await llamar("prestamos", "/prestamos")).data, [llamar]);
  const [abierto, setAbierto] = useState(location.state && location.state.creada);

  const hayPendientes = (datos || []).some((p) => !FINALES.includes(p.estado));
  // Actualización automática (polling) mientras haya solicitudes no finalizadas.
  useEffect(() => {
    if (!hayPendientes) return undefined;
    const t = setInterval(() => recargar(true), INTERVALO_MS);
    return () => clearInterval(t);
  }, [hayPendientes, recargar]);

  const seleccionado = (datos || []).find((p) => p.id === abierto);

  return (
    <section>
      <div className="encabezado">
        <h1>Mis solicitudes</h1>
        <button className="btn btn-secundario" onClick={() => recargar()}>Actualizar</button>
      </div>
      {location.state && location.state.creada && (
        <Alerta tipo="exito">Solicitud registrada con identificador <code>{location.state.creada}</code>. La decisión está pendiente; esta página se actualiza sola.</Alerta>
      )}
      {hayPendientes && <p className="nota">⟳ Actualización automática cada {INTERVALO_MS / 1000} s</p>}
      {cargando && !datos && <Cargando />}
      {error && <Alerta tipo="error">{error}</Alerta>}
      {datos && datos.length === 0 && <p>Aún no tienes solicitudes. Elige un producto en el catálogo.</p>}
      <div className="lista">
        {(datos || []).map((p) => (
          <article key={p.id} className="fila-tarjeta" onClick={() => setAbierto(p.id)}>
            <div>
              <strong>{p.producto_nombre || "Producto"}</strong> × {p.cantidad} · {cop(p.monto)} · {p.plazo_meses} meses
              <div className="nota">{fecha(p.creado_at)} · {mensajeEstado(p)}</div>
              <div className="nota"><Evaluacion p={p} /></div>
            </div>
            <Estado valor={p.estado} />
          </article>
        ))}
      </div>
      {seleccionado && <DetallePrestamo prestamo={seleccionado} onCerrar={() => setAbierto(null)} onCambio={() => recargar(true)} />}
    </section>
  );
}
