import { Campo } from "../componentes";

// Campos financieros y laborales compartidos por el registro y el perfil.
export const CAMPOS_FINANCIEROS = [
  { k: "ingresos_mensuales_cop", e: "Ingresos mensuales (COP)", min: 1, max: 1000000000, entero: true, req: true },
  { k: "obligaciones_mensuales_cop", e: "Obligaciones mensuales (COP)", min: 0, max: 1000000000, entero: true, req: true },
  { k: "antiguedad_laboral_meses", e: "Antigüedad laboral (meses)", min: 0, max: 720 },
  { k: "meses_historial_crediticio", e: "Historial crediticio (meses)", min: 0, max: 720 },
  { k: "creditos_previos", e: "Créditos previos", min: 0, max: 200, entero: true, req: true },
  { k: "atrasos_previos_30d", e: "Atrasos previos > 30 días", min: 0, max: 200, entero: true, req: true },
  { k: "porcentaje_pago_puntual", e: "Pago puntual (%)", min: 0, max: 100, ayuda: "Vacío si no tiene historial" },
];

export function aNumeros(form) {
  const salida = {};
  for (const c of CAMPOS_FINANCIEROS) {
    const v = form[c.k];
    salida[c.k] = v === "" || v === null || v === undefined ? null : Number(v);
  }
  salida.tipo_empleo = form.tipo_empleo || null;
  return salida;
}

export default function FormularioFinanciero({ valores, onChange }) {
  return (
    <fieldset className="grupo">
      <legend>Información financiera y laboral</legend>
      <div className="rejilla-2">
        <Campo etiqueta="Tipo de empleo">
          <select value={valores.tipo_empleo || ""} onChange={(e) => onChange("tipo_empleo", e.target.value)}>
            <option value="">Sin especificar</option>
            <option value="dependiente">Dependiente</option>
            <option value="independiente">Independiente</option>
            <option value="temporal">Temporal</option>
          </select>
        </Campo>
        {CAMPOS_FINANCIEROS.map((c) => (
          <Campo key={c.k} etiqueta={c.e + (c.req ? " *" : "")} ayuda={c.ayuda}>
            <input type="number" min={c.min} max={c.max} step={c.entero ? 1 : "any"} required={c.req}
                   value={valores[c.k] ?? ""} onChange={(e) => onChange(c.k, e.target.value)} />
          </Campo>
        ))}
      </div>
    </fieldset>
  );
}
