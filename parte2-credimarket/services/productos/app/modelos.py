from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Producto(Base):
    __tablename__ = "productos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, default="")
    categoria: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    precio: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    creado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actualizado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                     onupdate=func.now())

    def a_dict(self) -> dict:
        return {
            "id": self.id, "sku": self.sku, "nombre": self.nombre, "descripcion": self.descripcion,
            "categoria": self.categoria, "precio": self.precio, "activo": self.activo,
            "version": self.version,
            "actualizado_at": self.actualizado_at.isoformat() if self.actualizado_at else None,
        }


class HistorialPrecio(Base):
    __tablename__ = "historial_precios"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    producto_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    precio: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cambiado_por: Mapped[str] = mapped_column(String(120), nullable=False)
    cambiado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
