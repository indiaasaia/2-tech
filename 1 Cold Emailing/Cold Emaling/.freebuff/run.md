# Run doc — Outreach Control Center (Streamlit)

Web UI for the cold-outreach pipeline (Phase 1 → 2 → 3). Served on **port 8507**.

## Reproduce the artifacts

The app needs only two things beyond the repo itself, both already present:

1. **Runtime settings** — `streamlit_app/settings.json` (git-ignored; holds API keys,
   target cities, phase knobs). Fresh checkouts must **copy** it from the main
   checkout, never symlink:
   `cp streamlit_app/settings.json streamlit_app/settings.json` (from the main
   checkout). `streamlit_app/settings.example.json` is the fallback seed if no
   settings.json exists — the app auto-creates one on first run.
2. **Python + streamlit** — Python 3.14 with streamlit 1.61.1 is installed globally
   (`C:\Python314\python.exe`). No venv is required. If a clean env is preferred,
   follow `streamlit_app/README.md`:
   ```bash
   cd streamlit_app
   python -m venv .venv
   pip install -r requirements.txt
   ```

No other env files (`.env.local` etc.) or dependency installs are needed; the app
runs from the repository root and reads phase CSVs via relative paths.

## Run the server

From the repository root (`C:\Users\Meet Raval\Downloads\Cold Emaling`):

```bash
python -m streamlit run streamlit_app/app.py --server.port 8507 --server.address 127.0.0.1 --server.headless true
```

Detached (Windows, PowerShell — stdout/stderr to different files):

```powershell
powershell -NoProfile -Command "(Start-Process -FilePath 'C:\Python314\python.exe' -ArgumentList '-m','streamlit','run','streamlit_app/app.py','--server.port','8507','--server.address','127.0.0.1','--server.headless','true' -WorkingDirectory 'C:\Users\Meet Raval\Downloads\Cold Emaling' -RedirectStandardOutput '<log>' -RedirectStandardError '<log>.err' -WindowStyle Hidden -PassThru).Id"
```

Notes:
- Port 8507 is the project default for this thread's preview; if busy, pick a free
  port and pass `--server.port <port>`.
- Verify the URL answers before use: `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8507/` → `200`.
- The app's own README says the UI defaults to `http://localhost:8501`; this run doc
  pins 8507 to match the preview registration.
