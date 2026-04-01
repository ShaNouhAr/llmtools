"""
Client LLM generaliste (LM Studio - API OpenAI compatible).
Gere la connexion, la selection de modeles, le streaming chat.
Auto-decouvre LM Studio sur le reseau local.
"""
import json
import logging
import os
import socket
import time
import urllib.request
import urllib.error
from openai import OpenAI
import litellm

# Désactiver les logs verbeux de litellm
litellm.suppress_debug_info = True

logger = logging.getLogger(__name__)

CONFIG_FILE = "/data/config.json"


def _load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_config(config: dict):
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        logger.warning("Failed to save config: %s", e)


DEFAULT_CHAT_SYSTEM_PROMPT = """Tu es un assistant IA polyvalent. Tu peux aider avec divers sujets techniques.
Réponds de façon concise et actionnable."""


_saved_cfg = _load_config()
_active_model: str | None = _saved_cfg.get("active_model")
_provider_mode: str = _saved_cfg.get("provider_mode", "local")
_cloud_model: str = _saved_cfg.get("cloud_model", "gpt-4o")
_api_keys: dict = _saved_cfg.get("api_keys", {"openai": "", "anthropic": "", "gemini": ""})

# Set API keys in environment for litellm
for k, v in _api_keys.items():
    if v:
        os.environ[f"{k.upper()}_API_KEY"] = v

_models_cache: list[dict] = []
_models_cache_ts: float = 0
_MODELS_CACHE_TTL = 30  # seconds

def get_provider_config() -> dict:
    return {
        "provider_mode": _provider_mode,
        "cloud_model": _cloud_model,
        "api_keys": _api_keys
    }

def set_provider_config(mode: str, cloud_model: str, keys: dict):
    global _provider_mode, _cloud_model, _api_keys
    _provider_mode = mode
    if cloud_model:
        _cloud_model = cloud_model
    
    for k, v in keys.items():
        if v is not None:
            _api_keys[k] = v
    
    cfg = _load_config()
    cfg["provider_mode"] = _provider_mode
    cfg["cloud_model"] = _cloud_model
    cfg["api_keys"] = _api_keys
    _save_config(cfg)
    
    for k, v in _api_keys.items():
        if v:
            os.environ[f"{k.upper()}_API_KEY"] = v
            
    logger.info("Provider config updated: %s", _provider_mode)

# ========== Auto-discovery ==========

_CANDIDATE_PORTS = [1234, 1235, 8080]
_discovered_url: str | None = _saved_cfg.get("discovered_url")
_discovery_ts: float = 0
_DISCOVERY_TTL = 120  # retry discovery every 2 min if failed


def _get_candidate_hosts() -> list[str]:
    """Generate candidate hosts where LM Studio might be running."""
    hosts = []
    # 1. host.docker.internal (Docker Desktop standard)
    hosts.append("host.docker.internal")
    # 2. Docker bridge gateway (common on Linux Docker)
    hosts.append("172.17.0.1")
    # 3. Try to resolve the actual gateway IP
    try:
        with open("/proc/net/route", "r") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if parts[1] == "00000000":  # default route
                    hex_ip = parts[2]
                    ip = ".".join(str(int(hex_ip[i:i+2], 16)) for i in (6, 4, 2, 0))
                    if ip not in hosts:
                        hosts.append(ip)
    except Exception:
        pass
    # 4. localhost (if running without Docker)
    hosts.append("127.0.0.1")
    hosts.append("localhost")
    return hosts


