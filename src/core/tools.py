"""
Outils communs pour tous les modules.
Chaque module peut ajouter ses propres outils via le registre.
"""
import json
import os
import re
import subprocess
import threading

TOOL_TIMEOUT = int(os.getenv("TOOL_TIMEOUT", "120"))
MAX_OUTPUT = 100_000  # 100KB max output per tool call

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]|\x1b\].*?\x07|\x1b\(B')

_cancel_events: dict[int, threading.Event] = {}


def register_cancel_event(event: threading.Event):
    _cancel_events[threading.get_ident()] = event


def unregister_cancel_event():
    _cancel_events.pop(threading.get_ident(), None)


def _get_cancel_event():
    return _cancel_events.get(threading.get_ident())


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text)


def _run(cmd: str, timeout: int | None = None, env: dict | None = None, cwd: str = "/workspace") -> dict:
    """Execute une commande shell, interruptible via cancel event."""
    t = timeout or TOOL_TIMEOUT
    run_env = {**os.environ, **(env or {})}
    cancel = _get_cancel_event()
    try:
        proc = subprocess.Popen(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=cwd, env=run_env,
        )

        box = [None, None, False]  # stdout, stderr, timed_out

        def _comm():
            try:
                o, e = proc.communicate(timeout=t)
                box[0], box[1] = o, e
            except subprocess.TimeoutExpired:
                proc.kill()
                o, e = proc.communicate()
                box[0], box[1], box[2] = o or "", e or "", True

        ct = threading.Thread(target=_comm, daemon=True)
        ct.start()
        while ct.is_alive():
            if cancel and cancel.is_set():
                proc.kill()
                ct.join(timeout=5)
                cancel.clear()
                return {"exit_code": -2, "stdout": "", "stderr": "Commande skip par l'utilisateur", "truncated": False, "skipped": True}
            ct.join(timeout=0.5)

        if box[2]:
            return {"exit_code": -1, "stdout": "", "stderr": f"Timeout after {t}s", "truncated": False}

        stdout = _strip_ansi((box[0] or "")[:MAX_OUTPUT])
        stderr = _strip_ansi((box[1] or "")[:MAX_OUTPUT])
        truncated = len(box[0] or "") > MAX_OUTPUT or len(box[1] or "") > MAX_OUTPUT
        return {"exit_code": proc.returncode, "stdout": stdout, "stderr": stderr, "truncated": truncated}
    except Exception as e:
        return {"exit_code": -1, "stdout": "", "stderr": str(e), "truncated": False}


# ========== Common tool execution functions ==========

def exec_run_command(command: str, timeout: int | None = None) -> dict:
    return _run(command, timeout)


def exec_read_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(MAX_OUTPUT)
        return {"exit_code": 0, "stdout": content, "stderr": "", "truncated": len(content) >= MAX_OUTPUT}
    except Exception as e:
        return {"exit_code": 1, "stdout": "", "stderr": str(e), "truncated": False}


def exec_write_file(path: str, content: str) -> dict:
    try:
        resolved = os.path.realpath(path)
        if not resolved.startswith("/workspace"):
            return {"exit_code": 1, "stdout": "", "stderr": "Ecriture interdite hors de /workspace", "truncated": False}
        os.makedirs(os.path.dirname(resolved) if os.path.dirname(resolved) else "/workspace", exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)
        return {"exit_code": 0, "stdout": f"Written {len(content)} bytes to {path}", "stderr": "", "truncated": False}
    except Exception as e:
        return {"exit_code": 1, "stdout": "", "stderr": str(e), "truncated": False}


def exec_web_search(query: str, max_results: int = 5) -> dict:
    """Recherche web via DuckDuckGo HTML (pas d'API key requise)."""
    import requests
    from bs4 import BeautifulSoup
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (LLMTools Agent)"},
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for r in soup.select(".result")[:max_results]:
            title_el = r.select_one(".result__title a, .result__a")
            snippet_el = r.select_one(".result__snippet")
            title = title_el.get_text(strip=True) if title_el else ""
            href = title_el.get("href", "") if title_el else ""
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            if title:
                results.append(f"[{title}]\n  URL: {href}\n  {snippet}")
        output = "\n\n".join(results) if results else "(Aucun résultat trouvé)"
        return {"exit_code": 0, "stdout": output, "stderr": "", "truncated": False}
    except Exception as e:
        return {"exit_code": 1, "stdout": "", "stderr": str(e), "truncated": False}


def exec_web_read(url: str) -> dict:
    """Lit le contenu texte d'une page web."""
    import requests
    from bs4 import BeautifulSoup
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (LLMTools Agent)"},
            timeout=15,
            verify=False,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        if len(text) > MAX_OUTPUT:
            text = text[:MAX_OUTPUT]
        return {"exit_code": 0, "stdout": text, "stderr": "", "truncated": len(text) >= MAX_OUTPUT}
    except Exception as e:
        return {"exit_code": 1, "stdout": "", "stderr": str(e), "truncated": False}


# ========== Common tool dispatchers ==========

COMMON_EXECUTORS = {
    "run_command": lambda args: exec_run_command(
        command=args.get("command", ""),
        timeout=args.get("timeout")
    ),
    "read_file": lambda args: exec_read_file(
        path=args.get("path", "")
    ),
    "write_file": lambda args: exec_write_file(
        path=args.get("path", ""),
        content=args.get("content", "")
    ),
    "web_search": lambda args: exec_web_search(
        query=args.get("query", ""),
        max_results=args.get("max_results", 5)
    ),
    "web_read": lambda args: exec_web_read(
        url=args.get("url", "")
    ),
}


def execute_tool(name: str, arguments: str | dict, executors: dict | None = None) -> dict:
    """Execute un outil par nom. Utilise les executors fournis ou les communs."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return {"exit_code": 1, "stdout": "", "stderr": f"Invalid JSON arguments: {arguments}", "truncated": False}

    all_executors = dict(COMMON_EXECUTORS)
    if executors:
        all_executors.update(executors)

    executor = all_executors.get(name)
    if not executor:
        available = ", ".join(all_executors.keys())
        return {
            "exit_code": 1,
            "stdout": "",
            "stderr": f"'{name}' n'est pas un outil. Utilise run_command avec command=\"{name} ...\". Outils disponibles : {available}",
            "truncated": False,
        }
    return executor(arguments)


# ========== Common OpenAI function definitions ==========

COMMON_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute une commande shell. OBLIGATOIRE pour toute commande non listée comme outil dédié.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 120)"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the filesystem.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path for the file"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Recherche sur internet via DuckDuckGo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Requête de recherche"},
                    "max_results": {"type": "integer", "description": "Nombre max de résultats (défaut: 5)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_read",
            "description": "Lit le contenu texte d'une page web.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL complète de la page à lire"},
                },
                "required": ["url"],
            },
        },
    },
]
