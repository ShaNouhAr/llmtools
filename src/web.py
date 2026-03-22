"""
Interface web FastAPI : LLMTools — plateforme multi-modules avec LLM.
"""
import logging
import os
import json
import re
import uuid
import asyncio
import threading
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from openai import APIConnectionError
import httpx

from src.core.agent import get_client, get_model, set_model, list_models, check_lm_studio, stream_chat, get_base_url
from src.core.agent_loop import agent_loop, get_session
from src.core.tools import register_cancel_event, unregister_cancel_event
from src.core import chats
from src.modules.registry import list_modules, get_module, get_module_prompt, get_module_chat_prompt, get_module_tools, get_module_workspace_dirs

# Import modules to trigger their registration
import src.modules.pentest  # noqa: F401
import src.modules.ssh_diag  # noqa: F401

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(BASE, "templates")
STATIC = os.path.join(BASE, "static")
WORKSPACE_ROOT = Path("/workspace")

os.makedirs(chats.CHATS_DIR, exist_ok=True)

_skip_events: dict[str, threading.Event] = {}

_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)


def _validate_chat_id(chat_id: str):
    if not _UUID_RE.match(chat_id):
        raise HTTPException(400, "ID de conversation invalide")


def _get_workspace(chat_id: str, module_id: str = "") -> Path:
    """Retourne le dossier workspace pour un chat, le cree si besoin."""
    _validate_chat_id(chat_id)
    ws = WORKSPACE_ROOT / chat_id
    # Create module-specific subdirs
    dirs = get_module_workspace_dirs(module_id) if module_id else []
    for sub in dirs:
        (ws / sub).mkdir(parents=True, exist_ok=True)
    ws.mkdir(parents=True, exist_ok=True)
    return ws


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("LLMTools starting up... Modules: %s", [m['id'] for m in list_modules()])
    yield
    logger.info("LLMTools shutting down.")


app = FastAPI(title="LLMTools", lifespan=lifespan)

# --- Jinja Templates ---
templates = Jinja2Templates(directory="templates")

# SVG Icons dictionary for professional look instead of emojis
SVG_ICONS = {
    "shield": '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>',
    "terminal": '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line></svg>',
    "zap": '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>',
    "default": '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>'
}

def render_icon(name: str, class_name: str = "") -> str:
    svg = SVG_ICONS.get(name, SVG_ICONS["default"])
    if class_name:
        svg = svg.replace("<svg ", f'<svg class="{class_name}" ')
    return svg

templates.env.globals["render_icon"] = render_icon

app.mount("/static", StaticFiles(directory="static"), name="static")


# --- API Models ---
class ChatRequest(BaseModel):
    messages: list[dict]
    module_id: str = ""

class AgentRequest(BaseModel):
    messages: list[dict]
    auto_mode: bool = True
    chat_id: str | None = None
    module_id: str = "pentest"

class ApprovalRequest(BaseModel):
    session_id: str
    approved: bool

class ChatCreate(BaseModel):
    title: str
    messages: list[dict]
    module_id: str = ""

class ChatUpdate(BaseModel):
    title: str | None = None
    messages: list[dict] | None = None


# --- Model Store Schemas ---
class ModelHubSearch(BaseModel):
    query: str

class ModelDownloadRequest(BaseModel):
    model_id: str


# --- Pages ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "model": get_model(),
        "modules": list_modules(),
    })


def _chat_page_context(chat=None, module_id=""):
    return {
        "model": get_model(),
        "chat": chat,
        "chats": chats.list_chats(module_id),
        "modules": list_modules(),
        "current_module": get_module(module_id) if module_id else None,
        "module_id": module_id,
    }


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request, module: str = ""):
    return templates.TemplateResponse("chat.html", {"request": request, **_chat_page_context(None, module)})


@app.get("/chat/{chat_id}", response_class=HTMLResponse)
async def chat_with_id_page(request: Request, chat_id: str):
    c = chats.get_chat(chat_id)
    if not c:
        raise HTTPException(404, "Conversation introuvable")
    module_id = c.get("module_id", "")
    return templates.TemplateResponse("chat.html", {"request": request, **_chat_page_context(c, module_id)})

@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    return templates.TemplateResponse("config.html", {"request": request, "model": get_model()})


@app.get("/models", response_class=HTMLResponse)
async def models_page(request: Request):
    return templates.TemplateResponse("models.html", {"request": request, "model": get_model()})



# --- API Modules ---
@app.get("/api/modules")
async def api_list_modules():
    return {"modules": list_modules()}


