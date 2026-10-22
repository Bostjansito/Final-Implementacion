# Ciclo MLOps (etapas A a F)

Todo el ciclo se ejecuta con **un comando** en un contenedor con versiones fijas (`ml/requirements.txt`, iguales a las de Préstamos):

```bash
docker compose up -d mlflow
docker compose --profile ml run --rm ml-trainer        # ejecuta ml/entrenar_todo.sh
```

| Etapa | Qué se hace | Dónde |
|---|---|---|
| **A. Validar y versionar datos** | Tipos, rangos, faltantes, duplicados, clases, columnas constantes y redundancia de la cuota. EDA breve. SHA-256 del dataset. Partición **60/20/20 estratificada, semilla 42**, con los IDs de cada partición guardados. Verifica que ningún cliente quede en dos particiones. | `ml/src/preparar_datos.py` → `ml/reportes/eda.md`, `validacion_datos.json`, `ml/artefactos/datos_version.json`, `ml/artefactos/particiones/*_ids.csv` |
| **B. Entrenar y comparar** | Baseline (`DummyClassifier(prior)`) + **4 algoritmos** (regresión logística, árbol, random forest, HistGradientBoosting) en **9 ejecuciones candidatas** con hiperparámetros justificados (tag `justificacion`). Métricas: precision, recall y F1 de la clase 1, ROC-AUC, AP, matriz de confusión y Brier + curva de calibración. | `ml/src/entrenar.py` |
| **C. MLflow** | Cada ejecución registra algoritmo, hiperparámetros, semilla, estrategia de partición, versión y hash de datos, variables, versión del código (hash) y commit, parámetros de preprocesamiento, `pip freeze`, duración, métricas `train_*` y `val_*` (y `test_*` solo del modelo seleccionado), pipeline, matriz de confusión, calibración y reporte. Almacenamiento persistente en `ml/mlflow` (SQLite + artefactos). | http://localhost:5000 |
| **D. Seleccionar, exportar, promover** | Métrica definida **antes** de comparar: **AP en validación**; desempate por ROC-AUC, complejidad y Brier. Umbral elegido en validación con **curva de costo** (FN = 3, FP = 1; ficticios) y **congelado** antes de prueba. Prueba evaluada **una vez**. Exporta el pipeline completo con `joblib` + **manifiesto** + ejemplo de entrada y salida. **Promoción explícita** con `registry/active.json` e historial. | `ml/src/seleccionar_exportar.py`, `ml/src/promover.py`, `ml/registry/` |
| **E. Servir** | Préstamos carga el pipeline **al iniciar** desde `active.json` y verifica hash y versión de scikit-learn. Expone `/prestamos`, `/prestamos/{id}`, `/riesgo/predict`, `/modelo/info`, `/health` y `/ready`. Valida tipos, categorías, faltantes y rangos. | `services/prestamos/app/modelo_ml.py` |
| **F. Monitorear y versionar** | Cada inferencia se registra en `predicciones`. `/modelo/monitoreo` calcula el **PSI** por variable frente a la distribución de entrenamiento (guardada en el manifiesto). `scripts/simular_drift.py` demuestra la alerta. Segunda versión (`v2`), **promoción y rollback** con trazabilidad (prueba 11). | `scripts/simular_drift.py`, `ml/registry/historial_promociones.jsonl` |

## Decisiones sobre los datos

* **Excluidas:**
  * `solicitud_id` y `cliente_id`: identificadores.
  * `incumplimiento_90d`: etiqueta.
  * `tasa_mensual_simulada`: **constante** (0,018).
  * `cuota_estimada_cop`: **redundante**, función exacta de monto, plazo y tasa; diferencia máxima 0,005 COP. Se **recalcula dentro del pipeline**.
* **Faltantes:**
  * `porcentaje_pago_puntual` (20,6 %): significa "sin historial previo". Se imputa la mediana **más un indicador** de faltante, que es informativo.
  * `tipo_empleo`: se imputa la categoría "desconocido".
  * Antigüedad e historial: se imputa la mediana más un indicador.
* **Variables derivadas** (deterministas, dentro del pipeline): cuota calculada, endeudamiento, cuota/ingreso, carga financiera y monto/ingreso.
* **Sin fuga de datos:** imputadores, escalador y *one-hot* se ajustan solo con `fit` sobre entrenamiento, dentro del `Pipeline`.

## Resultados

| | v1 (activa) | v2 (alternativa) |
|---|---|---|
| Ejecución | `logreg_C1_sin_pesos` | `hgb_lr0.05_hojas15` |
| AP validación | 0,521 | 0,505 |
| Umbral (curva de costo) | 0,25 | 0,24 |
| **Prueba** ROC-AUC / AP | **0,697 / 0,533** | 0,681 / 0,511 |
| Prueba recall / precisión clase 1 | 0,718 / 0,411 | 0,697 / 0,398 |
| Prueba Brier (baseline 0,212) | 0,187 | 0,193 |

* La regresión logística **sin pesos** empata en AP con la balanceada, pero está **mejor calibrada** (Brier 0,189 frente a 0,218 en validación). Pesos balanceados desplazan las probabilidades hacia 0,5. Por eso ganó el desempate.
* El poder predictivo es moderado (AUC ~0,70): los datos sintéticos tienen mucho ruido. Los modelos no lineales no superaron al lineal.
* **Reconocimiento:** `v2` también se evaluó en prueba (para documentar la alternativa). La selección de `v1` se hizo antes, solo con validación. La métrica de prueba de `v2` no influyó en la elección.

Informes completos: [eda.md](../ml/reportes/eda.md), [informe_seleccion_v1.md](../ml/reportes/informe_seleccion_v1.md), [informe_seleccion_v2.md](../ml/reportes/informe_seleccion_v2.md), [comparacion_modelos.csv](../ml/reportes/comparacion_modelos.csv).

## Política de decisión (en Préstamos, no en el modelo)

1. Datos mínimos completos y válidos; cliente y producto activos; plazo permitido; monto entre 500.000 y 15.000.000 COP (rango del histórico).
2. Modelo: `probabilidad >= umbral` → riesgo **ALTO** → `RECHAZADA (RIESGO_ALTO)`.
3. Regla de capacidad de pago: `(obligaciones + cuota) / ingresos <= 70 %` (`CARGA_FINANCIERA_MAXIMA_PCT`).
4. Si todo es favorable → `PENDIENTE_INVENTARIO`. **La decisión de riesgo no es la aprobación final**: la aprobación llega cuando Inventario confirma la reserva.

> Datos y decisiones ficticios: el objetivo es evaluar ingeniería de software y MLOps, no una política de crédito real.

## Comandos útiles

```bash
docker compose --profile ml run --rm ml-trainer python promover.py --estado
docker compose --profile ml run --rm ml-trainer python promover.py --version v2 --motivo "prueba"
docker compose --profile ml run --rm ml-trainer python promover.py --rollback --motivo "volver a v1"
curl -X POST localhost:8003/modelo/recargar -H "Authorization: Bearer <token admin>"   # o el botón del frontend
docker compose --profile ml run --rm ml-trainer python predecir_lote.py   # equivalencia artefacto vs API (prueba 10)
```
