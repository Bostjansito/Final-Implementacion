import { useState } from "react";
import { ENLACES } from "../../api";
import { useAuth } from "../../auth";
import { Alerta, Cargando, fecha, useDatos } from "../../componentes";

export default function AdminModelo() {
  const { llamar } = useAuth();
  const { datos: info, error, cargando, recargar } = useDatos(async () => (await llamar("prestamos", "/modelo/info")).data, [llamar]);
  const { datos: mon, recargar: recargarMon } = useDatos(async () => (await llamar("prestamos", "/modelo/monitoreo")).data, [llamar]);
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);

  const recargarModelo = async () => {
    setMsg(null);
    setErr(null);
    try {
      const { data } = await llamar("prestamos", "/modelo/recargar", { method: "POST" });
      setMsg(`Modelo recargado: ${data.version_anterior} → ${data.version_activa}`);
      recargar(true);
    } catch (e) {
      setErr(e.message);
    }
  };

  return (
    <section>
      <div className="encabezado">
        <h1>Modelo de riesgo</h1>
        <div className="acciones">
          <a className="btn btn-secundario" href={`${ENLACES.mlflow}/#/experiments`} target="_blank" rel="noreferrer">Abrir MLflow ↗</a>
          <a className="btn btn-secundario" href={ENLACES.rabbitmq} target="_blank" rel="noreferrer">Abrir RabbitMQ ↗</a>
        </div>
      </div>
      <Alerta tipo="exito" onCerrar={() => setMsg(null)}>{msg}</Alerta>
      <Alerta tipo="error" onCerrar={() => setErr(null)}>{err}</Alerta>
      {cargando && <Cargando />}
      {error && <Alerta tipo="error">{error}</Alerta>}
      {info && (
        <div className="tarjeta">
          <h2>Versión activa: {info.model_version}</h2>
          <dl className="detalles">
            <dt>Run ID (MLflow)</dt><dd><code>{info.run_id}</code> ({info.run_name})</dd>
            <dt>Algoritmo</dt><dd>{info.algoritmo}</dd>
            <dt>Umbral</dt><dd>{info.umbral} — {info.regla_decision}</dd>
            <dt>Clase positiva</dt><dd>{info.clase_positiva.columna} = {info.clase_positiva.valor} ({info.clase_positiva.significado})</dd>
            <dt>Dataset</dt><dd>{info.dataset.version}</dd>
            <dt>Variables de entrada</dt><dd>{Object.keys(info.variables_entrada).join(", ")}</dd>
            <dt>Variables derivadas</dt><dd>{info.variables_derivadas.join(", ")}</dd>
            <dt>Métricas en prueba</dt><dd>ROC-AUC {info.metricas_prueba.test_roc_auc} · AP {info.metricas_prueba.test_average_precision} ·
              Recall clase 1 {info.metricas_prueba.test_recall_1} · Precisión clase 1 {info.metricas_prueba.test_precision_1} · Brier {info.metricas_prueba.test_brier}</dd>
            <dt>Dependencias</dt><dd>{Object.entries(info.dependencias).map(([k, v]) => `${k} ${v}`).join(" · ")}</dd>
            <dt>Exportado</dt><dd>{fecha(info.creado_at)} · SHA-256 <code>{info.artefacto_sha256.slice(0, 16)}…</code></dd>
          </dl>
          <p className="nota">Para cambiar de versión: <code>docker compose --profile ml run --rm ml-trainer python promover.py --version v2</code> (o <code>--rollback</code>) y luego “Recargar modelo”.</p>
          <button className="btn" onClick={recargarModelo}>Recargar modelo activo</button>
        </div>
      )}
      {mon && (
        <div className="tarjeta">
          <div className="encabezado"><h2>Monitoreo</h2><button className="btn btn-secundario btn-pequeno" onClick={() => recargarMon()}>Actualizar</button></div>
          <p>Predicciones analizadas: {mon.predicciones_analizadas} · Probabilidad media: {mon.probabilidad_media ?? "—"} ·
            Tasa de riesgo alto: {mon.tasa_riesgo_alto ?? "—"} · Versiones: {mon.versiones.join(", ") || "—"}</p>
          <p>Préstamos por estado: {Object.entries(mon.prestamos_por_estado).map(([k, v]) => `${k}: ${v}`).join(" · ") || "—"}</p>
          {mon.alertas_drift.length > 0 ? mon.alertas_drift.map((a) => <Alerta key={a} tipo="aviso">{a}</Alerta>) : <p>Sin alertas de drift.</p>}
          <div className="tabla-scroll">
            <table>
              <thead><tr><th>Variable</th><th>PSI</th></tr></thead>
              <tbody>{Object.entries(mon.psi).map(([k, v]) => <tr key={k}><td>{k}</td><td>{v}</td></tr>)}</tbody>
            </table>
          </div>
          <p className="nota">{mon.interpretacion_psi}</p>
        </div>
      )}
    </section>
  );
}
