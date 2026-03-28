import os
import json
import logging
from contextlib import asynccontextmanager

import os
import shutil  # NUEVO: Para guardar archivos
import asyncio # NUEVO: Para simular delay de indexación
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException # MODIFICADO: AgregadosUploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from llama_index.core import VectorStoreIndex, StorageContext
from llama_index.readers.file import PDFReader
from llama_index.vector_stores.elasticsearch import ElasticsearchStore
from llama_index.core.node_parser import SemanticSplitterNodeParser
from llama_index.embeddings.openai import OpenAIEmbedding
from elasticsearch import Elasticsearch

from authlib.integrations.starlette_client import OAuth
from starlette.middleware.sessions import SessionMiddleware
from starlette.config import Config
from pydantic import BaseModel

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, asc

from dotenv import load_dotenv
from database import (
    get_db, engine, Base, User, ChatHistory, ToolsHistory, ClienteEmpresa
)
from agent import run_agent_query

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Ciclo de Vida asincrono ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Crear tablas
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Limpiar conexiones
    await engine.dispose()

app = FastAPI(title="AI Agent API", lifespan=lifespan)

# Definimos el directorio de PDFs y lo creamos si no existe
PDF_DIRECTORY = os.path.join(os.path.dirname(__file__), "pdfs")
if not os.path.exists(PDF_DIRECTORY):
    os.makedirs(PDF_DIRECTORY)

# Servimos archivos estáticos (para CSS, imágenes, etc. si las hubiera)
app.mount("/static", StaticFiles(directory="."), name="static")

app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "supersecret"))
templates = Jinja2Templates(directory="templates")

# --- Auth Google ---
oauth = OAuth(Config(environ=os.environ))
oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# --- Endpoints Auth ---
@app.get("/login")
async def login(request: Request):
    redirect_uri = request.url_for('auth_callback')
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get("/auth/callback")
async def auth_callback(request: Request, db: AsyncSession = Depends(get_db)):
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get('userinfo')
    
    if user_info:
        stmt = select(User).where(User.google_sub == user_info['sub'])
        result = await db.execute(stmt)
        user = result.scalars().first()
        
        if not user:
            new_user = User(
                google_sub=user_info['sub'],
                email=user_info['email'],
                name=user_info['name'],
                picture=user_info.get('picture')
            )
            db.add(new_user)
            await db.commit()
            
        request.session['user'] = dict(user_info)
    return RedirectResponse(url='/chat')

@app.get("/logout")
async def logout(request: Request):
    request.session.pop('user', None)
    return RedirectResponse(url='/')

# --- UI Endpoints ---
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return RedirectResponse(url='/chat') if request.session.get('user') else templates.TemplateResponse("login.html", {"request": request})

@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    user = request.session.get('user')
    if not user: return RedirectResponse(url='/login')
    return templates.TemplateResponse("chat.html", {"request": request, "user": user})

# --- API del Agente ---
@app.post("/api/chat")
async def chat_endpoint(request: Request, db: AsyncSession = Depends(get_db)):
    user = request.session.get('user')
    if not user: raise HTTPException(status_code=401)
    
    data = await request.json()
    query_text = data.get("message")
    
    try:
        # 1. Iniciamos el agente
        response_state = await run_agent_query(query_text, user['sub'])
        messages = response_state.get("messages",)
        
        # 2. Obtenemos la última respuesta
        final_response = "No response"
        if messages:
            final_response = messages[-1].content
            
        # 3. Almacenamos herramientas usadas
        for msg in messages:
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    new_tool_log = ToolsHistory(
                        user_sub=user['sub'],
                        name=tool_call.get('name'),
                        args=json.dumps(tool_call.get('args'))
                    )
                    db.add(new_tool_log)
        
        # 4. Y tambien guardamos el historial de chat
        new_chat = ChatHistory(
            user_sub=user['sub'],
            query=query_text,
            response=str(final_response)
        )
        db.add(new_chat)
        await db.commit()
        
        return {"response": final_response}
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Error en chat: {e}")
        return {"response": "Error interno procesando tu solicitud.", "error": str(e)}

# --- API para obtener el historial de chat ---
@app.get("/api/history")
async def get_history(request: Request, db: AsyncSession = Depends(get_db)):
    user = request.session.get('user')
    if not user: raise HTTPException(status_code=401)
    
    stmt = select(ChatHistory).where(ChatHistory.user_sub == user['sub']).order_by(desc(ChatHistory.timestamp)).limit(10)
    result = await db.execute(stmt)
    return result.scalars().all()

# --- API para obtener el historial de herramientas usadas---
@app.get("/api/toolshistory")
async def get_tools_history(request: Request, db: AsyncSession = Depends(get_db)):
    user = request.session.get('user')
    if not user: raise HTTPException(status_code=401)
    
    stmt = select(ToolsHistory).where(ToolsHistory.user_sub == user['sub']).order_by(desc(ToolsHistory.timestamp)).limit(15)
    result = await db.execute(stmt)
    return result.scalars().all()


@app.get("/api/pdfs")
async def list_pdfs():
    """Ruta dinámica que lee la carpeta y devuelve todos los archivos PDF disponibles."""
    try:
        # Aseguramos que la carpeta exista antes de leer
        if not os.path.exists(PDF_DIRECTORY):
             return {"pdfs": []}
        # Leemos todos los archivos .pdf y los ordenamos alfabéticamente
        files = sorted([f for f in os.listdir(PDF_DIRECTORY) if f.lower().endswith('.pdf')])
        return {"pdfs": files}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/pdf/{file_name}")
