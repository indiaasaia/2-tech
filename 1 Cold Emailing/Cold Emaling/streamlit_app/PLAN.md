# Complete Plan — Outreach Control Center (Streamlit)

**Goal:** a single web app from which you can (1) edit every prompt, (2)
manage API keys, (3) manage target cities, (4) run the discovery/sending
pipeline, and (5) watch progress in real time — without touching the
terminal or Python files.

---

## 1. What already exists

The repo is a three-phase cold-outreach pipeline for Werkstudent/intern
applications:

| Phase | What it does | Where |
|---|---|---|
| 1 · Startup discovery | Gemini finds startups (batch by batch) matching hiring criteria, writes `discovered_companies.csv` | `phase_1/` |
| 2 · Contact discovery | For each company, Gemini researches public professional emails, writes contacts + outcomes CSVs | `phase_2/` |
| 3 · Email sender | Sends personalised outreach via Gmail SMTP, logs to `sent_history.csv` | `phase_3/` |

Each phase is a tested CLI package. Phase 1 hardcoded **Berlin** inside its
prompt; the API key came from an env var; prompts lived only in `.md` files.

## 2. Design principles

1. **CSV = source of truth.** Phases already persist after every
   batch/company, so the UI reads progress straight from the CSVs — no new
   state duplication, and runs are resumable.
2. **Backward-compatible phase edits.** The control center adds a few
   optional knobs to the phases (`cities`, `should_stop`) without changing
   existing CLI behaviour or breaking any of the 108 tests.
3. **Secrets stay local.** API keys and the Gmail `.env` live in
   git-ignored files (`streamlit_app/settings.json`, `phase_3/.env`).
4. **Simulation first.** A DRY-RUN toggle exercises the whole UI with fake
   Gemini clients — no key needed to test the system.
5. **Safe by default for sending.** Bulk emailing stays on the CLI; the UI
   only offers preview and a single test email.

## 3. Architecture

```
┌─────────────────────────── streamlit_app/ ───────────────────────────┐
│  app.py            entry point + sidebar navigation                   │
│  pages/            Overview · Run · Prompts · Settings · Results      │
│  core/paths.py     one place that resolves every file path            │
│  core/settings.py  settings.json  (api_keys · cities · knobs)         │
│  core/clients.py   RotatingClient (key fallback, provider dispatch)    │
│  core/runners.py   daemon threads + live log buffer + stop events     │
│  core/results.py   CSV readers / dashboard counts                     │
│  core/providers/   provider adapters (yandex.py = YandexGPT client)   │
└───────────────────────────────────────────────────────────────────────┘
                      │  imports (sys.path → repo root)
                      ▼
        phase_1 (startup_discovery)   phase_2 (contact_discovery)   phase_3 (send_emails.py)
```

**Real-time mechanism:** a run starts a **daemon thread** that calls the
existing `run_discovery` / `run_contact_discovery` functions with a
`log_fn` writing into a thread-safe `LogBuffer`. A Streamlit
`@st.fragment(run_every=2.0)` block re-renders itself every 2 seconds,
streaming the log, drawing progress bars from the CSVs, and exposing a
**Stop** button that flips a `threading.Event` the loops check between
batches/companies.

## 4. What the app lets you do

### 4.1 Edit prompts — `Prompts` tab
Four editors (each save writes a `.bak` backup):
- Phase 1 discovery prompt (`.md`)
- Phase 2 main research prompt (`.md`)
- Phase 2 repeat prompt (`.md`)
- Phase 3 email text (`email_text.py`, marked as Python)

### 4.2 Edit API keys — `Settings` tab
- Add / remove / enable / disable keys (label + value, password-masked),
  each with a **provider** (`gemini` / `yandex`) and — for Yandex keys —
  the Cloud **folder id**.
- Keys are tried **in order**; `RotatingClient` falls back to the next key
  on any failure (quota, rate limit, auth, outage) and logs which key
  served each call.
