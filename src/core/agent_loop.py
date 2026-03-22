"""
Boucle agent avec tool calling pour LM Studio (API OpenAI compatible).
Version generique : accepte tools et prompt en parametre depuis le module.
"""
import json
import logging
import os
import threading
import time
from openai import OpenAI

from src.core.tools import COMMON_EXECUTORS, COMMON_TOOL_DEFINITIONS, execute_tool

logger = logging.getLogger(__name__)

MAX_ITERATIONS = int(os.getenv("AGENT_MAX_ITERATIONS", "50"))
MAX_CONTEXT_MESSAGES = 60
MSG_MAX_CHARS = 3000


def _brief_result(result: dict, max_len: int = 120) -> str:
    if result.get("skipped"):
        return "SKIP par l'utilisateur"
    if result.get("exit_code") == -1:
        stderr = result.get("stderr", "")
        if "Timeout" in stderr:
            return "Timeout"
        return f"Erreur: {stderr[:80]}" if stderr else "Erreur"
    stdout = (result.get("stdout") or "").strip()
    stderr = (result.get("stderr") or "").strip()
    text = stdout or stderr or "(vide)"
    first_line = text.split('\n')[0].strip()
    if len(first_line) > max_len:
        first_line = first_line[:max_len] + "..."
    return first_line


def _build_progress(executed_log: list[dict]) -> str:
    if not executed_log:
        return "HISTORIQUE: aucune action encore. Commence par la première étape."
    lines = ["=== ACTIONS DÉJÀ EFFECTUÉES (NE PAS RÉPÉTER) ==="]
    for entry in executed_log:
        status = "[ERR]" if entry.get("failed") else "[OK]"
        lines.append(f"{status} [{entry['tool']}] {entry['preview']} → {entry['summary']}")
    lines.append("")
    lines.append("INTERDIT de relancer une commande ci-dessus. Passe à l'étape suivante non encore effectuée.")
    return "\n".join(lines)


def _format_tool_result(result: dict) -> str:
    parts = []
    if result.get("stdout"):
        parts.append(result["stdout"])
    if result.get("stderr"):
        parts.append(f"[stderr] {result['stderr']}")
    if result.get("truncated"):
        parts.append("[output truncated]")
    text = "\n".join(parts) or "(no output)"
    if len(text) > MSG_MAX_CHARS:
        text = text[:MSG_MAX_CHARS] + "\n[... output tronqué pour le contexte]"
    return text


def _build_command_preview(tool_name: str, args: dict) -> str:
    previews = {
        "run_command": lambda a: a.get("command", ""),
        "nmap_scan": lambda a: f"nmap {a.get('options', '-sV -sC')} {a.get('target', '')}",
        "sqlmap_test": lambda a: f"sqlmap -u '{a.get('url', '')}' {a.get('options', '--batch --smart')}",
        "gobuster_scan": lambda a: f"gobuster dir -u '{a.get('url', '')}' -w {a.get('wordlist', 'common.txt')}",
        "nikto_scan": lambda a: f"nikto -h '{a.get('target', '')}'",
        "hydra_bruteforce": lambda a: f"hydra ... {a.get('target', '')} {a.get('service', '')}",
        "nuclei_scan": lambda a: f"nuclei -u '{a.get('target', '')}'",
        "searchsploit": lambda a: f"searchsploit '{a.get('query', '')}'",
        "whatweb": lambda a: f"whatweb '{a.get('target', '')}'",
        "ffuf": lambda a: f"ffuf -u '{a.get('url', '')}'",
        "masscan": lambda a: f"masscan {a.get('target', '')} -p{a.get('ports', '1-65535')}",
        "crackmapexec": lambda a: f"crackmapexec {a.get('protocol', 'smb')} {a.get('target', '')}",
        "read_file": lambda a: f"cat {a.get('path', '')}",
        "write_file": lambda a: f"write -> {a.get('path', '')}",
        "web_search": lambda a: f"search: {a.get('query', '')}",
        "web_read": lambda a: f"read: {a.get('url', '')}",
        "ssh_exec": lambda a: f"ssh$ {a.get('command', '')}",
        "ssh_read_file": lambda a: f"ssh:cat {a.get('path', '')}",
        "ssh_list_dir": lambda a: f"ssh:ls {a.get('path', '')}",
        "ssh_connect": lambda a: f"ssh -> {a.get('host', '')}",
        "ssh_disconnect": lambda a: "ssh disconnect",
    }
    fn = previews.get(tool_name)
    return fn(args) if fn else tool_name


