import os
from dotenv import load_dotenv
from typing import Dict, Any

from langchain_openai import ChatOpenAI
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.tools import tool
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field, ConfigDict
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.elasticsearch import ElasticsearchStore
from elasticsearch import Elasticsearch
try:
    from database import AsyncSessionLocal, ClienteEmpresa, DetalleCliente
except ImportError:
    AsyncSessionLocal = None
    ClienteEmpresa = None
    DetalleCliente = None

from prompts import system_prompt, comunicacion_humanizada_prompt

from sqlalchemy import select, text

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
@tool
async def obtener_esquema_db() -> str:
    """
    Devuelve el esquema técnico (DDL) de las tablas de clientes en la base de datos.
    Úsalo CUANDO necesites saber qué tipos de datos contienen las tablas, 
    antes de responder preguntas sobre la estructura de los datos o realizar consultas complejas.
    """
    if AsyncSessionLocal is None:
        print("a"*200)
        return "Error: No se pudo cargar la configuración de la base de datos."

    async with AsyncSessionLocal() as db:
        try:
            # Query de introspección para obtener definiciones de tablas
            # Filtra por tablas públicas que contengan 'cliente' en el nombre
            query = text("""
                    SELECT 'TABLE ' || table_name || ' (' || 
                           string_agg(column_name || ' ' , ', ') || 
                           ');' as table_definition
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                    AND table_name like '%cliente%'
                    AND COLUMN_NAME not in ('id')
                    GROUP BY table_name
            """)
            
            result = await db.execute(query)
            rows = result.fetchall()
            
            if not rows:
                print("c"*200)
                return "No se encontraron tablas en el base de datos."
            
            # Formateamos la salida para que el LLM la entienda claramente
            print("-"*200)
            print(type(rows), rows)
            print("-"*200)
            schema_definitions = "\n".join([str(row) for row in rows])
            return f"Esquema actual de la base de datos:\n{schema_definitions}"
            
        except Exception as e:
            print("b"*200, str(e))
            return f"Error mientras se intentaba recuperar el esquema: {str(e)}"


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
                return f"No contamos información de la empresa '{nombre_empresa}'. Por favor, verifica el nombre o intenta con otro término de búsqueda."

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

            return [
                ('Monto Transaccional', cliente.monto_transacciones),
                ('Saldo Activo', cliente.saldo_activo),
                ('Saldo Pasivo', cliente.saldo_pasivo),
                ('Uso App', cliente.uso_de_app),
                ('Probabilidad Compra', cliente.prediccion_compra),
                ('¿Cliente Comprador?', 'Sí' if cliente.hizo_compra else 'No')
            ]

        except Exception as e:
            #print("6"*200)
            return f"Error recuperando datos financieros: {str(e)}"


# --- Herramienta para Consultar PDFs en Elasticsearch ---

class ConsultarPDFInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    pdf_name: str = Field(
        ..., 
        description="Nombre exacto del archivo PDF con su extensión, por ejemplo: 'ley-26702-general-sistema-financiero-sbs.pdf'"
    )
    pregunta: str = Field(
        ..., 
        description="La pregunta detallada que se desea responder utilizando la información del documento."
    )

def verify_index_exists_local(es_url: str, es_user: str, es_password: str, index_name: str) -> bool:
    """Función auxiliar para verificar la existencia del índice sin levantar LlamaIndex completo."""
    try:
        es_client = Elasticsearch(es_url, basic_auth=(es_user, es_password))
        existe = es_client.indices.exists(index=index_name)
        es_client.close()
        return existe
    except Exception as e:
        return False

