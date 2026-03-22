"""
Gestion des conversations (chats) : stockage JSON, CRUD. Persistance pour F5.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

CHATS_DIR = Path(os.getenv("LLMTOOLS_CHATS_DIR", "data/chats")).resolve()


def _ensure_dir():
    CHATS_DIR.mkdir(parents=True, exist_ok=True)


def _path(chat_id: str) -> Path:
    return CHATS_DIR / f"{chat_id}.json"


def list_chats(module_id: str | None = None) -> list[dict]:
    """Liste toutes les conversations (metadata + message_count), filtrables par module_id."""
    _ensure_dir()
    out = []
    for f in CHATS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            chat_module_id = data.get("module_id", "")
            if module_id is not None and chat_module_id != module_id:
                continue
            out.append({
                "id": data["id"],
                "title": data.get("title", "Sans titre"),
                "module_id": data.get("module_id", ""),
                "created_at": data["created_at"],
                "updated_at": data.get("updated_at", data["created_at"]),
                "message_count": len(data.get("messages", [])),
            })
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Chat file corrupted: %s — %s", f.name, e)
            continue
    out.sort(key=lambda x: x["updated_at"], reverse=True)
    return out


def get_chat(chat_id: str) -> dict | None:
    """Recupere une conversation complete par ID."""
    p = _path(chat_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Chat corrupted: %s — %s", chat_id, e)
        return None


def create_chat(title: str, messages: list[dict], module_id: str = "") -> dict:
    """Cree une nouvelle conversation."""
    _ensure_dir()
    chat_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "id": chat_id,
        "title": title or "Nouvelle conversation",
        "module_id": module_id,
        "created_at": now,
        "updated_at": now,
        "messages": list(messages),
    }
    _path(chat_id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def update_chat(chat_id: str, *, title: str | None = None, messages: list[dict] | None = None) -> dict | None:
    """Met a jour une conversation existante."""
    data = get_chat(chat_id)
    if not data:
        return None
    if title is not None:
        data["title"] = title
    if messages is not None:
        data["messages"] = list(messages)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _path(chat_id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def delete_chat(chat_id: str) -> bool:
    """Supprime une conversation."""
    p = _path(chat_id)
    if not p.exists():
        return False
    p.unlink()
    return True