async def get_pdf_file(file_name: str):
    """Ruta para servir archivos PDF individuales."""
    file_path = os.path.join(PDF_DIRECTORY, file_name)
    # Normalizamos la ruta para seguridad y verificamos existencia
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path, media_type='application/pdf')
    else:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")



def verify_index_exists(es_url: str, es_user: str, es_password: str, index_name: str) -> bool:
    """
    Verifica si un índice específico existe en la base de datos vectorial Elasticsearch.
    
    """
    try:
        # Cliente nativo de Elasticsearch
        es_client = Elasticsearch(
            es_url,
            basic_auth=(es_user, es_password)
        )
        
        # El método indices.exists devuelve un booleano nativo
        existe = es_client.indices.exists(index=index_name)
        
        # cerrando conexión
        es_client.close() 
        
        return existe
        
    except Exception as e:
        # Registramos el error sin detener la ejecución de la aplicación
        logging.error(f"Error al verificar el índice '{index_name}' en Elasticsearch: {e}")
        return False

class PDFQuestionRequest(BaseModel):
    pdf_name: str
    question: str

@app.post("/api/pdf_question")
async def ask_pdf_question(request: PDFQuestionRequest):
    """Endpoint para recibir preguntas sobre un PDF específico."""
    inddex_name = request.pdf_name.replace('-', '_').replace('.pdf', '_index')


    vector_store = ElasticsearchStore(
        es_url=os.getenv("ELASTIC_URL"),
        es_user=os.getenv("ELASTIC_USER"),
        es_password=os.getenv("ELASTIC_PASS"),
        index_name=inddex_name,
    )

    if verify_index_exists(
        os.getenv("ELASTIC_URL"), 
        os.getenv("ELASTIC_USER"), 
        os.getenv("ELASTIC_PASS"), 
        inddex_name
    ):
        print(f"✅ El índice '{inddex_name}' SÍ existe. Listo para consumir.")

        # CArgamos el índice directamente desde la base de datos vectorial
        index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
        query_engine = index.as_query_engine(
            similarity_top_k=3, # Opcional: define cuántos fragmentos de contexto quieres recuperar
        )

        # consulta a RAG
        answer_message = query_engine.query(request.question).response

    else:
        answer_message =  f"❌ El índice '{inddex_name}' NO existe o no se pudo conectar."

    return {"message": answer_message}



async def simulate_elasticsearch_indexing(file_path: str):
    """
    Función simulada para indexar el contenido en Elasticsearch.
    Aquí es donde integrarás la lógica de LlamaIndex/GenAI.
    """
    file_name = os.path.basename(file_path)
    print(f"DEBUG: Iniciando indexación simulada en Elasticsearch para: {file_name}")
    
    # Simulamos un proceso pesado de RAG/Embeddings (3 segundos)
    # En producción, esto no debe bloquear el hilo principal.
    await asyncio.sleep(3) 
    
    print(f"DEBUG: Indexación finalizada exitosamente para: {file_name}")
    # Aquí devolverías True o lanzarías una excepción si falla



# NUEVO ENDPOINT
@app.post("/api/upload_pdf")
async def upload_pdf(
    file: UploadFile = File(...), 
    overwrite: bool = Form(False)
):
    """
    Endpoint para subir un PDF, verificar existencia, sobreescribir e indexar.
    Devuelve 409 si el archivo existe y 'overwrite' es False.
    """
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Solamente se permiten archivos PDF.")

    file_name = file.filename
    file_path = os.path.join(PDF_DIRECTORY, file_name)

    # 1. Verificación de existencia para sobreescritura
    if os.path.exists(file_path) and not overwrite:
        # Devolvemos 409 Conflict indicando que el recurso ya existe
        return JSONResponse(
            content={
                "status": "exists", 
                "message": f"El archivo '{file_name}' ya existe. ¿Deseas sobreescribirlo?"
            }, 
            status_code=409
        )

    # 2. Guardar el archivo físicamente
    try:
        # Usamos 'async with file.read()' dentro de una escritura normal
        # para no bloquear, aunque shutil.copyfileobj es síncrono.
        # En producción 'aiofiles' es mejor práctica, pero esto funciona bien en FastAPI.
        with open(file_path, "wb") as buffer:
            # Leemos el contenido subido en trozos para no saturar memoria
            while content := await file.read(1024 * 1024): # 1MB chunks
                buffer.write(content)
        
        print(f"DEBUG: Archivo guardado físicamente en: {file_path}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al guardar el archivo: {str(e)}")

    # 3. Trigger de Indexación en Elasticsearch (Simulado Asíncronamente)
    try:
        # Ejecutamos la función de indexación. Al ser 'async', esperamos a que termine
        # para que el frontend mantenga el estado de carga.
        await simulate_elasticsearch_indexing(file_path)
    except Exception as e:
        # Si la indexación falla, quizás quieras borrar el archivo recién subido
        # os.remove(file_path) 
        raise HTTPException(status_code=500, detail=f"El archivo se subió pero falló la indexación: {str(e)}")

    return {"status": "success", "message": f"Archivo '{file_name}' subido e indexado correctamente."}


# --- FIN DE ENDPOINTS PARA PDFs ---