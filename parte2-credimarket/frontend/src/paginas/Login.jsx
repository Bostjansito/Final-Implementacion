import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { Alerta, Campo } from "../componentes";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [enviando, setEnviando] = useState(false);

  const enviar = async (e) => {
    e.preventDefault();
    setEnviando(true);
    setError(null);
    try {
      const u = await login(email.trim(), password);
      navigate(u.rol === "ADMIN" ? "/admin/prestamos" : "/");
    } catch (err) {
      setError(err.message);
    } finally {
      setEnviando(false);
    }
  };

  return (
    <section className="tarjeta angosta">
      <h1>Iniciar sesión</h1>
      <form onSubmit={enviar} className="formulario">
        <Campo etiqueta="Correo">
          <input type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
        </Campo>
        <Campo etiqueta="Contraseña">
          <input type="password" required autoComplete="current-password" value={password}
                 onChange={(e) => setPassword(e.target.value)} />
        </Campo>
        <Alerta tipo="error">{error}</Alerta>
        <button className="btn" disabled={enviando}>{enviando ? "Ingresando…" : "Ingresar"}</button>
      </form>
      <p className="nota">¿No tienes cuenta? <Link to="/registro">Regístrate</Link>. Las cuentas de prueba están en
        <code> .secrets/cuentas-demo.txt</code> (ver la guía de demostración).</p>
    </section>
  );
}
