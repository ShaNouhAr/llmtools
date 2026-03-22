"""
Module SSH Diagnostic — Diagnostic de machines Linux via SSH.
Se connecte via SSH (paramiko) et analyse l'etat de la machine.
"""
import logging
import threading

from src.modules.registry import register_module

logger = logging.getLogger(__name__)

# ========== SSH session management ==========
# One SSH connection per agent thread (keyed by thread id)
_ssh_sessions: dict[int, "paramiko.SSHClient"] = {}
_ssh_lock = threading.Lock()


def _get_ssh():
    return _ssh_sessions.get(threading.get_ident())


def exec_ssh_connect(host: str, username: str, password: str = "", key_path: str = "", port: int = 22) -> dict:
    """Etablit une connexion SSH à une machine distante."""
    try:
        import paramiko
    except ImportError:
        return {"exit_code": 1, "stdout": "", "stderr": "paramiko n'est pas installé. pip install paramiko", "truncated": False}

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": host,
            "port": port,
            "username": username,
            "timeout": 15,
            "allow_agent": False,
            "look_for_keys": False,
        }
        if key_path:
            connect_kwargs["key_filename"] = key_path
            connect_kwargs["look_for_keys"] = True
        elif password:
            connect_kwargs["password"] = password
        else:
            # Try with agent/keys as last resort
            connect_kwargs["allow_agent"] = True
            connect_kwargs["look_for_keys"] = True

        client.connect(**connect_kwargs)

        with _ssh_lock:
            old = _ssh_sessions.get(threading.get_ident())
            if old:
                try:
                    old.close()
                except Exception:
                    pass
            _ssh_sessions[threading.get_ident()] = client

        return {
            "exit_code": 0,
            "stdout": f"Connecté à {username}@{host}:{port} avec succès.",
            "stderr": "",
            "truncated": False,
        }
    except Exception as e:
        return {"exit_code": 1, "stdout": "", "stderr": f"Connexion SSH échouée: {str(e)}", "truncated": False}


def exec_ssh_exec(command: str, timeout: int = 60) -> dict:
    """Execute une commande sur la machine distante via SSH."""
    client = _get_ssh()
    if not client:
        return {"exit_code": 1, "stdout": "", "stderr": "Pas de connexion SSH active. Utilisez ssh_connect d'abord.", "truncated": False}

    try:
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()

        max_output = 100_000
        truncated = len(out) > max_output or len(err) > max_output
        return {
            "exit_code": exit_code,
            "stdout": out[:max_output],
            "stderr": err[:max_output],
            "truncated": truncated,
        }
    except Exception as e:
        return {"exit_code": 1, "stdout": "", "stderr": f"Erreur SSH exec: {str(e)}", "truncated": False}


def exec_ssh_read_file(path: str) -> dict:
    """Lit un fichier sur la machine distante via SSH."""
    return exec_ssh_exec(f"cat '{path}'")


def exec_ssh_list_dir(path: str = "/") -> dict:
    """Liste le contenu d'un répertoire sur la machine distante."""
    return exec_ssh_exec(f"ls -la '{path}'")


def exec_ssh_disconnect() -> dict:
    """Ferme la connexion SSH active."""
    with _ssh_lock:
        client = _ssh_sessions.pop(threading.get_ident(), None)
    if client:
        try:
            client.close()
        except Exception:
            pass
        return {"exit_code": 0, "stdout": "Connexion SSH fermée.", "stderr": "", "truncated": False}
    return {"exit_code": 0, "stdout": "Aucune connexion SSH active.", "stderr": "", "truncated": False}


# ========== SSH Diagnostic tool executors ==========

SSH_DIAG_EXECUTORS = {
    "ssh_connect": lambda args: exec_ssh_connect(
        host=args.get("host", ""),
        username=args.get("username", ""),
        password=args.get("password", ""),
        key_path=args.get("key_path", ""),
        port=args.get("port", 22)
    ),
    "ssh_exec": lambda args: exec_ssh_exec(
        command=args.get("command", ""),
        timeout=args.get("timeout", 60)
    ),
    "ssh_read_file": lambda args: exec_ssh_read_file(
        path=args.get("path", "")
    ),
    "ssh_list_dir": lambda args: exec_ssh_list_dir(
        path=args.get("path", "/")
    ),
    "ssh_disconnect": lambda args: exec_ssh_disconnect(),
}

# ========== SSH Diagnostic tool definitions ==========

