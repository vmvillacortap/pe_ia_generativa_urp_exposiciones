import os
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from authlib.integrations.starlette_client import OAuth
from starlette.middleware.sessions import SessionMiddleware
from starlette.config import Config

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from dotenv import load_dotenv

# Importaciones locales
from database import (
    get_db, engine, Base, User, ChatHistory, ToolsHistory, ClienteEmpresa
)
from agent import run_agent_query

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Ciclo de Vida (Lifespan) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicio: Crear tablas
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Cierre: Limpiar conexiones
    await engine.dispose()

app = FastAPI(title="AI Agent API", lifespan=lifespan)

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
    
    # 1. Ejecutar Agente (Graph)
    # create_agent devuelve un estado con la clave "messages"
    try:
        response_state = await run_agent_query(query_text, user['sub'])
        messages = response_state.get("messages",)
        
        # Obtener la última respuesta del asistente
        final_response = "No response"
        if messages:
            final_response = messages[-1].content
            
        # 2. Registrar Herramientas Usadas
        # Iteramos los mensajes para buscar llamadas a herramientas
        for msg in messages:
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    new_tool_log = ToolsHistory(
                        user_sub=user['sub'],
                        name=tool_call.get('name'),
                        args=json.dumps(tool_call.get('args'))
                    )
                    db.add(new_tool_log)
        
        # 3. Guardar Historial Chat
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

@app.get("/api/history")
async def get_history(request: Request, db: AsyncSession = Depends(get_db)):
    user = request.session.get('user')
    if not user: raise HTTPException(status_code=401)
    
    stmt = select(ChatHistory).where(ChatHistory.user_sub == user['sub']).order_by(desc(ChatHistory.timestamp)).limit(10)
    result = await db.execute(stmt)
    return result.scalars().all()

@app.get("/api/toolshistory")
async def get_tools_history(request: Request, db: AsyncSession = Depends(get_db)):
    user = request.session.get('user')
    if not user: raise HTTPException(status_code=401)
    
    stmt = select(ToolsHistory).where(ToolsHistory.user_sub == user['sub']).order_by(desc(ToolsHistory.timestamp)).limit(15)
    result = await db.execute(stmt)
    return result.scalars().all()