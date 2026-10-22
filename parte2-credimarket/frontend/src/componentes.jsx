import { useCallback, useEffect, useRef, useState } from "react";

export const cop = (n) => (n === null || n === undefined ? "—" : new Intl.NumberFormat("es-CO", {
  style: "currency", currency: "COP", maximumFractionDigits: 0 }).format(n));

export const fecha = (iso) => (iso ? new Date(iso).toLocaleString("es-CO") : "—");

export function Alerta({ tipo = "info", children, onCerrar }) {
  if (!children) return null;
  return (
    <div className={`alerta alerta-${tipo}`} role={tipo === "error" ? "alert" : "status"}>
      <span>{children}</span>
      {onCerrar && <button className="btn-link" onClick={onCerrar} aria-label="Cerrar">×</button>}
    </div>
  );
}

export function Cargando({ texto = "Cargando…" }) {
  return <div className="cargando"><span className="spinner" aria-hidden="true" /> {texto}</div>;
}

const COLORES = {
  EVALUANDO: "gris", PENDIENTE_INVENTARIO: "amarillo", APROBADA: "verde", COMPLETADA: "azul",
  RECHAZADA: "rojo", CANCELADA_SIN_STOCK: "rojo", CANCELANDO: "amarillo", CANCELADA: "gris",
  ACTIVA: "verde", CONFIRMADA: "azul", LIBERADA: "gris", VENCIDA: "rojo",
};
const TEXTOS = {
  EVALUANDO: "Evaluando", PENDIENTE_INVENTARIO: "Pendiente de inventario", APROBADA: "Aprobada",
  COMPLETADA: "Entregada", RECHAZADA: "Rechazada", CANCELADA_SIN_STOCK: "Cancelada sin stock",
  CANCELANDO: "Cancelando", CANCELADA: "Cancelada",
};

export function Estado({ valor }) {
  return <span className={`badge badge-${COLORES[valor] || "gris"}`}>{TEXTOS[valor] || valor}</span>;
}

export const FINALES = ["RECHAZADA", "CANCELADA_SIN_STOCK", "COMPLETADA", "CANCELADA"];

// Carga datos y permite recargarlos; maneja estado de carga y error.
export function useDatos(cargar, deps = []) {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState(null);
  const [cargando, setCargando] = useState(true);
  const montado = useRef(true);
  const recargar = useCallback(async (silencioso = false) => {
    if (!silencioso) setCargando(true);
    try {
      const d = await cargar();
      if (montado.current) {
        setDatos(d);
        setError(null);
      }
    } catch (e) {
      if (montado.current) setError(e.message);
    } finally {
      if (montado.current) setCargando(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    montado.current = true;
    recargar();
    return () => { montado.current = false; };
  }, [recargar]);
  return { datos, error, cargando, recargar, setDatos };
}

export function Campo({ etiqueta, ayuda, children }) {
  return (
    <label className="campo">
      <span className="campo-etiqueta">{etiqueta}</span>
      {children}
      {ayuda && <small className="campo-ayuda">{ayuda}</small>}
    </label>
  );
}
