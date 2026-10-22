# Contexto de construcción: raíz del repositorio (ver docker-compose.yml)
# La misma imagen sirve para la API (uvicorn) y para el worker (python -m app.worker).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY services/prestamos/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY libs/common/credimarket_common ./credimarket_common
# Paquete del modelo: el pipeline exportado referencia sus funciones
COPY ml/credimarket_ml ./credimarket_ml
COPY services/prestamos/app ./app
RUN useradd -r -u 10001 app
USER app
EXPOSE 8000
# El registro de modelos (ml/registry) se monta de solo lectura en /srv/registry
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