def _make_call_signature(tool_name: str, tool_args: dict) -> str:
    return f"{tool_name}::{json.dumps(tool_args, sort_keys=True)}"


def _trim_context(messages: list[dict]) -> list[dict]:
    if len(messages) <= MAX_CONTEXT_MESSAGES + 1:
        return messages

    system = messages[0]
    rest = messages[1:]
    keep_full = rest[-MAX_CONTEXT_MESSAGES:]
    old = rest[:-MAX_CONTEXT_MESSAGES]

    trimmed = [system]
    for msg in old:
        if msg.get("role") == "tool":
            content = msg.get("content", "")
            if len(content) > 200:
                trimmed.append({**msg, "content": content[:200] + "\n[... tronqué]"})
            else:
                trimmed.append(msg)
        elif msg.get("role") == "assistant" and msg.get("tool_calls"):
            trimmed.append(msg)
        else:
            if len(msg.get("content", "")) > 300:
                trimmed.append({**msg, "content": msg["content"][:300] + "\n[... tronqué]"})
            else:
                trimmed.append(msg)
    trimmed.extend(keep_full)
    return trimmed


_COMPLETE_MARKERS = ('terminé', 'récap', 'résumé', 'conclusion', 'rapport final', 'complet', 'bonne continuation', 'diagnostic terminé')


def _should_continue(content: str, finish_reason: str | None, cont_count: int, max_cont: int, iteration: int, max_iter: int) -> bool:
    if cont_count >= max_cont:
        return False
    if iteration >= max_iter - 3:
        return False
    if finish_reason == "length":
        return True
    stripped = content.rstrip()
    if not stripped:
        return False
    if stripped[-1] in '.!?:…»"\')':
        return False
    lower = stripped.lower()
    for marker in _COMPLETE_MARKERS:
        if marker in lower:
            return False
    return True


class AgentSession:
    def __init__(self):
        self._approval_event = threading.Event()
        self._approved = False
        self._waiting = False

    @property
    def waiting_for_approval(self):
        return self._waiting

    def request_approval(self) -> bool:
        self._waiting = True
        self._approval_event.clear()
        self._approval_event.wait(timeout=300)
        self._waiting = False
        return self._approved

    def approve(self):
        self._approved = True
        self._approval_event.set()

    def reject(self):
        self._approved = False
        self._approval_event.set()


_sessions: dict[str, tuple[AgentSession, float]] = {}
_SESSION_TTL = 600


def _cleanup_sessions():
    now = time.time()
    expired = [k for k, (_, ts) in _sessions.items() if now - ts > _SESSION_TTL]
    for k in expired:
        del _sessions[k]


def get_session(session_id: str) -> AgentSession | None:
    entry = _sessions.get(session_id)
    if entry is None:
        return None
    return entry[0]


