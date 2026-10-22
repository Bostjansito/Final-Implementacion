from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TIPOS_EMPLEO = ("dependiente", "independiente", "temporal")

# Campos financieros y laborales (mismos nombres que el histórico de entrenamiento)
CAMPOS_FINANCIEROS = (
    "ingresos_mensuales_cop", "obligaciones_mensuales_cop", "tipo_empleo",
    "antiguedad_laboral_meses", "meses_historial_crediticio", "creditos_previos",
    "atrasos_previos_30d", "porcentaje_pago_puntual",
)


class Base(DeclarativeBase):
    pass


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    codigo_externo: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    documento: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(160))
    telefono: Mapped[str | None] = mapped_column(String(30))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ingresos_mensuales_cop: Mapped[int | None] = mapped_column(BigInteger)
    obligaciones_mensuales_cop: Mapped[int | None] = mapped_column(BigInteger)
    tipo_empleo: Mapped[str | None] = mapped_column(String(20))
    antiguedad_laboral_meses: Mapped[float | None] = mapped_column(Float)
    meses_historial_crediticio: Mapped[float | None] = mapped_column(Float)
    creditos_previos: Mapped[int | None] = mapped_column(Integer)
    atrasos_previos_30d: Mapped[int | None] = mapped_column(Integer)
    porcentaje_pago_puntual: Mapped[float | None] = mapped_column(Float)
    origen: Mapped[str] = mapped_column(String(20), nullable=False, default="registro")
    creado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actualizado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                     onupdate=func.now())

    def a_dict(self, financiero: bool = True) -> dict:
        d = {"id": self.id, "codigo_externo": self.codigo_externo, "nombre": self.nombre,
             "documento": self.documento, "email": self.email, "telefono": self.telefono,
             "activo": self.activo, "origen": self.origen}
        if financiero:
            d.update({c: getattr(self, c) for c in CAMPOS_FINANCIEROS})
        return d


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    rol: Mapped[str] = mapped_column(String(20), nullable=False)  # CLIENTE | ADMIN
    cliente_id: Mapped[str | None] = mapped_column(ForeignKey("clientes.id"), unique=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Importacion(Base):
    __tablename__ = "importaciones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    archivo: Mapped[str] = mapped_column(String(200), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    filas: Mapped[int] = mapped_column(Integer, nullable=False)
    insertados: Mapped[int] = mapped_column(Integer, nullable=False)
    actualizados: Mapped[int] = mapped_column(Integer, nullable=False)
    sin_cambios: Mapped[int] = mapped_column(Integer, nullable=False)
    rechazados: Mapped[int] = mapped_column(Integer, nullable=False)
    errores: Mapped[list] = mapped_column(JSONB, nullable=False)
    realizada_por: Mapped[str] = mapped_column(String(160), nullable=False)
    creado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
