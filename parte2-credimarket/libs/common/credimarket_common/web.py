import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import lista


def configurar_logging(servicio: str) -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format=f"%(asctime)s %(levelname)s [{servicio}] %(name)s: %(message)s",
    )
    logging.getLogger("pika").setLevel(logging.WARNING)


def configurar_cors(app: FastAPI) -> None:
    origenes = lista("CORS_ORIGINS", "http://localhost:8080")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origenes,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        expose_headers=["X-Cache", "Location"],
    )
