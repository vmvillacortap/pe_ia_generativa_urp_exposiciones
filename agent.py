import os
from dotenv import load_dotenv
from typing import Dict, Any

from langchain_openai import ChatOpenAI
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.tools import tool
# Cambio solicitado: importar create_agent de langchain.agents
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver

# Importar Pydantic para definir esquemas explícitos y evitar errores de inferencia
# Se agrega ConfigDict para compatibilidad y resolución de errores de esquema
from pydantic import BaseModel, Field, ConfigDict

# Importar la factoría de sesiones asíncronas para uso dentro de herramientas
# Nota: Se asume que database.py existe en el mismo directorio
try:
    from database import AsyncSessionLocal, ClienteEmpresa, DetalleCliente
except ImportError:
    # Fallback para evitar errores si database.py no está presente durante la edición
    AsyncSessionLocal = None
    ClienteEmpresa = None
    DetalleCliente = None

from sqlalchemy import select

load_dotenv()

# --- Definición de Esquemas de Entrada (Fix para Pydantic V2) ---
# Se agrega model_config para evitar errores de PydanticInvalidForJsonSchema
# al permitir tipos arbitrarios si fuera necesario en esquemas complejos.

class DetalleClienteInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    nombre_empresa: str = Field(
       ..., 
        description="Nombre de la empresa a buscar, por ejemplo: 'plaza vea'"
    )

class ConsultarClienteInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    ruc_empresa: str = Field(
       ..., 
        description="RUC válido de la empresa (11 dígitos) para consultar reporte."
    )

# --- Definición de Herramientas Asíncronas ---

@tool(args_schema=DetalleClienteInput)
async def detalle_cliente(nombre_empresa: str) -> str:
    """
    Consulta la base de datos de clientes para obtener su RUC (Identificador Fiscal).
    Útil para buscar empresas por nombre aproximado.
    Ejemplo: 'plaza vea' -> '20608300393'
    """
    if AsyncSessionLocal is None:
        return "Error: No se pudo cargar la configuración de la base de datos."
        
    async with AsyncSessionLocal() as db:
        try:
            # Búsqueda insensible a mayúsculas (ilike)
            stmt = select(ClienteEmpresa).where(
                ClienteEmpresa.nombre_empresa.ilike(f"%{nombre_empresa.lower()}%")
            )
            result = await db.execute(stmt)
            cliente_ruc = result.scalars().first()

            if not cliente_ruc:
                return "No contamos con el registro de RUC para esta empresa."

            return cliente_ruc.ruc_empresa
        except Exception as e:
            return f"Error consultando detalles del cliente: {str(e)}"

@tool(args_schema=ConsultarClienteInput)
async def consultar_cliente(ruc_empresa: str) -> str:
    """
    Consulta la base de datos financiera para obtener métricas de valor de una empresa.
    Requiere un RUC válido de 11 dígitos.
    """
    if AsyncSessionLocal is None:
        return "Error: No se pudo cargar la configuración de la base de datos."

    # Validación simple de formato
    if not (ruc_empresa.startswith("10") or ruc_empresa.startswith("20")) or len(ruc_empresa)!= 11:
        return "ERROR: Formato de RUC inválido. Debes buscar el RUC primero usando la herramienta 'detalle_cliente'."

    async with AsyncSessionLocal() as db:
        try:
            stmt = select(DetalleCliente).where(
                DetalleCliente.ruc_empresa.ilike(f"%{ruc_empresa}%")
            )
            result = await db.execute(stmt)
            cliente = result.scalars().first()

            if not cliente:
                return "No se encontró información financiera para esta empresa en la base de datos."

            hizo_compra_str = 'Sí' if cliente.hizo_compra else 'No'
            
            return f"""
                Reporte para RUC {cliente.ruc_empresa}:
                - Monto Transaccional: ${cliente.monto_transacciones}
                - Saldo Activo: ${cliente.saldo_activo}
                - Saldo Pasivo: ${cliente.saldo_pasivo}
                - Uso App: {cliente.uso_de_app}
                - Probabilidad Compra: {cliente.prediccion_compra}%
                - ¿Cliente Comprador?: {hizo_compra_str}
            """
        except Exception as e:
            return f"Error recuperando datos financieros: {str(e)}"

# --- Configuración del Agente ---

# Lista de herramientas. 
# IMPORTANTE: Instanciamos TavilySearchResults() para evitar errores de esquema de Pydantic.
toolkit = [consultar_cliente, detalle_cliente, TavilySearchResults()]

# Modelo LLM
llm = ChatOpenAI(model="gpt-4o", temperature=0)

# Memoria para mantener el contexto de la conversación (Checkpointer)
memory = MemorySaver()

# Creación del Ejecutor del Agente usando create_agent (solicitado)
# create_agent en las versiones recientes de langchain.agents (basadas en langgraph)
# mantiene una firma compatible con la orquestación de grafos.
agent_executor = create_agent(
    model=llm, 
    tools=toolkit, 
    checkpointer=memory
)

async def run_agent_query(query: str, thread_id: str) -> Dict[str, Any]:
    """
    Ejecuta el grafo del agente de manera asíncrona.
    Utiliza .ainvoke() en lugar de .invoke() para no bloquear el loop.
    """
    config = {
        "configurable": {"thread_id": thread_id}
    }
    
    # La llamada ainvoke es crucial para el rendimiento bajo carga
    response = await agent_executor.ainvoke(
        {"messages": [("user", query)]}, 
        config=config
    )

    return response
