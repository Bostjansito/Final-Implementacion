import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { nuevaClave, request } from "../api";
import { useAuth } from "../auth";
import { Alerta, Campo, Cargando, cop, useDatos } from "../componentes";

const PLAZOS = [6, 12, 18, 24, 36];
const TASA = 0.018;
const cuota = (monto, n) => (monto * TASA) / (1 - (1 + TASA) ** -n);

// La clave de idempotencia se conserva mientras la MISMA solicitud no tenga respuesta definitiva:
// reintentar (por error de red o servicio caído) reutiliza la clave y nunca crea un préstamo duplicado.
function claveDe(firma) {
  const k = `credimarket.idem.${firma}`;
  let v = sessionStorage.getItem(k);
  if (!v) {
    v = nuevaClave();
    sessionStorage.setItem(k, v);
  }
  return v;
}
const olvidarClave = (firma) => sessionStorage.removeItem(`credimarket.idem.${firma}`);

function Solicitud({ producto, onCerrar }) {
  const { llamar, esCliente, sesion } = useAuth();
  const navigate = useNavigate();
  const [cantidad, setCantidad] = useState(1);
  const [plazo, setPlazo] = useState(12);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState(null);
  const [puedeReintentar, setPuedeReintentar] = useState(false);
  const { datos: stock } = useDatos(async () => (await request("inventario", `/inventario/existencias/${producto.id}`)).data, [producto.id]);

  const monto = producto.precio * cantidad;
  const firma = `${producto.id}|${cantidad}|${plazo}`;

  const enviar = async (e) => {
    e.preventDefault();
    if (enviando) return; // evita doble envío
    setEnviando(true);
    setError(null);
    setPuedeReintentar(false);
    try {
      const { data } = await llamar("prestamos", "/prestamos", {
        method: "POST", body: { producto_id: producto.id, cantidad: Number(cantidad), plazo_meses: Number(plazo) },
        headers: { "Idempotency-Key": claveDe(firma) },
      });
      olvidarClave(firma);
      navigate("/mis-solicitudes", { state: { creada: data.id } });
    } catch (err) {
      setError(err.message);
      // 0 = sin conexión, 5xx = servicio no disponible: se puede reintentar con la misma clave.
      setPuedeReintentar(err.status === 0 || err.status >= 500);
      if (err.status === 409) olvidarClave(firma);
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div className="modal-fondo" onClick={onCerrar}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h2>{producto.nombre}</h2>
        <p>{producto.descripcion}</p>
        <p><strong>{cop(producto.precio)}</strong> · {producto.categoria} · versión de precio {producto.version}</p>
        <p className="nota">Disponibles: {stock ? stock.disponible : "…"} (la reserva real se hace al procesar la solicitud)</p>
        {!sesion && <Alerta>Para solicitar financiación <Link to="/login">inicia sesión</Link> como cliente.</Alerta>}
        {sesion && !esCliente && <Alerta>Las solicitudes las hacen los clientes; el administrador gestiona el catálogo.</Alerta>}
        {esCliente && (
          <form onSubmit={enviar} className="formulario">
            <div className="rejilla-2">
              <Campo etiqueta="Cantidad">
                <input type="number" min={1} max={5} required value={cantidad} disabled={enviando}
                       onChange={(e) => setCantidad(Math.max(1, Math.min(5, Number(e.target.value) || 1)))} />
              </Campo>
              <Campo etiqueta="Plazo (meses)">
                <select value={plazo} disabled={enviando} onChange={(e) => setPlazo(Number(e.target.value))}>
                  {PLAZOS.map((p) => <option key={p} value={p}>{p}</option>)}
                </select>
              </Campo>
            </div>
            <p>Monto estimado: <strong>{cop(monto)}</strong> · Cuota estimada: <strong>{cop(cuota(monto, plazo))}</strong>/mes</p>
            <p className="nota">El monto definitivo lo calcula el servicio de Préstamos con la cotización vigente.
              La decisión queda <strong>pendiente</strong> hasta evaluar el riesgo y reservar el inventario.</p>
            <Alerta tipo="error">{error}</Alerta>
            <div className="acciones">
              <button className="btn" disabled={enviando}>
                {enviando ? "Enviando…" : puedeReintentar ? "Reintentar (misma solicitud)" : "Solicitar financiación"}
              </button>
              <button type="button" className="btn btn-secundario" onClick={onCerrar}>Cerrar</button>
            </div>
          </form>
        )}
        {!esCliente && <button className="btn btn-secundario" onClick={onCerrar}>Cerrar</button>}
      </div>
    </div>
  );
}

export default function Catalogo() {
  const { datos, error, cargando, recargar } = useDatos(async () => (await request("productos", "/productos")).data, []);
  const [elegido, setElegido] = useState(null);
  const [filtro, setFiltro] = useState("");
  const [errorDetalle, setErrorDetalle] = useState(null);

  const elegir = async (id) => {
    // El detalle pasa por la caché Redis del servicio Productos (cache-aside).
    setErrorDetalle(null);
    try {
      const { data } = await request("productos", `/productos/${id}`);
      setElegido(data);
    } catch (e) {
      setErrorDetalle(e.message);
    }
  };

  const productos = (datos || []).filter((p) => !filtro || p.categoria === filtro);
  const categorias = [...new Set((datos || []).map((p) => p.categoria))];

  return (
    <section>
      <div className="encabezado">
        <h1>Catálogo</h1>
        <select value={filtro} onChange={(e) => setFiltro(e.target.value)} aria-label="Categoría">
          <option value="">Todas las categorías</option>
          {categorias.map((c) => <option key={c}>{c}</option>)}
        </select>
      </div>
      {cargando && <Cargando />}
      {error && <Alerta tipo="error">{error} <button className="btn-link" onClick={() => recargar()}>Reintentar</button></Alerta>}
      <Alerta tipo="error" onCerrar={() => setErrorDetalle(null)}>{errorDetalle}</Alerta>
      <div className="rejilla-productos">
        {productos.map((p) => (
          <article key={p.id} className="producto">
            <span className="categoria">{p.categoria}</span>
            <h3>{p.nombre}</h3>
            <p className="precio">{cop(p.precio)}</p>
            <p className="nota">{p.descripcion}</p>
            <button className="btn" onClick={() => elegir(p.id)}>Ver y financiar</button>
          </article>
        ))}
      </div>
      {datos && productos.length === 0 && <p>No hay productos activos.</p>}
      {elegido && <Solicitud producto={elegido} onCerrar={() => setElegido(null)} />}
    </section>
  );
}
