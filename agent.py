from langchain_openai import ChatOpenAI
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
#from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver
from database import AsyncSessionLocal, ClienteEmpresa, DetalleCliente
import os
from dotenv import load_dotenv

load_dotenv()



@tool
def detalle_cliente(nombre_empresa: str) -> str:
    """Consulta la base de datos de clientes para obtener su ruc y así con él acceder a mayor información
       Ejemplo: 'plaza vea' -> '20608300393'
    """
    db = AsyncSessionLocal()
    try:
        cliente_ruc = db.query(ClienteEmpresa).filter(ClienteEmpresa.nombre_empresa.ilike(f"%{nombre_empresa.lower()}%")).first()

        if not cliente_ruc:
            return "No contamos con el registro de ruc para esta empresa"

        return cliente_ruc.ruc_empresa
    finally:
        db.close()


@tool
def consultar_cliente(ruc_empresa: str) -> str:
    """Consulta la base de datos financiera para obtener información de valor de una empresa."""

    if not(ruc_empresa.startswith("10")) and not(ruc_empresa.startswith("20")) and ruc_empresa.lenght() != 11:
        return " ERROR: Formato de RUC inválido. Debes buscar el ruc primero usando la herramienta 'detalle_cliente'."

    db = AsyncSessionLocal()
    try:
        cliente_detail = db.query(DetalleCliente).filter(DetalleCliente.ruc_empresa.ilike(f"%{ruc_empresa}%")).first()

        if not cliente_detail:
            return "No se encontró esa empresa en la base de datos."

        return f"""
            Con ruc: {cliente.ruc_empresa}, esta empresa registra:
            - Monto Transaccional: ${cliente.monto_transacciones}
            - Saldo Activo: ${cliente.saldo_activo}
            - Saldo Pasivo: ${cliente.saldo_pasivo}
            - Uso App: {cliente.uso_de_app}
            - Probabilidad Compra: {cliente.prediccion_compra}%
            - ¿Ya compró?: {'Sí' if cliente.hizo_compra else 'No'}
        """
    finally:
        db.close()

#@tool
#def registrar_compra(nombre_empresa: str) -> str:
#    """Actualiza la base de datos marcando que una empresa YA realizó una compra."""
#    db = SessionLocal()
#    try:
#        cliente = db.query(ClienteEmpresa).filter(ClienteEmpresa.nombre_empresa.ilike(f"%{nombre_empresa}%")).first()
#        if not cliente:
#            return "Error: Empresa no encontrada para actualizar."
#        cliente.hizo_compra = True
#        cliente.monto_transacciones += 1000
#        db.commit()
#        return f"Éxito: Se registró la compra para {cliente.nombre_empresa} y se actualizó la DB."
#    except Exception as e:
#        return f"Error en DB: {str(e)}"
#    finally:
#        db.close()


tools = [TavilySearchResults(max_results=1), consultar_cliente, detalle_cliente]
llm = ChatOpenAI(model="gpt-4o", temperature=0)
memory = MemorySaver()
agent_executor = create_react_agent(
    model=llm, 
    tools=tools, 
    checkpointer=memory
)

def run_agent_query(query: str, thread_id: str):
    config = {
        "configurable": {"thread_id": thread_id}
    }
    response = agent_executor.invoke(
        {"messages": [("user", query)]}, 
        config=config
    )

    return response
