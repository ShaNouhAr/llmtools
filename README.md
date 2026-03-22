# LLMTools — Plateforme multi-modules avec LLM (LM Studio)

Projet Docker qui fournit une **plateforme multi-modules** pilotée par un **LLM local** via **LM Studio**, avec une **interface web** (chat, agent autonome, rapports, gestion de modèles).

## Modules disponibles

| Module | Description |
|--------|-------------|
| **Pentest** | Agent de test d'intrusion autonome. Scanne, analyse et teste les vulnérabilités d'une cible (nmap, nikto, sqlmap, nuclei…). |
| **Diagnostic SSH** | Diagnostic complet d'une machine Linux via SSH. Détecte crashes, erreurs, services défaillants, problèmes de performance. |

## Prérequis

- **Docker** et **Docker Compose**
- **LM Studio** installé sur la machine hôte, avec :
  - Un modèle chargé
  - Le **serveur local** activé (onglet Developer → port **1234** par défaut)

## Démarrage rapide

1. **Lancer LM Studio** sur l'hôte, charger un modèle, puis activer le serveur local (port 1234).

2. **Copier la config** (optionnel) :
   ```bash
   cp .env.example .env
   ```

3. **Lancer le conteneur** :
   ```bash
   docker compose up --build
   ```

4. **Ouvrir l'interface web** : [http://localhost:8000](http://localhost:8000)
   - **Accueil** : tableau de bord avec statut LM Studio et modules disponibles.
   - **Chat** : discutez avec l'agent, mode chat simple ou mode agent autonome (exécution d'outils).
   - **Modèles** : sélectionnez le modèle actif, recherchez et téléchargez des modèles GGUF depuis HuggingFace.
   - Panneau **Fichiers** : consultez les fichiers générés par l'agent (scans, rapports…).

## Configuration

LM Studio est **auto-découvert** sur le réseau. Si besoin, vous pouvez forcer l'URL dans `.env` :

| Variable | Description | Défaut |
|----------|-------------|--------|
| `LM_STUDIO_BASE_URL` | URL de l'API LM Studio (auto-découvert si non défini) | Auto-découverte |
| `LM_STUDIO_MODEL` | Nom du modèle dans LM Studio | `local-model` |
| `LM_STUDIO_API_KEY` | Clé API si auth activée dans LM Studio | `not-needed` |
| `LLMTOOLS_REPORTS_DIR` | Dossier de stockage des rapports (dans le conteneur) | `/data/reports` |
| `LLMTOOLS_CHATS_DIR` | Dossier de stockage des conversations | `/data/chats` |
| `TOOL_TIMEOUT` | Timeout des outils en secondes | `120` |
| `AGENT_MAX_ITERATIONS` | Nombre max d'itérations de l'agent | `50` |

Les **données** sont stockées dans les volumes Docker `llmtools_data` et `llmtools_workspace`, donc conservées entre les redémarrages.

## Dépannage : « Impossible de joindre LM Studio »

1. **Activer « Serve on Local Network » dans LM Studio**
   Developer → Local Server → activez **Serve on Local Network**. Redémarrez le serveur.

2. **Utiliser l'IP de votre PC**
   Dans `.env` :
   ```env
   LM_STUDIO_BASE_URL=http://192.168.x.x:1234/v1
   ```

3. **Pare-feu**
   Autorisez les connexions entrantes sur le port **1234**.

4. **Sans Docker (tout en local)**
   ```bash
   pip install -r requirements.txt
   export LM_STUDIO_BASE_URL=http://localhost:1234/v1
   python -m uvicorn src.web:app --host 0.0.0.0 --port 8000
   ```

## Lancer sans Docker (en local)

```bash
pip install -r requirements.txt
# .env : LM_STUDIO_BASE_URL=http://localhost:1234/v1
python -m uvicorn src.web:app --reload --host 0.0.0.0 --port 8000
```

Interface web : [http://localhost:8000](http://localhost:8000).
CLI en mode console uniquement : `python -m src.main`.

## Structure

```
llmtools/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── README.md
├── src/
│   ├── __init__.py
│   ├── main.py              # CLI interactif
│   ├── web.py               # FastAPI, chat streaming, pages
│   ├── core/
│   │   ├── agent.py         # Client LLM, auto-découverte, streaming
│   │   ├── agent_loop.py    # Boucle agent avec tool calling
│   │   ├── chats.py         # CRUD conversations (JSON)
│   │   └── tools.py         # Outils communs (run_command, web, fichiers)
│   └── modules/
│       ├── registry.py      # Registre central des modules
│       ├── pentest/          # Module Pentest (nmap, sqlmap, nikto…)
│       └── ssh_diag/         # Module Diagnostic SSH (paramiko)
├── templates/                # HTML Jinja2 (accueil, chat, modèles, config)
└── static/                   # CSS, JS
```

## Avertissement

Les modules de sécurité (Pentest) sont conçus pour des **tests autorisés** et un usage **légal**. Utilisez-les uniquement sur des systèmes pour lesquels vous avez une autorisation explicite.
