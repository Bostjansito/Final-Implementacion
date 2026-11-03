import { useEffect, useState } from "react";
import { useAuth } from "../auth";
import { Alerta, Campo, Cargando, useDatos } from "../componentes";
import FormularioFinanciero, { CAMPOS_FINANCIEROS, aNumeros } from "./FormularioFinanciero";

const CLAVES_FINANCIERAS = [...CAMPOS_FINANCIEROS.map((c) => c.k), "tipo_empleo"];

export default function Perfil() {
  const { llamar, usuario } = useAuth();
  const { datos, error, cargando, recargar } = useDatos(async () => (await llamar("clientes", `/clientes/${usuario.cliente_id}`)).data, []);
  const [form, setForm] = useState(null);
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);
  const [guardando, setGuardando] = useState(false);
  useEffect(() => { if (datos) setForm(datos); }, [datos]);
  const cambiar = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  // El backend solo deja completar datos financieros vacíos; los ya registrados los cambia un administrador.
  const bloqueados = datos ? CLAVES_FINANCIERAS.filter((k) => datos[k] !== null && datos[k] !== undefined) : [];

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
      recargar(true);
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
        <FormularioFinanciero valores={form} onChange={cambiar} bloqueados={bloqueados} />
        {bloqueados.length > 0 && (
          <p className="nota">Los datos financieros ya registrados no se pueden editar desde aquí: son la base de la
            evaluación de riesgo. Si cambiaron, pide a un administrador que los actualice.</p>
        )}
        <Alerta tipo="exito">{msg}</Alerta>
        <Alerta tipo="error">{err}</Alerta>
        <button className="btn" disabled={guardando}>{guardando ? "Guardando…" : "Guardar cambios"}</button>
      </form>
    </section>
  );
}
