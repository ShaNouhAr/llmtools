#!/usr/bin/env python3
"""
Point d'entree CLI pour LLMTools (LLM via LM Studio).
"""
import os
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from src.core.agent import get_client, get_model, stream_chat

load_dotenv()
console = Console()


def main():
    console.print(
        Panel(
            "[bold cyan]LLMTools[/] — Plateforme multi-modules avec LLM (LM Studio)",
            subtitle=f"Modèle: {get_model()}",
        )
    )
    console.print(
        "[dim]Mode console (chat simple). 'quit' pour quitter.[/]\n"
    )

    messages: list[dict] = []
    client = get_client()

    while True:
        try:
            user_input = console.input("[bold green]Vous > [/] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            break

        messages.append({"role": "user", "content": user_input})

        console.print("[bold blue]LLMTools > [/] ", end="")
        try:
            full = ""
            for token in stream_chat(messages, client=client):
                full += token
                console.print(token, end="")
            console.print()
            if full:
                messages.append({"role": "assistant", "content": full})
        except Exception as e:
            console.print(f"[red]Erreur LLM: {e}[/]")
            console.print(
                "[dim]Vérifiez que LM Studio tourne avec le serveur local (port 1234).[/]"
            )
            messages.pop()

    console.print("[dim]Au revoir.[/]")


if __name__ == "__main__":
    main()