- The two supplied `AQ.…` keys are seeded as **yandex** provider; they
  become usable for live runs once their folder id is filled in (Yandex
  Cloud → folder → ID). Gemini keys (`AIza…`) work out of the box.

### 4.3 Edit cities — `Settings` tab
- Comma-separated city list, seeded with **Berlin, Munich, Frankfurt,
  Hamburg**.
- The Phase 1 prompt was rewritten to use a `{{CITIES}}` placeholder; the
  context builder fills it from settings (`"Berlin, Munich, Frankfurt and
  Hamburg"`), so no prompt editing is needed to change cities.
- Phase 1 config gained a `cities` field + `--cities` CLI flag +
  `DISCOVERY_CITIES` env var (default `Berlin` — fully backward
  compatible).

### 4.4 Run the program — `Run` tab
- Stage selector: Phase 1 / Phase 2 / Phase 3 (preview · test only).
- Per-run overrides (cities, batch size, cap, min score, model, iterations,
  limit, temperature) **are actually applied** to the run via
  `handle.overrides` → config merge; they never touch saved settings, and
  the progress bar targets follow them.
- **DRY RUN** toggle: simulated clients write to `phase_2/data/_demo_*.csv`
  so real campaign data is never touched.
- Start / Stop, live log, progress bars, and a summary table on finish.

### 4.5 Check updates in real time — `Run` + `Results` tabs
- Run page polls the log buffer every 2 s; CSV-driven progress updates in
  place.
- Results page auto-refreshes every 5 s (toggleable), with download buttons
  for every CSV (companies, contacts, outcomes, sent history, demo data).

### 4.6 Overview — `Overview` tab
Dashboard: enabled-key health (incl. the `AQ.` warning), per-phase counts,
outcome breakdown, target cities, and quick-start steps.

## 5. Changes to existing phases (minimal, backward compatible)

| File | Change |
|---|---|
| `phase_1/prompts/discovery_prompt.md` | Hardcoded "Berlin" → `{{CITIES}}` placeholder |
| `phase_1/startup_discovery/config.py` | + `cities` field, `DISCOVERY_CITIES` env |
| `phase_1/startup_discovery/context.py` | + `format_cities`, `{{CITIES}}` rendering |
| `phase_1/startup_discovery/cli.py` | + `--cities` flag |
| `phase_1/startup_discovery/discovery.py` | + optional `should_stop` callable (clean break) |
| `phase_2/contact_discovery/discovery.py` | + optional `should_stop`; `StoppedByUser`; in-flight company retried next run |
| `phase_1/__init__.py`, `phase_2/__init__.py` | empty packages so the app can import them |

All existing tests pass unchanged (53 + 55).

## 6. Security & safety

- `settings.json` and `phase_3/.env` are git-ignored; the app refuses to
  run live without at least one enabled key.
- Bulk email sending is not exposed in the UI (only dry-run preview and one
  test email).
- Prompt saves are backed up to `.bak` before overwrite.
- Dry runs never write to real CSVs.

## 7. Run it

```bash
cd streamlit_app
python -m venv .venv && source .venv/Scripts/activate   # or bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Then: Settings (add a real Gemini key) → DRY RUN Phase 1 → Phase 2 → real run.

## 8. Status vs. plan

Implemented in this iteration (beyond the original scope):

- **Provider plug-in (done)** — YandexGPT support via
  `core/providers/yandex.py` (Yandex Cloud completion API, `Api-Key` +
  `x-folder-id` auth). The two `AQ.` keys are wired to it; add the folder
  id and they work. The same `discover()` contract makes new providers
  (OpenAI, Anthropic…) drop-in.
- **Run-time overrides wired (done)** — per-run cities/batch/cap/score/
  model/iterations/limit/temperature actually reach the run.

## 9. Roadmap (future)

- Persist per-run overrides as named "campaigns" (city+cap+prompt presets).
- Bulk Phase 3 sending with live status + per-email open/reply tracking.
- Company-level audit panel (evidence, sources, contact quality scores).
- Swap CSVs for SQLite/Postgres behind the same `storage.py` API.
