import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { request } from "./api";

const AuthContext = createContext(null);
const CLAVE = "credimarket.sesion";

function leerSesion() {
  try {
    const s = JSON.parse(sessionStorage.getItem(CLAVE));
    if (s && s.expira_en * 1000 > Date.now()) return s;
  } catch {
    /* sesión corrupta: se ignora */
  }
  return null;
}

export function AuthProvider({ children }) {
  const [sesion, setSesion] = useState(leerSesion);
  const [aviso, setAviso] = useState(null);

  const guardar = (s) => {
    if (s) sessionStorage.setItem(CLAVE, JSON.stringify(s));
    else sessionStorage.removeItem(CLAVE);
    setSesion(s);
  };

  const logout = useCallback((mensaje) => {
    guardar(null);
    setAviso(mensaje || null);
  }, []);

  // Cierre automático cuando el token vence.
  useEffect(() => {
    if (!sesion) return undefined;
    const ms = sesion.expira_en * 1000 - Date.now();
    const t = setTimeout(() => logout("Tu sesión expiró. Inicia sesión de nuevo."), Math.max(ms, 0));
    return () => clearTimeout(t);
  }, [sesion, logout]);

  const login = async (email, password) => {
    const { data } = await request("clientes", "/auth/login", { method: "POST", body: { email, password } });
    guardar({ token: data.access_token, expira_en: data.expira_en, usuario: data.usuario });
    setAviso(null);
    return data.usuario;
  };

  const registrar = async (datos) => {
    const { data } = await request("clientes", "/auth/registro", { method: "POST", body: datos });
    guardar({ token: data.access_token, expira_en: data.expira_en, usuario: data.usuario });
    return data.usuario;
  };

  // Llamada autenticada: si el backend responde 401, la sesión se considera vencida.
  const llamar = useCallback(async (servicio, ruta, opciones = {}) => {
    try {
      return await request(servicio, ruta, { ...opciones, token: sesion && sesion.token });
    } catch (e) {
      if (e.status === 401 && sesion) logout("Tu sesión expiró o no es válida. Inicia sesión de nuevo.");
      throw e;
    }
  }, [sesion, logout]);

  const valor = useMemo(() => ({
    sesion, usuario: sesion && sesion.usuario, esAdmin: sesion && sesion.usuario.rol === "ADMIN",
    esCliente: sesion && sesion.usuario.rol === "CLIENTE", login, registrar, logout, llamar, aviso, setAviso,
  }), [sesion, llamar, logout, aviso]);

  return <AuthContext.Provider value={valor}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
