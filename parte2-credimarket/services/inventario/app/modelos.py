from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from credimarket_common.mensajeria import tabla_inbox, tabla_outbox


class Base(DeclarativeBase):
    pass


class Existencia(Base):
    __tablename__ = "existencias"
    __table_args__ = (
        # Última línea de defensa: la base de datos nunca acepta existencias negativas.
        CheckConstraint("disponible >= 0", name="ck_disponible_no_negativo"),
        CheckConstraint("reservado >= 0", name="ck_reservado_no_negativo"),
    )

    producto_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    disponible: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reservado: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actualizado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                     onupdate=func.now())


class Reserva(Base):
    __tablename__ = "reservas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Una sola reserva por préstamo: evita reservar dos veces ante comandos repetidos.
    prestamo_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    producto_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    motivo: Mapped[str | None] = mapped_column(String(120))
    expira_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(80))
    creado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actualizado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                     onupdate=func.now())

    def a_dict(self) -> dict:
        return {"id": self.id, "prestamo_id": self.prestamo_id, "producto_id": self.producto_id,
                "cantidad": self.cantidad, "estado": self.estado, "motivo": self.motivo,
                "expira_at": self.expira_at.isoformat() if self.expira_at else None,
                "creado_at": self.creado_at.isoformat() if self.creado_at else None,
                "actualizado_at": self.actualizado_at.isoformat() if self.actualizado_at else None}


class Movimiento(Base):
    __tablename__ = "movimientos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    producto_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # ENTRADA|RESERVA|LIBERACION|SALIDA|VENCIMIENTO
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    reserva_id: Mapped[str | None] = mapped_column(String(36))
    prestamo_id: Mapped[str | None] = mapped_column(String(36))
    nota: Mapped[str | None] = mapped_column(Text)
    realizado_por: Mapped[str] = mapped_column(String(160), nullable=False)
    creado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def a_dict(self) -> dict:
        return {"id": self.id, "producto_id": self.producto_id, "tipo": self.tipo, "cantidad": self.cantidad,
                "reserva_id": self.reserva_id, "prestamo_id": self.prestamo_id, "nota": self.nota,
                "realizado_por": self.realizado_por, "creado_at": self.creado_at.isoformat()}


outbox = tabla_outbox(Base.metadata)
inbox = tabla_inbox(Base.metadata)
