import { useState } from "react";
import { useAuth } from "../../auth";
import { Alerta, Cargando, cop, fecha, useDatos } from "../../componentes";

export default function AdminClientes() {
  const { llamar } = useAuth();
  const [buscar, setBuscar] = useState("");
  const [pagina, setPagina] = useState(1);
  const { datos, error, cargando, recargar } = useDatos(
    async () => (await llamar("clientes", `/clientes?pagina=${pagina}&tamano=20${buscar ? `&buscar=${encodeURIComponent(buscar)}` : ""}`)).data,
    [llamar, pagina, buscar]);
  const { datos: historial, recargar: recargarHist } = useDatos(async () => (await llamar("clientes", "/clientes/importaciones")).data, [llamar]);
  const [archivo, setArchivo] = useState(null);
  const [resumen, setResumen] = useState(null);
  const [err, setErr] = useState(null);
  const [importando, setImportando] = useState(false);

  const importar = async (e) => {
    e.preventDefault();
    if (!archivo) return;
    setImportando(true);
    setErr(null);
    setResumen(null);
    try {
      const form = new FormData();
      form.append("archivo", archivo);
      const { data } = await llamar("clientes", "/clientes/importar", { method: "POST", form });
      setResumen(data);
      recargar(true);
      recargarHist(true);
    } catch (e2) {
      setErr(e2.message);
    } finally {
      setImportando(false);
    }
  };

  const cambiarActivo = async (c) => {
    try {
      await llamar("clientes", `/clientes/${c.id}`, { method: "PUT", body: { activo: !c.activo } });
      recargar(true);
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const total = datos ? Math.max(1, Math.ceil(datos.total / datos.tamano)) : 1;

  return (
    <section>
      <h1>Clientes</h1>
      <div className="tarjeta">
        <h2>Importación masiva (CSV)</h2>
        <p className="nota">Clave externa única: <code>codigo_externo</code> (también se acepta <code>cliente_id</code> del histórico).
          Importar dos veces el mismo archivo no duplica clientes. Ejemplo: <code>data/clientes_demo.csv</code>.</p>
        <form onSubmit={importar} className="acciones">
          <input type="file" accept=".csv,text/csv" onChange={(e) => setArchivo(e.target.files[0])} />
          <button className="btn" disabled={!archivo || importando}>{importando ? "Importando…" : "Importar"}</button>
        </form>
        <Alerta tipo="error" onCerrar={() => setErr(null)}>{err}</Alerta>
        {resumen && (
          <div>
            <Alerta tipo="exito">Filas {resumen.filas} · Insertados {resumen.insertados} · Actualizados {resumen.actualizados} ·
              Sin cambios {resumen.sin_cambios} · Rechazados {resumen.rechazados}</Alerta>
            {resumen.errores.length > 0 && (
              <div className="tabla-scroll">
                <table>
                  <thead><tr><th>Fila</th><th>Código</th><th>Error</th></tr></thead>
                  <tbody>{resumen.errores.map((x, i) => <tr key={i}><td>{x.fila}</td><td>{x.codigo_externo || "—"}</td><td>{x.error}</td></tr>)}</tbody>
                </table>
              </div>
            )}
          </div>
        )}
        {historial && historial.length > 0 && (
          <details>
            <summary>Historial de importaciones ({historial.length})</summary>
            <div className="tabla-scroll">
              <table>
                <thead><tr><th>Fecha</th><th>Archivo</th><th>SHA-256</th><th>Ins.</th><th>Act.</th><th>Sin cambios</th><th>Rech.</th><th>Por</th></tr></thead>
                <tbody>{historial.map((h) => (
                  <tr key={h.id}><td>{fecha(h.creado_at)}</td><td>{h.archivo}</td><td><code>{h.sha256.slice(0, 12)}</code></td>
                    <td>{h.insertados}</td><td>{h.actualizados}</td><td>{h.sin_cambios}</td><td>{h.rechazados}</td><td>{h.realizada_por}</td></tr>))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </div>

      <div className="encabezado">
        <h2>Listado ({datos ? datos.total : "…"})</h2>
        <input placeholder="Buscar por nombre, código, correo o documento" value={buscar}
               onChange={(e) => { setBuscar(e.target.value); setPagina(1); }} />
      </div>
      {cargando && !datos && <Cargando />}
      {error && <Alerta tipo="error">{error}</Alerta>}
      <div className="tabla-scroll">
        <table>
          <thead><tr><th>Código</th><th>Nombre</th><th>Correo</th><th>Ingresos</th><th>Obligaciones</th><th>Empleo</th><th>Origen</th><th>Estado</th><th></th></tr></thead>
          <tbody>
            {(datos ? datos.items : []).map((c) => (
              <tr key={c.id} className={c.activo ? "" : "inactivo"}>
                <td>{c.codigo_externo}</td><td>{c.nombre}</td><td>{c.email || "—"}</td><td>{cop(c.ingresos_mensuales_cop)}</td>
                <td>{cop(c.obligaciones_mensuales_cop)}</td><td>{c.tipo_empleo || "—"}</td><td>{c.origen}</td>
                <td>{c.activo ? "Activo" : "Inactivo"}</td>
                <td><button className="btn btn-pequeno btn-secundario" onClick={() => cambiarActivo(c)}>{c.activo ? "Desactivar" : "Activar"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="acciones paginacion">
        <button className="btn btn-secundario btn-pequeno" disabled={pagina <= 1} onClick={() => setPagina(pagina - 1)}>Anterior</button>
        <span>Página {pagina} de {total}</span>
        <button className="btn btn-secundario btn-pequeno" disabled={pagina >= total} onClick={() => setPagina(pagina + 1)}>Siguiente</button>
      </div>
    </section>
  );
}
