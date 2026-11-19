# Outreach Control Center (Streamlit)

A web UI for the whole cold-outreach pipeline (Phase 1 → 2 → 3):

- **Edit prompts** — the discovery / contact-discovery prompts and the
  outreach email text, saved to disk with `.bak` backups.
- **Edit API keys** — add/remove/enable keys; live runs rotate across them
  automatically when one fails (quota, rate limit, auth).
- **Edit cities** — the target city list is filled into the Phase 1 prompt's
  `{{CITIES}}` placeholder (no more hardcoded Berlin).
- **Run the program** — start Phase 1, Phase 2, or a safe Phase 3 preview /
  test from the UI, with a **DRY RUN** mode that needs no API key.
- **Real-time updates** — the run page streams the live log and progress
  (the CSVs are the source of truth), and the Results page auto-refreshes.

## Quickstart

```bash
cd streamlit_app
python -m venv .venv
# Windows (Git Bash): source .venv/Scripts/activate   ·  macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

streamlit run app.py
```

Open the printed URL (default `http://localhost:8501`).

## First run

1. `streamlit_app/settings.json` is created automatically, seeded with the
   target cities and the two additional keys you supplied.
2. **Settings → API keys**: each key has a **provider** — `gemini`
   (starts with `AIza`) or `yandex` (starts with `AQ.`). The two supplied
   `AQ.…` keys are Yandex Cloud keys: set provider **yandex** and add their
   **folder id** (Yandex Cloud → folder → ID) and they work for live runs.
   Gemini keys work out of the box.
3. **Run** → tick **DRY RUN** → start Phase 1: watch the simulated campaign
   stream into the log, then try Phase 2 on the same demo data.
4. When happy, untick DRY RUN and run for real (needs a working key).
   Run-time overrides (cities, batch, cap, model…) on the Run page are
   applied per run without touching saved settings.

## Verify the UI without a browser

```bash
cd streamlit_app
python _ui_smoke_test.py   # AppTest: renders every page, then starts a
                           # DRY-RUN Phase 1 and asserts the live log
                           # streams in and the run finishes.
python _audit_test.py      # AppTest: Stop button, delete-key draft reset,
                           # idempotent saves, prompt .bak backup.
```

## What lives where

| Path | Purpose |
|---|---|
| `app.py` | Entry point, sidebar navigation |
| `core/paths.py` | Repo-wide path resolution |
| `core/settings.py` | `settings.json` load/save (keys, cities, knobs) |
| `core/clients.py` | `RotatingClient` — key fallback + provider dispatch |
| `core/providers/` | Provider adapters (`yandex.py` = YandexGPT) |
| `core/runners.py` | Background threads, live log buffer, stop events |
| `core/results.py` | CSV reading / overview counts |
| `pages/*.py` | Overview · Run · Prompts · Settings · Results |
| `settings.json` | Runtime settings (**git-ignored**, contains keys) |

## Notes

- **Runs are resumable**: the phases persist after every batch/company, so a
  stopped run continues where it left off on the next start.
- **Phase 3** in the UI is limited to *preview* and *test* (one email to
  `TEST_RECIPIENT`). Bulk sending stays on the CLI:
  `cd phase_3 && python send_emails.py --mode all`.
- The `settings.json` `phase1.csv_path` defaults to
  `phase_2/data/discovered_companies.csv` so Phase 1 feeds Phase 2 directly.
- Dry runs write to `phase_2/data/_demo_*.csv` and never touch real data.