# --- API Chat (streaming SSE) ---
@app.post("/api/chat/stream")
async def api_chat_stream(body: ChatRequest):
    client = get_client()
    chat_prompt = get_module_chat_prompt(body.module_id) if body.module_id else None
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    _SENTINEL = object()

    def _stream_in_thread():
        full = ""
        try:
            for token in stream_chat(body.messages, system_prompt=chat_prompt, client=client):
                full += token
                loop.call_soon_threadsafe(queue.put_nowait, {"token": token})
            loop.call_soon_threadsafe(queue.put_nowait, {"done": True, "full": full})
        except (APIConnectionError, httpx.ConnectError) as e:
            msg = (
                "Impossible de joindre LM Studio. Vérifiez que le serveur local est démarré (port 1234) "
                "et qu'il écoute sur toutes les interfaces (0.0.0.0)."
            )
            loop.call_soon_threadsafe(queue.put_nowait, {"error": msg, "detail": str(e)})
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, {"error": "Erreur LLM: " + str(e)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

    async def generate():
        t = threading.Thread(target=_stream_in_thread, daemon=True)
        t.start()
        while True:
            data = await queue.get()
            if data is _SENTINEL:
                break
            yield f"data: {json.dumps(data)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- API Agent (tool calling loop, streaming SSE) ---
@app.post("/api/agent/stream")
async def api_agent_stream(body: AgentRequest):
    client = get_client()
    model = get_model()
    module_id = body.module_id
    session_id = str(uuid.uuid4()) if not body.auto_mode else None

    chat_id = body.chat_id or str(uuid.uuid4())
    workspace = _get_workspace(chat_id, module_id)
    system_prompt = get_module_prompt(module_id, str(workspace))
    tool_defs, tool_execs = get_module_tools(module_id)

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    _SENTINEL = object()

    loop.call_soon_threadsafe(
        queue.put_nowait,
        {"type": "workspace", "chat_id": chat_id, "path": str(workspace), "module_id": module_id},
    )

    skip_event = threading.Event()
    _skip_events[chat_id] = skip_event

    def _run_agent_in_thread():
        register_cancel_event(skip_event)
        try:
            for event in agent_loop(
                messages=body.messages,
                client=client,
                model=model,
                system_prompt=system_prompt,
                tool_definitions=tool_defs,
                tool_executors=tool_execs,
                auto_mode=body.auto_mode,
                session_id=session_id,
            ):
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except (APIConnectionError, httpx.ConnectError) as e:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "content": "Impossible de joindre LM Studio: " + str(e)},
            )
        except Exception as e:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "content": "Erreur agent: " + str(e)},
            )
        finally:
            unregister_cancel_event()
            _skip_events.pop(chat_id, None)
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

    async def generate():
        t = threading.Thread(target=_run_agent_in_thread, daemon=True)
        t.start()
        while True:
            event = await queue.get()
            if event is _SENTINEL:
                break
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class SkipRequest(BaseModel):
    chat_id: str

@app.post("/api/agent/skip")
async def api_agent_skip(body: SkipRequest):
    ev = _skip_events.get(body.chat_id)
    if ev:
        ev.set()
        return {"ok": True}
    return {"ok": False, "error": "No active agent for this chat"}


@app.post("/api/agent/approve")
async def api_agent_approve(body: ApprovalRequest):
    session = get_session(body.session_id)
    if not session:
        raise HTTPException(404, "Session introuvable ou expirée")
    if not session.waiting_for_approval:
        raise HTTPException(400, "Pas de tool call en attente")
    if body.approved:
        session.approve()
    else:
        session.reject()
    return {"ok": True}


# --- API Workspace ---
@app.get("/api/workspace/{chat_id}")
async def api_workspace_list(chat_id: str):
    _validate_chat_id(chat_id)
    ws = WORKSPACE_ROOT / chat_id
    if not ws.exists():
        return {"files": [], "chat_id": chat_id}

    files = []
    for p in sorted(ws.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(ws)).replace("\\", "/")
            files.append({
                "path": rel,
                "size": p.stat().st_size,
                "dir": str(p.parent.relative_to(ws)).replace("\\", "/") if p.parent != ws else "",
            })
    return {"files": files, "chat_id": chat_id}


@app.get("/api/workspace/{chat_id}/{file_path:path}")
async def api_workspace_read(chat_id: str, file_path: str):
    _validate_chat_id(chat_id)
    ws = WORKSPACE_ROOT / chat_id
    target = (ws / file_path).resolve()
    if not str(target).startswith(str(ws.resolve())):
        raise HTTPException(403, "Acces interdit")
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "Fichier introuvable")

    content = target.read_text(encoding="utf-8", errors="replace")
    if file_path.endswith(".md"):
        return PlainTextResponse(content, media_type="text/markdown; charset=utf-8")
    return PlainTextResponse(content, media_type="text/plain; charset=utf-8")


