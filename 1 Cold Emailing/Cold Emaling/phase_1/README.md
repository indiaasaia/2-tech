# Startup Discovery — Stage 1 Prototype

Batch discovery of Berlin startups (small-to-medium, English-friendly, student/intern
hiring) via the Gemini **Interactions API**. Batches of 5 companies per request,
repeated until 50 are stored — no duplicates, no guessing.

```
Category Selection → Entity/Startup Discovery → (future) Contact Discovery → (future) Communication
```

This prototype implements **only** the Entity/Startup Discovery stage.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate        # Windows (Git Bash): source .venv/Scripts/activate
pip install -r requirements-dev.txt

export GEMINI_API_KEY="your-key" # from https://aistudio.google.com/apikey — starts with "AIza..."

python -m startup_discovery.cli                 # live campaign: 5/batch until 50 stored
python -m startup_discovery.cli --once          # single batch (smoke test)
python -m startup_discovery.cli --dry-run       # offline simulation, no API key needed
```

Results are written to `data/discovered_companies.csv` after **every** batch, so the
CSV is always the source of truth — rerun any time to resume a campaign.

## How a run works

1. **Context manager** builds the request: the research instructions from
   `prompts/discovery_prompt.md` (with `{target_count}` / `{total_cap}` filled) as the
   system instruction, plus a task block containing the batch number, progress counts,
   and the compact **exclusion list** of already-discovered companies. The conversation
   history is never sent — everything is rebuilt from the CSV before each request.
2. **Gemini client** calls `interactions.create` (stateless, `store=False`) with a
   strict JSON response schema (`startup_discovery/schema.py`).
3. **Validation** rejects candidates that lack required evidence
   (`english_hiring_evidence`, `student_intern_evidence`), have a hiring-probability
   score below the threshold (default 55), a bad website, or no sources.
4. **Dedup** drops candidates matching an existing company by normalized name or
   website domain (handles GmbH/AG suffixes, www, case).
5. **Storage** appends the new records with `discovery_batch` (run number) and a
   timestamp.

The loop stops when the cap is reached, after `max_runs` calls, or after repeated runs
with no new companies (empty-run tolerance: `empty_run_retries`).

## Configuration

| Env var / flag | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | — | API key (required for live runs) |
| `GEMINI_MODEL` / `--model` | `gemini-3.6-flash` | Model id |
| `DISCOVERY_BATCH_SIZE` / `--batch-size` | 5 | Companies requested per run |
| `DISCOVERY_CAP` / `--cap` | 50 | Stop once this many are stored |
| `DISCOVERY_MIN_SCORE` / `--min-score` | 55 | Reject candidates below this score |
| `DISCOVERY_MAX_RUNS` / `--max-runs` | 20 | Safety limit on API calls |
| `DISCOVERY_TEMPERATURE` | 0.2 | Sampling temperature |
| `DISCOVERY_CSV` / `--csv` | `data/discovered_companies.csv` | Output file |
| `DISCOVERY_PROMPT` / `--prompt` | `prompts/discovery_prompt.md` | Prompt template |

## Modules

| Module | Responsibility |
|---|---|
| `config.py` | All knobs; env + CLI overrides |
| `context.py` | Builds the per-request context (instructions + task + exclusion list) |
| `gemini_client.py` | Thin wrapper over the Interactions API (+ `FakeGeminiClient` for dry runs) |
| `schema.py` | Pydantic JSON contract between Gemini and the app |
| `validation.py` | Structural checks; turns quality rules into enforced rules |
| `dedup.py` | Name/domain normalization + duplicate detection |
| `storage.py` | CSV read/write — the source of truth |
| `discovery.py` | The batch loop |
| `cli.py` | Entry point |

## Tests

```bash
python -m pytest -q
```

Covers dedup, validation, storage round-trips, context building, and the full loop
(cap, dedup, low-score rejection, empty-run stop, parse errors, resume, truncation).

## Known limits (by design, for now)

- Evidence is **model-reported**: the model cites sources, but nothing verifies them
  live. Audit the `sources` column before acting on it. Live verification (Google
  Search grounding) is a future hardening step.
- "Currently hiring" is approximated by the model's knowledge; rows carry a
  `discovered_at` timestamp and `current_hiring_evidence` for human judgment.
- The CSV is an allow-list only — rejected candidates are logged, not stored.

## Extending later

- **Contact Discovery** (next stage): consume the CSV's `company_name`/`website`,
  append contact columns. The schema is additive-friendly.
- **Communication**: new stage after contacts.
- Swap `storage.py` for a database without touching the loop.
