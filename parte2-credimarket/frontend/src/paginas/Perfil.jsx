import { useEffect, useState } from "react";
import { useAuth } from "../auth";
import { Alerta, Campo, Cargando, useDatos } from "../componentes";
import FormularioFinanciero, { aNumeros } from "./FormularioFinanciero";

export default function Perfil() {
  const { llamar, usuario } = useAuth();
  const { datos, error, cargando } = useDatos(async () => (await llamar("clientes", `/clientes/${usuario.cliente_id}`)).data, []);
  const [form, setForm] = useState(null);
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);
  const [guardando, setGuardando] = useState(false);
  useEffect(() => { if (datos) setForm(datos); }, [datos]);
  const cambiar = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  if (cargando) return <Cargando />;
  if (error) return <Alerta tipo="error">{error}</Alerta>;
  if (!form) return null;

  const guardar = async (e) => {
    e.preventDefault();
    setGuardando(true);
    setMsg(null);
    setErr(null);
    try {
      const { data } = await llamar("clientes", `/clientes/${usuario.cliente_id}`, {
        method: "PUT", body: { nombre: form.nombre, telefono: form.telefono || null, ...aNumeros(form) } });
      setForm(data);
      setMsg("Datos actualizados.");
    } catch (e2) {
      setErr(e2.message);
    } finally {
      setGuardando(false);
    }
  };

  return (
    <section className="tarjeta">
      <h1>Mi perfil</h1>
      <p className="nota">Código {form.codigo_externo} · Documento {form.documento || "—"} · {form.email}</p>
      <form onSubmit={guardar} className="formulario">
        <div className="rejilla-2">
          <Campo etiqueta="Nombre"><input required minLength={2} value={form.nombre || ""} onChange={(e) => cambiar("nombre", e.target.value)} /></Campo>
          <Campo etiqueta="Teléfono"><input value={form.telefono || ""} onChange={(e) => cambiar("telefono", e.target.value)} /></Campo>
        </div>
        <FormularioFinanciero valores={form} onChange={cambiar} />
        <Alerta tipo="exito">{msg}</Alerta>
        <Alerta tipo="error">{err}</Alerta>
        <button className="btn" disabled={guardando}>{guardando ? "Guardando…" : "Guardar cambios"}</button>
      </form>
    </section>
  );
}
