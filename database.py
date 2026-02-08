import ssl
import os
from typing import Optional, List
from datetime import datetime
from sqlalchemy.engine import make_url
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

load_dotenv()

# --- Configuración de la Base de Datos
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent_db")

def sanitize_and_configure(url_string):
    # Convertir string a objeto URL mutable
    url_obj = make_url(url_string)
    
    # Asegurar el driver correcto
    if url_obj.drivername == 'postgres':
        url_obj = url_obj._replace(drivername='postgresql+asyncpg')
    
    # Extraer y eliminar 'sslmode' de los query params
    query_dict = dict(url_obj.query)
    if 'sslmode' in query_dict:
        # Loguear advertencia si es necesario
        del query_dict['sslmode']
    
    # Reconstruir la URL limpia
    clean_url = url_obj._replace(query=query_dict)
    
    return clean_url

# Creación del Motor Asíncrono
clean_url = sanitize_and_configure(DATABASE_URL)
engine = create_async_engine(
    clean_url,
    #connect_args={"ssl": ssl_context},
    pool_pre_ping=True,
    echo=True,  # para que se vean las interacciones de la base de datos en el log 
    pool_size=20,
    max_overflow=10
)

# Fábrica de Sesiones Asíncronas
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

# --- Inyección de Dependencias para FastAPI
async def get_db():
    """
    Generador asíncrono, garantiza que la sesión se cierre correctamente después de cada request.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# --- Definición de Modelos
class Base(AsyncAttrs, DeclarativeBase):
    """
    Clase base para permitir atributos asincronos en carga lazy
    """
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    google_sub: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    picture: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    #created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    # Relaciones
    chat_history: Mapped[List["ChatHistory"]] = relationship(back_populates="user")
    tools_history: Mapped[List["ToolsHistory"]] = relationship(back_populates="user")

class ChatHistory(Base):
    __tablename__ = "chat_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_sub: Mapped[str] = mapped_column(ForeignKey("users.google_sub"))
    query: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text)
    #timestamp: Mapped[datetime] = mapped_column(server_default=func.now())
    timestamp: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="chat_history")

class ToolsHistory(Base):
    __tablename__ = "tools_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_sub: Mapped[str] = mapped_column(ForeignKey("users.google_sub"))
    name: Mapped[str] = mapped_column(String)
    args: Mapped[str] = mapped_column(Text)
    #timestamp: Mapped[datetime] = mapped_column(server_default=func.now())
    timestamp: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="tools_history")

class ClienteEmpresa(Base):
    __tablename__ = "clientes_empresa"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ruc_empresa: Mapped[str] = mapped_column(String(11), unique=True, index=True)
    nombre_empresa: Mapped[str] = mapped_column(String, index=True)
    #hizo_compra: Mapped[bool] = mapped_column(Boolean, default=False)

class DetalleCliente(Base):
    __tablename__ = "detalle_cliente"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ruc_empresa: Mapped[str] = mapped_column(String(11), unique=True, index=True)
    monto_transacciones: Mapped[float] = mapped_column(Float, default=0.0)
    saldo_activo: Mapped[float] = mapped_column(Float, default=0.0)
    saldo_pasivo: Mapped[float] = mapped_column(Float, default=0.0)
    uso_de_app: Mapped[int] = mapped_column(default=0)
    prediccion_compra: Mapped[float] = mapped_column(Float, default=0.0)
    hizo_compra: Mapped[int] = mapped_column(default=0)