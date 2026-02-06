import os
import asyncio
import asyncpg
from typing import AsyncGenerator, Optional 
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, Text, select
from sqlalchemy.orm import sessionmaker, declarative_base, DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker, AsyncAttrs

from datetime import datetime
from sqlalchemy.pool import AsyncAdaptedQueuePool

from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

#engine = create_engine(DATABASE_URL)
# Creación del motor asíncrono con pool_pre_ping para verificar conexiones muertas
engine = create_async_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False  # Cambiar a True para depurar SQL en desarrollo
)

#SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# Constructor de sesiones asíncronas
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Evita errores de lazy-loading en contexto async
    autoflush=False
)

Base = declarative_base()

class Base(AsyncAttrs, DeclarativeBase):
    """Clase base moderna que incluye soporte para atributos asíncronos."""
    pass

class AgentLog(Base):
    __tablename__ = "agent_logs"

    # Definición con Mapped y mapped_column (Estándar 2.0)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_input: Mapped[str] = mapped_column(String(500), nullable=False)
    agent_output: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class User(Base):
    __tablename__ = "users"
    #id = Column(Integer, primary_key=True, index=True)
    id: Mapped[int] = mapped_column(Integer,primary_key=True, autoincrement=True, index=True)
    #google_sub = Column(String, unique=True, index=True)
    google_sub: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    picture: Mapped[str] = mapped_column(String)

class ClienteEmpresa(Base):
    __tablename__ = "clientes_empresa"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    ruc_empresa: Mapped[str] = mapped_column(String, index=True)
    nombre_empresa: Mapped[str] = mapped_column(String, index=False)

class DetalleCliente(Base):
    __tablename__ = "detalle_cliente"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    ruc_empresa: Mapped[str] = mapped_column(String, index=True)
    monto_transacciones: Mapped[float] = mapped_column(Float, default=0.0)
    saldo_pasivo: Mapped[float] = mapped_column(Float, default=0.0)
    saldo_activo: Mapped[float] = mapped_column(Float, default=0.0)
    uso_de_app: Mapped[int] = mapped_column(Integer, default=0)
    prediccion_compra: Mapped[float] = mapped_column(Float, default=0.0)
    hizo_compra: Mapped[float] = mapped_column(Float, default=0.0)

class ChatHistory(Base):
    __tablename__ = "chat_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    user_sub: Mapped[str] = mapped_column(String, index=True) # Vinculado al Google Sub del usuario
    query: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ToolsHistory(Base):
    __tablename__ = "tools_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    user_sub: Mapped[str] = mapped_column(String, index=True) # Vinculado al Google Sub del usuario
    name: Mapped[str] = mapped_column(String, index=False)
    args: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


#def init_db():
#    Base.metadata.create_all(bind=engine)

#async def init_db():
#    async with engine.begin() as conn:
#        #await conn.run_sync(Base.metadata.drop_all)
#        await conn.run_sync(Base.metadata.create_all)

#def get_db():
#    db = SessionLocal()
#    try:
#        yield db
#    finally:
#        db.close()

# Dependencia para inyectar la base de datos en las rutas de FastAPI [8, 20]
async def get_db() -> AsyncGenerator:
    """Inyección de dependencia de sesión asíncrona."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()