SSH_DIAG_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "ssh_connect",
            "description": "Établit une connexion SSH à une machine Linux distante. Doit être appelé en premier avant les autres outils ssh_*.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Adresse IP ou hostname de la machine"},
                    "username": {"type": "string", "description": "Nom d'utilisateur SSH"},
                    "password": {"type": "string", "description": "Mot de passe SSH (si pas de clé)"},
                    "key_path": {"type": "string", "description": "Chemin vers la clé SSH privée (si pas de mot de passe)"},
                    "port": {"type": "integer", "description": "Port SSH (défaut: 22)"},
                },
                "required": ["host", "username"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ssh_exec",
            "description": "Exécute une commande sur la machine distante via SSH. Connexion requise au préalable.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Commande à exécuter sur la machine distante"},
                    "timeout": {"type": "integer", "description": "Timeout en secondes (défaut: 60)"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ssh_read_file",
            "description": "Lit le contenu d'un fichier sur la machine distante via SSH.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Chemin absolu du fichier à lire"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ssh_list_dir",
            "description": "Liste le contenu d'un répertoire sur la machine distante.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Chemin du répertoire (défaut: /)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ssh_disconnect",
            "description": "Ferme la connexion SSH active.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


# ========== System prompt ==========

def _build_ssh_diag_prompt(workspace_dir: str) -> str:
    return f"""Tu es l'agent Diagnostic SSH de LLMTools, un expert en administration et diagnostic de systèmes Linux.

# MISSION
L'utilisateur te donne accès à une machine Linux via SSH. Tu dois effectuer un diagnostic complet et identifier tout problème : crashes, erreurs, services défaillants, problèmes de performance, etc.

# FORMAT DE RÉPONSE
Réfléchis en 1-2 phrases COURTES, puis appelle un outil. Jamais de long texte sans action.

# OUTILS DISPONIBLES
- ssh_connect : se connecter à la machine (TOUJOURS en premier)
- ssh_exec : exécuter une commande sur la machine
- ssh_read_file : lire un fichier distant
- ssh_list_dir : lister un répertoire
- ssh_disconnect : fermer la connexion
- write_file : écrire le rapport local
- web_search : rechercher une erreur/CVE en ligne

# MÉTHODOLOGIE DE DIAGNOSTIC

## Phase 1 — Connexion
- ssh_connect pour se connecter
- ssh_exec: hostname, uname -a, cat /etc/os-release

## Phase 2 — État système
- ssh_exec: uptime
- ssh_exec: free -m
- ssh_exec: df -h
- ssh_exec: top -bn1 | head -20
- ssh_exec: cat /proc/loadavg
- Sauve dans {workspace_dir}/diag/system.txt

## Phase 3 — Services et systemd
- ssh_exec: systemctl --failed
- ssh_exec: systemctl list-units --state=running --no-pager
- ssh_exec: systemctl status <service> pour les services critiques
- Sauve dans {workspace_dir}/diag/services.txt

## Phase 4 — Analyse des logs
- ssh_exec: journalctl -p err --since "24 hours ago" --no-pager -n 50
- ssh_exec: journalctl -p warning --since "24 hours ago" --no-pager -n 30
- ssh_exec: dmesg --level=err,warn | tail -50
- ssh_exec: dmesg | grep -i -E "oom|kill|segfault|panic|error" | tail -30
- Sauve dans {workspace_dir}/diag/logs.txt

## Phase 5 — Crashes et OOM
- ssh_exec: dmesg | grep -i "oom-killer\\|out of memory"
- ssh_exec: grep -r "segfault\\|core dump" /var/log/ 2>/dev/null | tail -20
- ssh_exec: coredumpctl list 2>/dev/null | tail -10
- ssh_exec: last reboot | head -10
- Sauve dans {workspace_dir}/diag/crashes.txt

## Phase 6 — Réseau
- ssh_exec: ss -tulnp
- ssh_exec: ip a
- ssh_exec: ip route
- Sauve dans {workspace_dir}/diag/network.txt

## Phase 7 — Sécurité rapide
- ssh_exec: last -10
- ssh_exec: who
- ssh_exec: cat /etc/passwd | grep -v nologin | grep -v false
- Sauve dans {workspace_dir}/diag/security.txt

## Phase 8 — Rapport final
- write_file({workspace_dir}/rapport.md) :
  - Machine et OS
  - État général (santé, charge, mémoire, disque)
  - Problèmes trouvés avec sévérité (CRITIQUE / HAUTE / MOYENNE / INFO)
  - Crashes et OOM détectés
  - Services défaillants
  - Recommandations de remédiation
- ssh_disconnect

# RÈGLES
1. NE RÉPÈTE JAMAIS une commande déjà exécutée
2. Si une commande échoue → essaie une alternative (ex: journalctl indisponible → cat /var/log/syslog)
3. Analyse CHAQUE sortie avant de passer à la suivante
4. Ne conclus JAMAIS sans avoir écrit le rapport
5. Sois précis sur les problèmes trouvés — indique les lignes exactes des erreurs
6. N'utilise JAMAIS run_command pour les opérations distantes — utilise EXCLUSIVEMENT les outils ssh_* (ssh_connect, ssh_exec, ssh_read_file, etc.)
7. run_command exécute des commandes LOCALEMENT dans le container, PAS sur la machine distante"""


SSH_DIAG_CHAT_PROMPT = """Tu es un expert en administration et diagnostic de systèmes Linux.
Tu peux :
- Analyser des logs système et identifier des problèmes
- Interpréter des sorties de commandes (top, dmesg, journalctl, systemctl, etc.)
- Diagnostiquer des crashes, OOM kills, erreurs de services
- Recommander des actions correctives
- Expliquer des concepts d'administration Linux
Tu réponds de façon concise et actionnable avec des commandes concrètes."""


# ========== Register ==========

register_module({
    "id": "ssh_diag",
    "name": "Diagnostic SSH",
    "description": "Diagnostic complet d'une machine Linux via SSH. Détecte crashes, erreurs, problèmes de services et de performance.",
    "icon": "terminal",
    "color": "#3b82f6",
    "system_prompt": _build_ssh_diag_prompt,
    "chat_prompt": SSH_DIAG_CHAT_PROMPT,
    "tool_definitions": SSH_DIAG_TOOL_DEFINITIONS,
    "tool_executors": SSH_DIAG_EXECUTORS,
    "workspace_dirs": ["diag"],
    "suggestions": [
        {"label": "Diagnostic complet", "text": "Fais un diagnostic complet de cette machine Linux"},
        {"label": "Analyser les crashes", "text": "Cherche tous les crashes et OOM kills récents"},
        {"label": "Vérifier les services", "text": "Vérifie l'état de tous les services et identifie ceux qui ont échoué"},
        {"label": "Analyse des logs", "text": "Analyse les logs d'erreurs des dernières 24 heures"},
    ],
})