def _probe_url(url: str, timeout: float = 2.0) -> bool:
    """Check if a URL responds (try /v1/models endpoint)."""
    try:
        req = urllib.request.Request(url + "/models", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _discover_lm_studio() -> str | None:
    """Try to find LM Studio on the network. Returns base URL or None."""
    global _discovered_url, _discovery_ts

    # If user set an explicit URL via env, try it first
    env_url = os.getenv("LM_STUDIO_BASE_URL", "").strip()
    if env_url:
        if _probe_url(env_url):
            _discovered_url = env_url
            _discovery_ts = time.time()
            logger.info("LM Studio found at env URL: %s", env_url)
            _save_discovered(env_url)
            return env_url

    # Try all candidates
    candidates = _get_candidate_hosts()
    for host in candidates:
        for port in _CANDIDATE_PORTS:
            url = f"http://{host}:{port}/v1"
            if _probe_url(url):
                _discovered_url = url
                _discovery_ts = time.time()
                logger.info("LM Studio auto-discovered at: %s", url)
                _save_discovered(url)
                return url

    logger.warning("LM Studio not found on any candidate address")
    _discovery_ts = time.time()
    return None


def _save_discovered(url: str):
    config = _load_config()
    config["discovered_url"] = url
    _save_config(config)


def _get_base_url() -> str:
    """Get the best known URL for LM Studio, with auto-discovery."""
    global _discovered_url, _discovery_ts

    # If we have a recent discovery, use it
    if _discovered_url and (time.time() - _discovery_ts) < _DISCOVERY_TTL:
        return _discovered_url

    # Try to discover
    found = _discover_lm_studio()
    if found:
        return found

    # Fallback to env or default
    return os.getenv("LM_STUDIO_BASE_URL", "http://host.docker.internal:1234/v1")


if _active_model:
    logger.info("Restored saved model: %s", _active_model)

# Run discovery at import time (startup)
logger.info("Auto-discovering LM Studio...")
_startup_url = _discover_lm_studio()
if _startup_url:
    logger.info("LM Studio ready at: %s", _startup_url)
else:
    logger.warning("LM Studio not found at startup. Will retry on first request.")


# ========== Client ==========

def get_client() -> OpenAI:
    base_url = _get_base_url()
    api_key = os.getenv("LM_STUDIO_API_KEY", "not-needed")
    return OpenAI(base_url=base_url, api_key=api_key)


def get_base_url() -> str:
    """Public accessor for the current LM Studio URL."""
    return _get_base_url()


def set_base_url(url: str):
    """Set a custom LM Studio URL (remote or local)."""
    global _discovered_url, _discovery_ts, _models_cache, _models_cache_ts
    url = url.strip().rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    _discovered_url = url
    _discovery_ts = time.time() + 86400 * 365  # pin for ~1 year
    _models_cache = []
    _models_cache_ts = 0
    config = _load_config()
    config["discovered_url"] = url
    _save_config(config)
    logger.info("LM Studio URL set manually: %s", url)


def get_model() -> str:
    if _provider_mode == "cloud":
        return _cloud_model
    if _active_model:
        return _active_model
    if _models_cache:
        return _models_cache[0]["id"]
    return "local-model"


def set_model(model_id: str):
    global _active_model, _cloud_model, _provider_mode
    config = _load_config()
    if _provider_mode == "cloud":
        _cloud_model = model_id
        config["cloud_model"] = model_id
        logger.info("Modele Cloud actif selectionne et sauvegarde: %s", model_id)
    else:
        _active_model = model_id
        config["active_model"] = model_id
        logger.info("Modele Local actif selectionne et sauvegarde: %s", model_id)
    _save_config(config)


def list_models(client: OpenAI | None = None, force_refresh: bool = False) -> list[dict]:
    global _models_cache, _models_cache_ts
    if not force_refresh and _models_cache and (time.time() - _models_cache_ts) < _MODELS_CACHE_TTL:
        return _models_cache
    if client is None:
        client = get_client()
    try:
        resp = client.models.list()
        _models_cache = [{"id": m.id, "owned_by": getattr(m, "owned_by", "")} for m in resp.data]
        _models_cache_ts = time.time()
        logger.info("Models refreshed: %d found", len(_models_cache))
        return _models_cache
    except Exception as e:
        logger.warning("Impossible de lister les modeles LM Studio: %s", e)
        # Connection failed — force re-discovery next time
        global _discovery_ts
        _discovery_ts = 0
        return _models_cache or []


def check_lm_studio() -> dict:
    """Verifie la connexion a LM Studio. Retourne status + info."""
    if _provider_mode == "cloud":
        return {
            "connected": True,
            "model_count": 0,
            "current_model": _cloud_model,
            "url": "Cloud API (LiteLLM)",
            "provider_mode": "cloud"
        }
    try:
        client = get_client()
        models = list_models(client, force_refresh=True)
        return {
            "connected": True,
            "model_count": len(models),
            "current_model": get_model(),
            "url": _get_base_url(),
            "provider_mode": "local"
        }
    except Exception as e:
        logger.warning("LM Studio health check failed: %s", e)
        return {"connected": False, "error": str(e), "current_model": get_model(), "url": _get_base_url(), "provider_mode": "local"}


def do_completion(**kwargs):
    """Wrapper generique LiteLLM gérant le basculement Local/Cloud."""
    model = kwargs.get("model", get_model())
    
    if _provider_mode == "local":
        kwargs["api_base"] = _get_base_url()
        kwargs["api_key"] = os.getenv("LM_STUDIO_API_KEY", "not-needed")
        if not model.startswith("openai/"):
            kwargs["model"] = f"openai/{model}"
    else:
        kwargs["model"] = model
        
    return litellm.completion(**kwargs)


def chat(messages: list[dict], system_prompt: str | None = None, client: OpenAI | None = None) -> str:
    prompt = system_prompt or DEFAULT_CHAT_SYSTEM_PROMPT
    r = do_completion(
        messages=[{"role": "system", "content": prompt}] + messages,
        temperature=0.4,
        max_tokens=2048,
    )
    if not r.choices:
        return ""
    return (r.choices[0].message.content or "").strip()


def stream_chat(messages: list[dict], system_prompt: str | None = None, client: OpenAI | None = None):
    prompt = system_prompt or DEFAULT_CHAT_SYSTEM_PROMPT
    stream = do_completion(
        messages=[{"role": "system", "content": prompt}] + messages,
        temperature=0.4,
        max_tokens=2048,
        stream=True,
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content

