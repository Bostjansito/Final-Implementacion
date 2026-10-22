FROM python:3.12-slim
RUN pip install --no-cache-dir cryptography==44.0.2
COPY init_secrets.py /init_secrets.py
CMD ["python", "/init_secrets.py"]
