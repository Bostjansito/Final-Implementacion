import { useState } from "react";
import { useAuth } from "../../auth";
import { Alerta, Campo, Cargando, cop, fecha, useDatos } from "../../componentes";

const VACIO = { sku: "", nombre: "", categoria: "", precio: "", descripcion: "" };

export default function AdminProductos() {
  const { llamar } = useAuth();
  const { datos, error, cargando, recargar } = useDatos(
    async () => (await llamar("productos", "/productos?incluir_inactivos=true")).data, [llamar]);
  const { datos: cache, recargar: recargarCache } = useDatos(
    async () => (await llamar("productos", "/cache/estadisticas")).data, [llamar]);
  const [form, setForm] = useState(VACIO);
  const [editando, setEditando] = useState(null);
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);
  const [ocupado, setOcupado] = useState(false);
  const [consulta, setConsulta] = useState(null);

  const ejecutar = async (accion, exito) => {
    setOcupado(true);
    setMsg(null);
    setErr(null);
    try {
      await accion();
      setMsg(exito);
      recargar(true);
      recargarCache(true);
    } catch (e) {
      setErr(e.message);
    } finally {
      setOcupado(false);
    }
  };

  const guardar = (e) => {
    e.preventDefault();
    const cuerpo = { nombre: form.nombre, categoria: form.categoria, precio: Number(form.precio), descripcion: form.descripcion };
    if (editando) {
      ejecutar(() => llamar("productos", `/productos/${editando.id}`, { method: "PUT",
        body: { ...cuerpo, version_esperada: editando.version } }), "Producto actualizado (la caché se invalidó).");
    } else {
      ejecutar(() => llamar("productos", "/productos", { method: "POST", body: { ...cuerpo, sku: form.sku.toUpperCase() } }),
        "Producto creado.");
    }
    setEditando(null);
    setForm(VACIO);
  };

  const probarCache = async (p) => {
    const { data, headers } = await llamar("productos", `/productos/${p.id}`);
    setConsulta({ nombre: data.nombre, xcache: headers.get("X-Cache"), precio: data.precio, version: data.version });
    recargarCache(true);
  };

  return (
    <section>
      <h1>Productos</h1>
      <div className="tarjeta">
        <h2>{editando ? `Editar ${editando.sku}` : "Nuevo producto"}</h2>
        <form onSubmit={guardar} className="formulario">
          <div className="rejilla-3">
            {!editando && <Campo etiqueta="SKU *"><input required pattern="[A-Za-z0-9-]{3,40}" value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} /></Campo>}
            <Campo etiqueta="Nombre *"><input required minLength={2} value={form.nombre} onChange={(e) => setForm({ ...form, nombre: e.target.value })} /></Campo>
            <Campo etiqueta="Categoría *"><input required minLength={2} value={form.categoria} onChange={(e) => setForm({ ...form, categoria: e.target.value })} /></Campo>
            <Campo etiqueta="Precio (COP) *"><input type="number" min={1} required value={form.precio} onChange={(e) => setForm({ ...form, precio: e.target.value })} /></Campo>
          </div>
          <Campo etiqueta="Descripción"><textarea rows={2} value={form.descripcion} onChange={(e) => setForm({ ...form, descripcion: e.target.value })} /></Campo>
          <div className="acciones">
            <button className="btn" disabled={ocupado}>{editando ? "Guardar cambios" : "Crear producto"}</button>
            {editando && <button type="button" className="btn btn-secundario" onClick={() => { setEditando(null); setForm(VACIO); }}>Cancelar</button>}
          </div>
        </form>
      </div>
      <Alerta tipo="exito" onCerrar={() => setMsg(null)}>{msg}</Alerta>
      <Alerta tipo="error" onCerrar={() => setErr(null)}>{err}</Alerta>

      {cache && (
        <div className="tarjeta">
          <h2>Caché Redis (cache-aside)</h2>
          <p>Aciertos {cache.hits} · Fallos {cache.misses} · Tasa de aciertos {cache.tasa_aciertos ?? "—"} · Errores {cache.errores}
            · Omitidas {cache.omitidas} · Invalidaciones {cache.invalidaciones} · TTL detalle {cache.ttl_detalle_s} s ·
            Redis {cache.redis_disponible ? "disponible" : "NO disponible (respondiendo desde PostgreSQL)"}</p>
          {consulta && <Alerta>Consulta de “{consulta.nombre}”: <strong>X-Cache: {consulta.xcache}</strong> · {cop(consulta.precio)} (versión {consulta.version})</Alerta>}
          <div className="acciones">
            <button className="btn btn-secundario" onClick={() => recargarCache()}>Actualizar estadísticas</button>
            <button className="btn btn-secundario" onClick={() => ejecutar(() => llamar("productos", "/cache", { method: "DELETE" }), "Caché vaciada.")}>Vaciar caché</button>
          </div>
        </div>
      )}

      {cargando && !datos && <Cargando />}
      {error && <Alerta tipo="error">{error}</Alerta>}
      <div className="tabla-scroll">
        <table>
          <thead><tr><th>SKU</th><th>Nombre</th><th>Categoría</th><th>Precio</th><th>Versión</th><th>Estado</th><th>Actualizado</th><th>Acciones</th></tr></thead>
          <tbody>
            {(datos || []).map((p) => (
              <tr key={p.id} className={p.activo ? "" : "inactivo"}>
                <td>{p.sku}</td><td>{p.nombre}</td><td>{p.categoria}</td><td>{cop(p.precio)}</td><td>{p.version}</td>
                <td>{p.activo ? "Activo" : "Inactivo"}</td><td>{fecha(p.actualizado_at)}</td>
                <td className="acciones">
                  <button className="btn btn-pequeno" onClick={() => { setEditando(p); setForm({ ...VACIO, ...p, precio: String(p.precio) }); window.scrollTo(0, 0); }}>Editar</button>
                  <button className="btn btn-pequeno btn-secundario" onClick={() => probarCache(p)}>Consultar (caché)</button>
                  <button className={`btn btn-pequeno ${p.activo ? "btn-peligro" : ""}`} disabled={ocupado}
                          onClick={() => ejecutar(() => llamar("productos", `/productos/${p.id}/${p.activo ? "desactivar" : "activar"}`, { method: "POST" }),
                            p.activo ? "Producto desactivado." : "Producto activado.")}>
                    {p.activo ? "Desactivar" : "Activar"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