def agent_loop(
    messages: list[dict],
    client: OpenAI,
    model: str,
    system_prompt: str,
    tool_definitions: list[dict] | None = None,
    tool_executors: dict | None = None,
    auto_mode: bool = True,
    session_id: str | None = None,
):
    """
    Boucle agent generique.
    tool_definitions et tool_executors sont fournis par le module actif.
    S'ils ne sont pas fournis, seuls les outils communs sont disponibles.
    """
    _cleanup_sessions()
    session = None
    if not auto_mode and session_id:
        session = AgentSession()
        _sessions[session_id] = (session, time.time())

    # Merge common + module-specific tools
    all_definitions = list(COMMON_TOOL_DEFINITIONS)
    if tool_definitions:
        all_definitions.extend(tool_definitions)

    all_executors = dict(COMMON_EXECUTORS)
    if tool_executors:
        all_executors.update(tool_executors)

    full_messages = [{"role": "system", "content": system_prompt}] + messages
    logger.info("Agent loop started | model=%s auto=%s iterations_max=%d msgs=%d",
                model, auto_mode, MAX_ITERATIONS, len(messages))

    yield {"type": "status", "content": "Analyse de la demande..."}

    call_counts: dict[str, int] = {}
    executed_log: list[dict] = []
    rapport_written = False
    conclude_next = False
    continuation_count = 0
    MAX_CONTINUATIONS = 3

    for iteration in range(MAX_ITERATIONS):
        step_num = iteration + 1

        full_messages = _trim_context(full_messages)

        if conclude_next:
            yield {"type": "status", "content": "Rapport ecrit — Recap final..."}
            recap_prompt = (
                "Le rapport a été écrit. Fais un RÉCAP FINAL structuré en markdown.\n\n"
                "## Récapitulatif\n"
                "- Résumé des actions effectuées\n"
                "- Problèmes/résultats trouvés avec sévérité\n"
                "- Recommandations clés\n\n"
                "## Et maintenant ?\n"
                "Propose 2 à 4 suites concrètes. "
                "Formule chaque proposition comme une question courte. Pas d'outils."
            )
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=full_messages + [{"role": "system", "content": recap_prompt}],
                    tool_choice="none",
                    temperature=0.3,
                    max_tokens=2048,
                )
            except Exception as e:
                logger.exception("LLM error during recap")
                yield {"type": "error", "content": f"Erreur LLM: {str(e)}"}
                break
            content = (response.choices[0].message.content or "").strip()
            if not content:
                content = "Tâche terminée. Consultez les fichiers dans l'onglet **Fichiers**."
            yield from _stream_final(content)
            break

        yield {
            "type": "status",
            "content": f"Etape {step_num} — Reflexion...",
            "step": step_num,
        }

        force_no_tools = iteration >= MAX_ITERATIONS - 2

        try:
            messages_for_llm = list(full_messages)
            progress_msg = _build_progress(executed_log)
            messages_for_llm.append({"role": "system", "content": progress_msg})

            create_kwargs = dict(
                model=model,
                messages=messages_for_llm,
                temperature=0.3,
                max_tokens=4096,
            )
            if force_no_tools:
                create_kwargs["tool_choice"] = "none"
                if iteration == MAX_ITERATIONS - 2:
                    messages_for_llm.append({
                        "role": "system",
                        "content": "Tu approches de la limite. Écris ton résumé final MAINTENANT, sans appeler d'outils.",
                    })
            else:
                create_kwargs["tools"] = all_definitions
                create_kwargs["tool_choice"] = "auto"

            response = client.chat.completions.create(**create_kwargs)
        except Exception as e:
            logger.exception("LLM error at iteration %d", step_num)
            yield {"type": "error", "content": f"Erreur LLM: {str(e)}"}
            break

        choice = response.choices[0]
        msg = choice.message

        if not msg.tool_calls:
            content = (msg.content or "").strip()
            if not content:
                content = "(Tâche terminée)"

            if _should_continue(content, choice.finish_reason, continuation_count, MAX_CONTINUATIONS, iteration, MAX_ITERATIONS):
                continuation_count += 1
                full_messages.append({"role": "assistant", "content": content})
                full_messages.append({
                    "role": "user",
                    "content": "Continue. Ta réponse a été coupée. Reprends exactement où tu t'es arrêté.",
                })
                yield {"type": "thinking", "content": content}
                yield {"type": "status", "content": f"Réponse tronquée — relance auto ({continuation_count}/{MAX_CONTINUATIONS})..."}
                continue

            yield {"type": "status", "content": "Rédaction de la réponse..."}
            yield from _stream_final(content)
            break

        # Tool calls
        full_messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })

        if msg.content:
            yield {"type": "thinking", "content": msg.content}

        tool_count = len(msg.tool_calls)
        for tc_idx, tc in enumerate(msg.tool_calls):
            tool_name = tc.function.name
            try:
                tool_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            cmd_preview = _build_command_preview(tool_name, tool_args)

            if tool_name not in all_executors:
                yield {
                    "type": "tool_call",
                    "tool": tool_name,
                    "args": tool_args,
                    "command": tool_name,
                    "tool_index": tc_idx + 1,
                    "tool_total": tool_count,
                }
                yield {
                    "type": "tool_output",
                    "tool": tool_name,
                    "output": {"stdout": "", "stderr": f"'{tool_name}' n'est pas un outil disponible.", "exit_code": 1},
                    "duration": 0,
                    "command": tool_name,
                }
                full_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": f"ERREUR : '{tool_name}' n'est PAS un outil. Pour exécuter la commande '{tool_name}', utilise l'outil run_command avec command=\"{tool_name} {' '.join(str(v) for v in tool_args.values())}\". Seuls ces outils existent : {', '.join(all_executors.keys())}",
                })
                continue

            call_sig = _make_call_signature(tool_name, tool_args)
            call_counts[call_sig] = call_counts.get(call_sig, 0) + 1
            if call_counts[call_sig] >= 3 and tool_name != "write_file":
                yield {
                    "type": "tool_call",
                    "tool": tool_name,
                    "args": tool_args,
                    "command": cmd_preview,
                    "tool_index": tc_idx + 1,
                    "tool_total": tool_count,
                }
                yield {
                    "type": "tool_output",
                    "tool": tool_name,
                    "output": {"stdout": "(Commande déjà exécutée 2+ fois — skipped)", "stderr": "", "exit_code": 0},
                    "duration": 0,
                    "command": cmd_preview,
                }
                full_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": "BOUCLE DÉTECTÉE : cette commande a déjà été exécutée 2 fois. Passe à une AUTRE commande ou termine.",
                })
                continue

            yield {
                "type": "tool_call",
                "tool": tool_name,
                "args": tool_args,
                "command": cmd_preview,
                "tool_index": tc_idx + 1,
                "tool_total": tool_count,
            }

            if not auto_mode and session:
                yield {
                    "type": "approval_needed",
                    "tool": tool_name,
                    "args": tool_args,
                    "command": cmd_preview,
                    "session_id": session_id,
                }
                approved = session.request_approval()
                if not approved:
                    yield {"type": "approval_rejected", "tool": tool_name}
                    full_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": "User rejected this tool call. Try a different approach.",
                    })
                    continue

            yield {"type": "tool_start", "tool": tool_name, "command": cmd_preview}

            t0 = time.time()
            result = execute_tool(tool_name, tool_args, all_executors)
            duration = round(time.time() - t0, 1)
            logger.info("Tool %s done in %.1fs | exit=%s", tool_name, duration, result.get("exit_code"))

            yield {
                "type": "tool_output",
                "tool": tool_name,
                "output": result,
                "duration": duration,
                "command": cmd_preview,
            }

            if result.get("skipped"):
                tool_content = "SKIP: L'utilisateur a ignoré cette commande. Continue avec l'étape suivante."
            else:
                tool_content = _format_tool_result(result)
                if result.get("exit_code") == -1 and "Timeout" in result.get("stderr", ""):
                    tool_content += "\n\nTIMEOUT: cet outil a pris trop de temps. Continue avec l'étape suivante."
                elif result.get("exit_code") not in (0, None) and not result.get("stdout"):
                    tool_content += "\n\nERREUR: cet outil a échoué. Continue avec une alternative."

            full_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_content,
            })

            executed_log.append({
                "tool": tool_name,
                "preview": cmd_preview,
                "summary": _brief_result(result),
                "failed": result.get("exit_code") not in (0, None) or result.get("skipped"),
            })

            if tool_name == "write_file":
                path = tool_args.get("path", "")
                if "rapport" in path.lower() and path.endswith(".md"):
                    rapport_written = True

        if rapport_written:
            conclude_next = True

    else:
        yield {"type": "status", "content": "Recap final..."}
        recap = (
            "Fais un récap markdown de tout ce qui a été fait : résultats, problèmes trouvés, recommandations.\n\n"
            "Ajoute une section '## Et maintenant ?' avec 2 à 4 propositions concrètes de suites. Pas d'outils."
        )
        try:
            response = client.chat.completions.create(
                model=model,
                messages=full_messages + [{"role": "system", "content": recap}],
                tool_choice="none",
                temperature=0.3,
                max_tokens=2048,
            )
            content = (response.choices[0].message.content or "").strip()
            if content:
                yield from _stream_final(content)
            else:
                yield {"type": "done", "content": "Tâche terminée. Consultez les fichiers du workspace."}
        except Exception as e:
            logger.exception("LLM error during final recap")
            yield {"type": "done", "content": "Tâche terminée. Consultez les fichiers du workspace."}

    if session_id and session_id in _sessions:
        del _sessions[session_id]


def _stream_final(content: str):
    words = content.split(' ')
    chunk = ''
    for i, word in enumerate(words):
        chunk += (' ' if chunk else '') + word
        if len(chunk) > 20 or i == len(words) - 1:
            yield {"type": "token", "content": chunk + ' '}
            chunk = ''
    yield {"type": "done", "content": content}
