import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { Alerta, Campo } from "../componentes";
import FormularioFinanciero, { aNumeros } from "./FormularioFinanciero";

export default function Registro() {
  const { registrar } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ nombre: "", documento: "", email: "", telefono: "", password: "" });
  const [error, setError] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const cambiar = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const enviar = async (e) => {
    e.preventDefault();
    if (form.password.length < 8) return setError("La contraseña debe tener al menos 8 caracteres.");
    setEnviando(true);
    setError(null);
    try {
      await registrar({ nombre: form.nombre.trim(), documento: form.documento.trim(), email: form.email.trim(),
        telefono: form.telefono.trim() || null, password: form.password, ...aNumeros(form) });
      navigate("/");
    } catch (err) {
      setError(err.message);
    } finally {
      setEnviando(false);
    }
  };

  return (
    <section className="tarjeta">
      <h1>Crear cuenta</h1>
      <form onSubmit={enviar} className="formulario">
        <div className="rejilla-2">
          <Campo etiqueta="Nombre completo *"><input required minLength={2} value={form.nombre} onChange={(e) => cambiar("nombre", e.target.value)} /></Campo>
          <Campo etiqueta="Documento *"><input required minLength={5} pattern="[0-9A-Za-z-]+" value={form.documento} onChange={(e) => cambiar("documento", e.target.value)} /></Campo>
          <Campo etiqueta="Correo *"><input type="email" required value={form.email} onChange={(e) => cambiar("email", e.target.value)} /></Campo>
          <Campo etiqueta="Teléfono"><input value={form.telefono} onChange={(e) => cambiar("telefono", e.target.value)} /></Campo>
          <Campo etiqueta="Contraseña *" ayuda="Mínimo 8 caracteres"><input type="password" required minLength={8} autoComplete="new-password" value={form.password} onChange={(e) => cambiar("password", e.target.value)} /></Campo>
        </div>
        <FormularioFinanciero valores={form} onChange={cambiar} />
        <Alerta tipo="error">{error}</Alerta>
        <button className="btn" disabled={enviando}>{enviando ? "Creando…" : "Crear cuenta"}</button>
      </form>
    </section>
  );
}
