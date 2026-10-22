from datetime import datetime

from sqlalchemy import (BigInteger, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from credimarket_common.mensajeria import tabla_inbox, tabla_outbox


class Base(DeclarativeBase):
    pass


class Prestamo(Base):
    __tablename__ = "prestamos"
    __table_args__ = (
        # Restricción durable de idempotencia HTTP: misma clave del mismo usuario = misma solicitud.
        UniqueConstraint("usuario_id", "idempotency_key", name="uq_prestamo_idempotencia"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    usuario_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    cliente_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    producto_id: Mapped[str] = mapped_column(String(36), nullable=False)
    producto_nombre: Mapped[str | None] = mapped_column(String(120))
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    plazo_meses: Mapped[int] = mapped_column(Integer, nullable=False)
    # Cotización vigente usada (precio y versión leídos de Productos, nunca del cliente)
    precio_unitario: Mapped[int | None] = mapped_column(BigInteger)
    version_producto: Mapped[int | None] = mapped_column(Integer)
    cotizado_at: Mapped[str | None] = mapped_column(String(40))
    monto: Mapped[int | None] = mapped_column(BigInteger)
    cuota_estimada: Mapped[float | None] = mapped_column(Float)
    carga_financiera: Mapped[float | None] = mapped_column(Float)
    # Evaluación de riesgo
    probabilidad_incumplimiento: Mapped[float | None] = mapped_column(Float)
    decision_riesgo: Mapped[str | None] = mapped_column(String(10))
    umbral: Mapped[float | None] = mapped_column(Float)
    model_version: Mapped[str | None] = mapped_column(String(20))
    model_run_id: Mapped[str | None] = mapped_column(String(40))
    # Estado
    estado: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    motivo: Mapped[str | None] = mapped_column(String(300))
    reserva_id: Mapped[str | None] = mapped_column(String(36))
    reserva_expira_at: Mapped[str | None] = mapped_column(String(40))
    creado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actualizado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                     onupdate=func.now())

    def a_dict(self) -> dict:
        return {
            "id": self.id, "cliente_id": self.cliente_id, "producto_id": self.producto_id,
            "producto_nombre": self.producto_nombre, "cantidad": self.cantidad, "plazo_meses": self.plazo_meses,
            "precio_unitario": self.precio_unitario, "version_producto": self.version_producto,
            "cotizado_at": self.cotizado_at, "monto": self.monto, "cuota_estimada": self.cuota_estimada,
            "carga_financiera": self.carga_financiera,
            "evaluacion": None if self.probabilidad_incumplimiento is None else {
                "probabilidad_incumplimiento": self.probabilidad_incumplimiento,
                "decision_riesgo": self.decision_riesgo, "umbral": self.umbral,
                "model_version": self.model_version, "model_run_id": self.model_run_id,
                "nota": "La decisión de riesgo no es la aprobación final del préstamo.",
            },
            "estado": self.estado, "motivo": self.motivo, "reserva_id": self.reserva_id,
            "reserva_expira_at": self.reserva_expira_at, "idempotency_key": self.idempotency_key,
            "creado_at": self.creado_at.isoformat() if self.creado_at else None,
            "actualizado_at": self.actualizado_at.isoformat() if self.actualizado_at else None,
        }


class CambioEstado(Base):
    __tablename__ = "prestamo_historial"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prestamo_id: Mapped[str] = mapped_column(ForeignKey("prestamos.id"), index=True, nullable=False)
    estado_anterior: Mapped[str | None] = mapped_column(String(30))
    estado_nuevo: Mapped[str] = mapped_column(String(30), nullable=False)
    motivo: Mapped[str | None] = mapped_column(String(300))
    origen: Mapped[str] = mapped_column(String(60), nullable=False)
    creado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Prediccion(Base):
    """Registro de inferencias: trazabilidad y monitoreo (drift)."""
    __tablename__ = "predicciones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    origen: Mapped[str] = mapped_column(String(20), nullable=False)  # prestamo | predict
    prestamo_id: Mapped[str | None] = mapped_column(String(36), index=True)
    model_version: Mapped[str] = mapped_column(String(20), nullable=False)
    entrada: Mapped[dict] = mapped_column(JSONB, nullable=False)
    probabilidad: Mapped[float] = mapped_column(Float, nullable=False)
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    umbral: Mapped[float] = mapped_column(Float, nullable=False)
    creado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


outbox = tabla_outbox(Base.metadata)
inbox = tabla_inbox(Base.metadata)