@app.post("/api/chat")
async def api_chat(body: ChatRequest):
    from src.core.agent import chat as do_chat
    chat_prompt = get_module_chat_prompt(body.module_id) if body.module_id else None
    try:
        reply = do_chat(body.messages, system_prompt=chat_prompt)
        return {"reply": reply}
    except (APIConnectionError, httpx.ConnectError) as e:
        raise HTTPException(503, "Impossible de joindre LM Studio.") from e


# --- API Chats ---
@app.get("/api/chats")
async def api_list_chats():
    return {"chats": chats.list_chats()}

@app.get("/api/chats/{chat_id}")
async def api_get_chat(chat_id: str):
    c = chats.get_chat(chat_id)
    if not c:
        raise HTTPException(404, "Conversation introuvable")
    return c

@app.post("/api/chats")
async def api_create_chat(body: ChatCreate):
    return chats.create_chat(body.title, body.messages, module_id=body.module_id)

@app.patch("/api/chats/{chat_id}")
async def api_update_chat(chat_id: str, body: ChatUpdate):
    out = chats.update_chat(chat_id, title=body.title, messages=body.messages)
    if not out:
        raise HTTPException(404, "Conversation introuvable")
    return out

@app.delete("/api/chats/{chat_id}")
async def api_delete_chat(chat_id: str):
    if not chats.delete_chat(chat_id):
        raise HTTPException(404, "Conversation introuvable")
    return {"ok": True}


# --- API Config / Models ---
class ModelSelect(BaseModel):
    model_id: str

@app.get("/api/models")
async def api_list_models():
    loop = asyncio.get_event_loop()
    client = get_client()
    models = await loop.run_in_executor(None, lambda: list_models(client))
    current = get_model()
    return {"models": models, "current": current}

@app.post("/api/models/select")
async def api_select_model(body: ModelSelect):
    set_model(body.model_id)
    return {"ok": True, "model": body.model_id}

@app.get("/api/models/search")
async def api_models_search(query: str = ""):
    """Searches HuggingFace Hub specifically for GGUF format models."""
    if not query.strip():
        return {"results": []}
    
    hf_url = "https://huggingface.co/api/models"
    params = {
        "search": query,
        "filter": "gguf",
        "sort": "downloads",
        "direction": "-1",
        "limit": 20
    }
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(hf_url, params=params, timeout=10.0)
            resp.raise_for_status()
            models = resp.json()
            # Clean up the payload before sending to frontend
            results = []
            for m in models:
                results.append({
                    "id": m.get("id"),
                    "downloads": m.get("downloads", 0),
                    "likes": m.get("likes", 0),
                    "tags": m.get("tags", []),
                    "author": m.get("author", "unknown")
                })
            return {"results": results}
        except Exception as e:
            logger.error("HuggingFace search failed: %s", e)
            raise HTTPException(502, "Erreur lors de la recherche sur HuggingFace.")

@app.post("/api/models/download")
async def api_models_download(body: ModelDownloadRequest):
    """Triggers LM Studio to download the specified model via its experimental API."""
    base_url = get_base_url()
    # Replace the typical /v1 suffix with the new download endpoint
    lm_api = base_url.replace("/v1", "/api/v1/models/download") if base_url.endswith("/v1") else base_url + "/models/download"
    
    # LM Studio download payload
    payload = {
        "model": body.model_id
    }
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(lm_api, json=payload, timeout=30.0)
            # 200 or 202 is generally accepted for triggered downloads
            if resp.status_code >= 400:
                logger.error("LM Studio download error: %s", resp.text)
                raise HTTPException(resp.status_code, "Échec du téléchargement dans LM Studio.")
            return {"ok": True, "message": "Téléchargement démarré dans LM Studio."}
        except httpx.ConnectError:
            raise HTTPException(503, "Impossible de joindre LM Studio pour le téléchargement.")
        except Exception as e:
            logger.error("Download trigger failed: %s", e)
            raise HTTPException(500, str(e))

@app.get("/api/config")
async def api_get_config():
    base_url = get_base_url()
    return {
        "lm_studio_url": base_url + " (auto-discovered)",
        "current_model": get_model(),
        "tool_timeout": int(os.getenv("TOOL_TIMEOUT", "120")),
        "max_iterations": int(os.getenv("AGENT_MAX_ITERATIONS", "50")),
    }


# --- Health & Dashboard ---
@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})


@app.get("/api/dashboard")
async def api_dashboard():
    loop = asyncio.get_event_loop()
    lm = await loop.run_in_executor(None, check_lm_studio)
    chat_list = chats.list_chats()
    return {
        "lm_studio": lm,
        "chats_count": len(chat_list),
        "last_chat": chat_list[0] if chat_list else None,
        "modules": list_modules(),
    }
