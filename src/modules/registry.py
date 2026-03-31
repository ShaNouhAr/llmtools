"""
Registre central des modules LLMTools.
Chaque module s'enregistre ici avec sa config, son prompt et ses outils.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)

_modules: dict[str, dict[str, Any]] = {}


def register_module(config: dict):
    """
    Enregistre un module. Config attendue :
    - id: str
    - name: str
    - description: str
    - icon: str (emoji)
    - color: str (CSS color)
    - system_prompt: str | callable(workspace_dir) -> str
    - chat_prompt: str (prompt for simple chat mode)
    - tool_definitions: list[dict] (OpenAI function defs, module-specific)
    - tool_executors: dict (name -> callable, module-specific)
    - workspace_dirs: list[str] (subdirs to create in workspace)
    - suggestions: list[dict] (text, label for chat suggestions)
    """
    module_id = config["id"]
    _modules[module_id] = config
    logger.info("Module registered: %s (%s)", module_id, config.get("name", ""))


def get_module(module_id: str) -> dict | None:
    return _modules.get(module_id)


def list_modules() -> list[dict]:
    """Retourne la liste des modules (sans les outils/executors pour l'API)."""
    out = []
    for m in _modules.values():
        out.append({
            "id": m["id"],
            "name": m["name"],
            "description": m["description"],
            "icon": m.get("icon", "🔧"),
            "color": m.get("color", "#6366f1"),
            "suggestions": m.get("suggestions", []),
        })
    return out


def get_module_prompt(module_id: str, workspace_dir: str) -> str:
    """Retourne le system prompt du module, resolu avec le workspace_dir."""
    m = _modules.get(module_id)
    if not m:
        return "Tu es un assistant IA."
    prompt = m.get("system_prompt", "Tu es un assistant IA.")
    if callable(prompt):
        return prompt(workspace_dir)
    return prompt


def get_module_chat_prompt(module_id: str) -> str:
    """Retourne le prompt pour le mode chat simple (sans agent)."""
    m = _modules.get(module_id)
    if not m:
        return "Tu es un assistant IA polyvalent."
    return m.get("chat_prompt", "Tu es un assistant IA polyvalent.")


def get_module_tools(module_id: str) -> tuple[list[dict], dict]:
    """Retourne (tool_definitions, tool_executors) specifiques au module."""
    m = _modules.get(module_id)
    if not m:
        return [], {}
    return m.get("tool_definitions", []), m.get("tool_executors", {})


def get_module_workspace_dirs(module_id: str) -> list[str]:
    m = _modules.get(module_id)
    if not m:
        return []
    return m.get("workspace_dirs", [])
