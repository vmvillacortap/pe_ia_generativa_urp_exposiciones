#Importaciones
import os
from typing import Optional, List
from datetime import datetime
from sqlalchemy.ext.asyncio import (
    create_async_engine, 
    AsyncSession, 
    async_sessionmaker, 
    AsyncAttrs
)
from sqlalchemy.orm import (
    DeclarativeBase, 
    Mapped, 
    mapped_column, 
    relationship
)
from sqlalchemy import String, Float, Text, ForeignKey, func, Boolean
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# Creación del Motor Asíncrono (Async Engine)
# pool_size: Mantiene conexiones vivas listas para usar.
# max_overflow: Permite picos temporales de tráfico.
engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Cambiar a True para ver SQL en logs durante desarrollo
    pool_size=20,
    max_overflow=10
)

# Fábrica de Sesiones Asíncronas
# expire_on_commit=False es OBLIGATORIO en async para evitar errores de I/O implícito
# al acceder a atributos después de un commit.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

# --- Inyección de Dependencias para FastAPI ---
async def get_db():
    """
    Generador asíncrono de sesiones de base de datos.
    Garantiza que la sesión se cierre correctamente después de cada request.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# --- Definición de Modelos (Sintaxis SQLAlchemy 2.0) ---
class Base(AsyncAttrs, DeclarativeBase):
    """
    Clase base para todos los modelos ORM.
    AsyncAttrs permite el uso de.awaitable_attrs para carga perezosa si fuera estrictamente necesario.
    """
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    google_sub: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)class ChatHistory(Base):
    __tablename__ = "chat_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_sub: Mapped[str] = mapped_column(ForeignKey("users.google_sub"))
    query: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="chat_history")

class ChatHistory(Base):
    __tablename__ = "chat_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_sub: Mapped[str] = mapped_column(ForeignKey("users.google_sub"))
    query: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="chat_history")

class ToolsHistory(Base):
    __tablename__ = "tools_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_sub: Mapped[str] = mapped_column(ForeignKey("users.google_sub"))
    name: Mapped[str] = mapped_column(String)
    args: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="tools_history")

class ClienteEmpresa(Base):
    __tablename__ = "cliente_empresa"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ruc_empresa: Mapped[str] = mapped_column(String(11), unique=True, index=True)
    nombre_empresa: Mapped[str] = mapped_column(String, index=True)
    hizo_compra: Mapped[bool] = mapped_column(Boolean, default=False)

class DetalleCliente(Base):
    __tablename__ = "detalle_cliente"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ruc_empresa: Mapped[str] = mapped_column(ForeignKey("cliente_empresa.ruc_empresa"), unique=True)
    monto_transacciones: Mapped[float] = mapped_column(Float, default=0.0)
    saldo_activo: Mapped[float] = mapped_column(Float, default=0.0)
    saldo_pasivo: Mapped[float] = mapped_column(Float, default=0.0)
    uso_de_app: Mapped[int] = mapped_column(default=0)
    prediccion_compra: Mapped[float] = mapped_column(Float, default=0.0)
    hizo_compra: Mapped[int] = mapped_column(default=0)


