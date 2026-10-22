#!/bin/sh
# Ciclo MLOps completo (etapas A a D). Se ejecuta con:
#   docker compose --profile ml run --rm ml-trainer
set -eu
cd /work/ml/src
echo "== A. Validar, versionar y particionar datos =="
python preparar_datos.py
echo "== B y C. Entrenar baseline + candidatos y registrar en MLflow =="
python entrenar.py
echo "== D. Seleccionar, exportar v1 (mejor global) =="
[ -d ../registry/models/v1 ] && echo "v1 ya existe, se conserva" || python seleccionar_exportar.py --version v1
echo "== D. Exportar v2 (mejor boosting, alternativa no lineal para promoción/rollback) =="
[ -d ../registry/models/v2 ] && echo "v2 ya existe, se conserva" || python seleccionar_exportar.py --version v2 --familia hgb
if [ ! -f ../registry/active.json ]; then
  python promover.py --version v1 --motivo "promoción inicial: mejor AP en validación"
fi
python promover.py --estado
