# Contexto de construcción: raíz del repositorio (ver docker-compose.yml)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY services/clientes/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY libs/common/credimarket_common ./credimarket_common
COPY services/clientes/app ./app
RUN useradd -r -u 10001 app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
