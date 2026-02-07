import ssl
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

# --- Configuración de la Base de Datos ---
# Se utiliza el esquema 'postgresql+asyncpg' para habilitar el driver asíncrono.
# Es fundamental que la URL apunte a una instancia PostgreSQL válida.
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent_db"
)

# Creación del Motor Asíncrono (Async Engine)
# pool_size: Mantiene conexiones vivas listas para usar.
# max_overflow: Permite picos temporales de tráfico.
#ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
#ssl_context.verify_mode = ssl.CERT_REQUIRED

from sqlalchemy.engine import make_url

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

# Uso
clean_url = sanitize_and_configure(DATABASE_URL)
engine = create_async_engine(
    clean_url,
    #connect_args={"ssl": ssl_context},
    pool_pre_ping=True,
    echo=True,  # Cambiar a True para ver SQL en logs durante desarrollo
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
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    picture: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Relaciones tipadas explícitamente
    chat_history: Mapped[List["ChatHistory"]] = relationship(back_populates="user")
    tools_history: Mapped[List["ToolsHistory"]] = relationship(back_populates="user")

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