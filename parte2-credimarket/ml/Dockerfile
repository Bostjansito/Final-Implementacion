# Entorno de entrenamiento: mismas versiones de scikit-learn/pandas/numpy/joblib que Préstamos.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg
WORKDIR /work/ml/src
COPY ml/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
# El código (ml/) y los datos (data/) se montan como volúmenes: ver docker-compose.yml (perfil "ml").
CMD ["sh", "/work/ml/entrenar_todo.sh"]
