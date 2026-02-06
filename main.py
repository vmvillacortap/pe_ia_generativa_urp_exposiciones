import os
import asyncio
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from authlib.integrations.starlette_client import OAuth
from starlette.middleware.sessions import SessionMiddleware
from starlette.config import Config
from sqlalchemy.orm import Session
from sqlalchemy import select,desc
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from database import get_db, User, ClienteEmpresa, ChatHistory, ToolsHistory, DetalleCliente, engine
from agent import run_agent_query

load_dotenv()
#init_db()
#asyncio.run(init_db())
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestión del ciclo de vida del servidor."""
    # Startup: Crear tablas si no existen
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield  # La aplicación está activa
    
    # Shutdown: Cerrar el pool de conexiones de forma limpia
    await engine.dispose()

app = FastAPI(
    title="AI Agent Production API (SQLAlchemy >= 2.0)",
    lifespan=lifespan
)

app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "secret"))
templates = Jinja2Templates(directory="templates")

oauth = OAuth(Config(environ=os.environ))
oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

@app.get("/login")
async def login(request: Request):
    redirect_uri = request.url_for('auth_callback')
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get("/auth/callback")
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get('userinfo')
        user_db = db.query(User).filter(User.google_sub == user_info['sub']).first()
        if not user_db:
            new_user = User(google_sub=user_info['sub'], email=user_info['email'], name=user_info['name'], picture=user_info['picture'])
            db.add(new_user)
            db.commit()
        request.session['user'] = dict(user_info)
        return RedirectResponse(url='/chat')
    except Exception as e:
        return f"Error auth: {e}"

@app.get("/logout")
async def logout(request: Request):
    request.session.pop('user', None)
    return RedirectResponse(url='/')

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return RedirectResponse(url='/chat') if request.session.get('user') else templates.TemplateResponse("login.html", {"request": request})

@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    user = request.session.get('user')
    if not user: return RedirectResponse(url='/login')
    return templates.TemplateResponse("chat.html", {"request": request, "user": user})

# --- API ENDPOINTS ---

@app.get("/api/history")
async def get_chat_history(request: Request, db: Session = Depends(get_db)):
    user = request.session.get('user')
    if not user: raise HTTPException(status_code=401)
    
    # Obtener últimas 10 consultas del usuario
    history = db.query(ChatHistory).filter(
        ChatHistory.user_sub == user['sub']
    ).order_by(
        desc(ChatHistory.timestamp)
    ).limit(10).all()

    return history

@app.get("/api/toolshistory")
async def get_tools_history(request: Request, db: Session = Depends(get_db)):
    user = request.session.get('user')
    if not user: raise HTTPException(status_code=401)
    
    # Obtener últimas 15 consultas del usuario
    # 1. Build the statement

    stmt = select(User).where(User.id == user_id)

    # 2. Execute and get result
    result = await session.execute(stmt)

    # 3. Extract the actual object (scalars)
    user = result.scalar_one_or_none()


    tools_history = db.query(ToolsHistory).filter(
        ToolsHistory.user_sub == user['sub']
    ).order_by(
        desc(ToolsHistory.timestamp)
    ).limit(15).all()
    
    return tools_history

@app.post("/api/chat")
async def chat_endpoint(request: Request, db: Session = Depends(get_db)):
    user = request.session.get('user')
    if not user: raise HTTPException(status_code=401)
    
    data = await request.json()
    query_text = data.get("message")
    
    # 1. Ejecutar Agente
    response_struct = run_agent_query(query_text, user['sub'])

    error = ''
    try:
        for rastreo in response_struct["messages"]:
            for rastro in rastreo:
                if 'tool_calls' in rastro:
                    huella = rastro[-1]

                    if len(huella) == 0:
                        continue
          
                    detalle = huella[0]
                    new_tool = ToolsHistory(
                        user_sub=user['sub'],
                        name=detalle.get('name', ''),
                        args=str(detalle.get('args', '')),
                    )
                    db.add(new_tool)
    except Exception as e:
        error = str(e)

    response_text = response_struct["messages"][-1].content
    
    # 2. Guardar en Historial DB
    new_chat = ChatHistory(
        user_sub=user['sub'], 
        query=query_text, 
        response=response_text
    )
    db.add(new_chat)
    db.commit()
    
    return {"response": response_text, "error": error}

@app.get("/seed_data")
def seed_data(db: Session = Depends(get_db)):
    if not db.query(ClienteEmpresa).first():
        db.add_all([
            ClienteEmpresa(ruc_empresa="20489411921", nombre_empresa="Tech Solutions SAC"),
            ClienteEmpresa(ruc_empresa="20100053455", nombre_empresa="IBK Interbank"),
            ClienteEmpresa(ruc_empresa="20100070970", nombre_empresa="Plaza Vea SUPERMERCADOS PERUANOS SOCIEDAD ANONIMA"),
            DetalleCliente(ruc_empresa="20100070970", monto_transacciones=11000.50, saldo_activo=300, saldo_pasivo=2000, uso_de_app=31, prediccion_compra=0.45, hizo_compra=1),
            DetalleCliente(ruc_empresa="20489411921", monto_transacciones=15000.50, saldo_activo=5000, saldo_pasivo=200, uso_de_app=85, prediccion_compra=0.9, hizo_compra=1),
            DetalleCliente(ruc_empresa="20100053455", monto_transacciones=2000.00, saldo_activo=100, saldo_pasivo=5000, uso_de_app=10, prediccion_compra=0.1, hizo_compra=0)
        ])
        db.commit()
        return {"status": "Datos creados"}
    return {"status": "Datos ya existen"}
