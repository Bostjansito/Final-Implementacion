// Cliente HTTP del frontend. El navegador SOLO habla con las APIs autorizadas
// (nunca con bases de datos, Redis, el broker ni el modelo).
const cfg = window.__CONFIG__ || {};

export const API = {
  productos: cfg.PRODUCTOS_API || "/api/productos",
  clientes: cfg.CLIENTES_API || "/api/clientes",
  prestamos: cfg.PRESTAMOS_API || "/api/prestamos",
  inventario: cfg.INVENTARIO_API || "/api/inventario",
};
export const ENLACES = { mlflow: cfg.MLFLOW_URL || "http://localhost:5000", rabbitmq: cfg.RABBITMQ_URL || "http://localhost:15672" };

const NOMBRES = { productos: "Productos", clientes: "Clientes", prestamos: "Préstamos", inventario: "Inventario" };

export class ApiError extends Error {
  constructor(status, message, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

function mensajeError(status, data, servicio) {
  const detalle = data && data.detail;
  if ([502, 503, 504].includes(status)) {
    return `El servicio ${NOMBRES[servicio]} no está disponible en este momento.` +
      (typeof detalle === "string" ? ` ${detalle}` : " Intente de nuevo en unos segundos.");
  }
  if (status === 422 && Array.isArray(detalle)) {
    return "Datos inválidos: " + detalle.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
  }
  if (detalle && typeof detalle === "object") {
    return detalle.mensaje ? `${detalle.mensaje}: ${(detalle.errores || []).join("; ")}` : JSON.stringify(detalle);
  }
  if (typeof detalle === "string") return detalle;
  return `Error ${status} en ${NOMBRES[servicio]}`;
}

export async function request(servicio, ruta, { method = "GET", body, token, headers = {}, form } = {}) {
  const h = { ...headers };
  if (token) h.Authorization = `Bearer ${token}`;
  let cuerpo;
  if (form) cuerpo = form;
  else if (body !== undefined) {
    h["Content-Type"] = "application/json";
    cuerpo = JSON.stringify(body);
  }
  let resp;
  try {
    resp = await fetch(API[servicio] + ruta, { method, headers: h, body: cuerpo });
  } catch {
    throw new ApiError(0, `No fue posible conectar con el servicio ${NOMBRES[servicio]}. Verifique su conexión e intente de nuevo.`);
  }
  const texto = await resp.text();
  let data = null;
  try {
    data = texto ? JSON.parse(texto) : null;
  } catch {
    data = texto;
  }
  if (!resp.ok) throw new ApiError(resp.status, mensajeError(resp.status, data, servicio), data);
  return { data, status: resp.status, headers: resp.headers };
}

export function nuevaClave() {
  if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
  return "k-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 12);
}
