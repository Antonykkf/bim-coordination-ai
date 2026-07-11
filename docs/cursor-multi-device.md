# Access this project from another laptop (same Cursor account)

Cursor signs you into the same account on every machine, but it does **not**
automatically sync local project folders or chat history. Use **Git + a remote
repository** so both laptops work on the same codebase.

## One-time setup on this laptop

1. Create an empty GitHub repository named `bim-coordination-ai` (private is
   fine).
2. Commit and push from this machine:

```powershell
cd C:\Users\anton\Projects\bim-coordination-ai
git add .
git commit -m "Initial BIM coordination AI workflow"
.\scripts\connect-github.ps1 -RemoteUrl "https://github.com/YOUR_USER/bim-coordination-ai.git"
```

Replace `YOUR_USER` with your GitHub username.

## Open on the other laptop

1. Sign into **the same Cursor account**.
2. Install Git and Python 3.11+ if needed.
3. Clone and open the project:

```powershell
git clone https://github.com/YOUR_USER/bim-coordination-ai.git
cd bim-coordination-ai
cursor .
```

If the `cursor` CLI is not installed, use **File → Open Folder** in Cursor and
select the cloned directory.

4. Bootstrap the environment:

```powershell
.\scripts\setup.ps1
```

5. Copy secrets locally (never commit `.env`):

```powershell
Copy-Item .env.example .env
# Edit .env and add AI_API_KEY if you use LLM triage
```

## What syncs automatically

| Item | Syncs via Git? | Syncs via Cursor account? |
| --- | --- | --- |
| Source code | Yes | No |
| `.cursor/rules/` project rules | Yes | No |
| `.vscode/` workspace settings | Yes | No |
| User settings / keybindings | No | Often (Settings Sync) |
| Chat / agent history | No | No |
| `.venv/` virtual environment | No (rebuild with `setup.ps1`) | No |
| `.env` secrets | No (keep local) | No |

## Optional: Cursor Cloud Agents

If the repo is on GitHub and connected to Cursor, you can start a **Cloud
Agent** from either laptop against the same repository without copying files
manually. This is useful when you want cloud compute instead of a local venv.

## Daily workflow between two laptops

```powershell
# Before switching machines
git add .
git commit -m "Describe your change"
git push

# On the other laptop
git pull
.\scripts\setup.ps1   # only needed after dependency changes
```

## Chat history (optional)

Cursor chat history is stored locally per machine. To carry conversations
between laptops, use a third-party sync tool such as
[cursaves](https://github.com/Callum-Ward/cursaves), or continue each task in a
new chat after pulling the latest code.