@tool("consultar_documento_pdf", args_schema=ConsultarPDFInput)
def consultar_documento_pdf(pdf_name: str, pregunta: str) -> str:
    """
    Consulta información específica dentro de un documento PDF que ha sido indexado en la base de datos vectorial.
    Útil para responder preguntas detalladas sobre leyes, manuales, reportes o documentos técnicos del proyecto.
    """
    try:
        # Formatear el nombre del índice siguiendo tu convención en main.py
        index_name = pdf_name.replace('-', '_').replace('.pdf', '_index').lower()
        
        # Recuperar variables de entorno (Asegúrate de tenerlas en tu archivo .env)
        es_url = os.getenv("ELASTIC_URL")
        es_user = os.getenv("ELASTIC_USER")
        es_password = os.getenv("ELASTIC_PASS")
        
        # 1. Verificamos si el índice ya fue creado (si el documento ya se procesó)
        if not verify_index_exists_local(es_url, es_user, es_password, index_name):
            return f"Lo siento ERROR, el documento '{pdf_name}' aún no ha sido indexado o no se encuentra en la base de datos. Pide al usuario que lo suba primero."
        
        # 2. Conexión al Vector Store existente
        vector_store = ElasticsearchStore(
            es_url=es_url,
            es_user=es_user,
            es_password=es_password,
            index_name=index_name,
        )
        
        # 3. Cargar el índice de LlamaIndex
        index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
        
        # 4. Configurar el motor de búsqueda
        query_engine = index.as_query_engine(similarity_top_k=3)
        
        # 5. Ejecutar la consulta contra los fragmentos del PDF
        respuesta = query_engine.query(pregunta)
        
        return str(respuesta.response)
        
    except Exception as e:
        return f"Ocurrió un error interno al intentar consultar el documento {pdf_name}: {str(e)}"


# --- Herramienta para Listar PDFs Disponibles ---

class ListarPDFsInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    # LangChain a veces requiere al menos un argumento en los esquemas Pydantic para las tools,
    # así que agregamos un dummy por seguridad.
    consulta: str = Field(
        default="listar", 
        description="Parámetro por defecto. Enviar simplemente la palabra 'listar'."
    )

@tool("listar_documentos_pdf", args_schema=ListarPDFsInput)
def listar_documentos_pdf(consulta: str = "listar") -> str:
    """
    Obtiene el listado exacto de todos los documentos PDF que están subidos y disponibles 
    en el sistema para ser consultados. Útil cuando el usuario pregunta qué documentos, 
    leyes o archivos hay disponibles en el proyecto.
    """
    try:
        # Definimos la ruta a la carpeta 'pdfs' al igual que en main.py
        pdf_directory = os.path.join(os.path.dirname(__file__), "pdfs")
        
        if not os.path.exists(pdf_directory):
            return "El directorio de documentos aún no ha sido creado o no hay PDFs disponibles."
            
        # Leemos los archivos y filtramos solo los .pdf
        files = sorted([f for f in os.listdir(pdf_directory) if f.lower().endswith('.pdf')])
        
        if not files:
            return "Actualmente no hay ningún documento PDF subido en el sistema."
            
        # Formateamos la lista para que el LLM la lea claramente
        lista_archivos = "\n".join([f"- {f}" for f in files])
        return f"Los siguientes documentos PDF están disponibles para consulta:\n{lista_archivos}"
        
    except Exception as e:
        return f"Ocurrió un error al intentar leer el directorio de documentos: {str(e)}"



# --- Configuración del Agente ---

# Modelo LLM
llm = ChatOpenAI(model="gpt-4o", temperature=0.5)

# Memoria para mantener el contexto de la conversación (Checkpointer)
memory = MemorySaver()

# Lista de herramientas. 
prompt_comunicacion = ChatPromptTemplate.from_template(comunicacion_humanizada_prompt)
comunicacion_humanizada_chain = (prompt_comunicacion | llm | StrOutputParser())

tool_comunicacion_humanizada= comunicacion_humanizada_chain.as_tool(
        name="comunicacion_humanizada_chain",
        description="Herramienta para redirigir las comunicaicones humanizadas de nuestro agente",
    )

tool_tavily = TavilySearchResults()
toolkit = [
    consultar_cliente, 
    detalle_cliente, 
    tool_comunicacion_humanizada, 
    obtener_esquema_db, 
    tool_tavily,
    consultar_documento_pdf,
    listar_documentos_pdf
]


# Creación del Ejecutor del Agente usando create_agent
agent_executor = create_agent(
    model=llm, 

    tools=toolkit, 
    system_prompt= system_prompt,
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
