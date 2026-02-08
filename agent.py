import os
from dotenv import load_dotenv
from typing import Dict, Any

from langchain_openai import ChatOpenAI
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.tools import tool
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field, ConfigDict
try:
    from database import AsyncSessionLocal, ClienteEmpresa, DetalleCliente
except ImportError:
    AsyncSessionLocal = None
    ClienteEmpresa = None
    DetalleCliente = None

from sqlalchemy import select

load_dotenv()

# --- Esquemas de Entrada (Fix para Pydantic V2) solucion de issue PydanticInvalidForJsonSchema ---
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

# --- Adaptación a herramientas asíncronas ---
@tool(args_schema=DetalleClienteInput)
async def detalle_cliente(nombre_empresa: str) -> str:
    """
    Consulta la base de datos de clientes para obtener su RUC, útil para buscar empresas por nombre aproximado.
    Ejemplo: 'plaza vea' -> '20608300393'
    """
    if AsyncSessionLocal is None:
        #print("0"*200)
        return "Error: No se pudo cargar la configuración de la base de datos."
        
    async with AsyncSessionLocal() as db:
        try:
            stmt = select(ClienteEmpresa).where(
                ClienteEmpresa.nombre_empresa.ilike(f"%{nombre_empresa.lower()}%")
            )
            result = await db.execute(stmt)
            cliente_ruc = result.scalars().first()

            if not cliente_ruc:
                #print("1"*200)
                return f"No contamos con el registro de RUC para la empresa '{nombre_empresa}'. Por favor, verifica el nombre o intenta con otro término de búsqueda."

            return f"El RUC para '{nombre_empresa}' es: {cliente_ruc.ruc_empresa}. Ahora puedes usar este RUC con la herramienta 'consultar_cliente'."

        except Exception as e:
            #print("2"*200, str(e))
            return f"Error consultando detalles del cliente: {str(e)}"

@tool(args_schema=ConsultarClienteInput)
async def consultar_cliente(ruc_empresa: str) -> str:
    """
    Consulta la base de datos financiera para obtener métricas de valor de una empresa.
    Requiere un RUC válido de 11 dígitos. Si no tienes el RUC, usa 'detalle_cliente' primero.
    """
    if AsyncSessionLocal is None:
        #print("3"*200)
        return "Error: No se pudo cargar la configuración de la base de datos."

    # Validación de formato: debe ser numérico y tener 11 dígitos
    if not (ruc_empresa.startswith("10") or ruc_empresa.startswith("20")) or len(ruc_empresa)!= 11 or not ruc_empresa.isdigit():
        #print("4"*200)
        return f"ERROR: El valor '{ruc_empresa}' no es un RUC válido (debe tener 11 dígitos numéricos). Por favor, obtén el RUC correcto usando la herramienta 'detalle_cliente' ingresando el nombre de la empresa."

    async with AsyncSessionLocal() as db:
        try:
            stmt = select(DetalleCliente).where(
                DetalleCliente.ruc_empresa == ruc_empresa
            )
            result = await db.execute(stmt)
            cliente = result.scalars().first()

            if not cliente:
                #print("5"*200)
                return f"No se encontró información financiera para el RUC {ruc_empresa}. Si crees que es un error, intenta buscar el RUC de nuevo con 'detalle_cliente' para confirmar que sea el correcto."

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
            #print("6"*200)
            return f"Error recuperando datos financieros: {str(e)}"


# --- Configuración del Agente ---

# Lista de herramientas. 
toolkit = [consultar_cliente, detalle_cliente, TavilySearchResults()]

# Modelo LLM
llm = ChatOpenAI(model="gpt-4o", temperature=0)

# Memoria para mantener el contexto de la conversación (Checkpointer)
memory = MemorySaver()

# Creación del Ejecutor del Agente usando create_agent
agent_executor = create_agent(
    model=llm, 
    tools=toolkit, 
    checkpointer=memory
)

async def run_agent_query(query: str, thread_id: str) -> Dict[str, Any]:
    """
    Ejecuta el grafo del agente de manera asíncrona, para ello usa .ainvoke() en lugar de .invoke() para no bloquear el loop.
    """
    config = {
        "configurable": {"thread_id": thread_id}
    }
    
    response = await agent_executor.ainvoke(
        {"messages": [("user", query)]}, 
        config=config
    )

    return response
