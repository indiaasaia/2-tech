# Contact Discovery — Phase 2

Deep contact discovery for cold outreach. Takes the **company list produced in
Phase 1** (`data/discovered_companies.csv`, 50 Berlin startups) and, **one
company at a time**, hunts for legitimate, publicly available professional
email addresses via a multi-pass Gemini research campaign.

The output is the **address book** for a future communication phase: per
company, a list of `Name | Email` pairs (people and official role addresses)
— or an explicit record that no public email exists. Nothing is sent; this
phase only discovers.

```
Phase 1 (Entity Discovery) → Phase 2 (Contact Discovery) → (future) Communication
```

## How a run works

For every company with no outcome record yet:

1. **Iteration 1** — the main research prompt
   (`prompts/contact_discovery_prompt.md`) with `{{COMPANY_NAME}}` filled.
   Broad, deep search across the priority ladder (HR → recruiting → talent →
   hiring managers → eng managers → CTO → founders → general careers email).
2. **Iterations 2..N** — the repeat prompt
   (`prompts/contact_discovery_repeat_prompt.md`) with `{{COMPANY_NAME}}` and
   `{{PREVIOUS_EMAILS}}` (every email found so far) filled. The previous
   emails act as the **per-company exclusion list**: later passes must dig
   with different queries and return **only new** emails.
3. **Stop early** when the model signals saturation
   (`NO_NEW_PUBLIC_EMAIL_FOUND`) or returns nothing new; stop immediately
   when iteration 1 reports `NO_PUBLIC_EMAIL_FOUND`.
4. **Consolidate** — case-insensitive email dedup across iterations — then
   persist the contacts and the per-company outcome.

The **outcomes CSV doubles as the progress tracker**: a company with a
`CONTACTS_FOUND` / `NO_PUBLIC_EMAIL_FOUND` outcome is done and skipped on
rerun, while `ERROR` outcomes (e.g. a quota/rate-limit outage) are **retried**
on the next run — so a campaign always resumes where it stopped, and a
throttled company is never abandoned. One row per company, last attempt wins
(same "CSV is the source of truth" principle as Phase 1).

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate        # Windows (Git Bash): source .venv/Scripts/activate
pip install -r requirements-dev.txt

export GEMINI_API_KEY="your-key" # from https://aistudio.google.com/apikey — starts with "AIza..."

python -m contact_discovery.cli --probe       # verify Gemini connectivity + which models respond
python -m contact_discovery.cli                # live run, all companies
python -m contact_discovery.cli --limit 1      # smoke test on one company
python -m contact_discovery.cli --dry-run      # offline simulation, no API key needed
```

`--probe` makes one tiny call per model in the chain and prints which ones
respond — run it first to confirm your key and the model chain work.

Results are written to `data/contact_discovery_results.csv` (one row per
contact) and `data/contact_discovery_outcomes.csv` (one row per company)
after **every company**, so both CSVs are always current.

## Configuration

| Env var / flag | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | — | API key (required for live runs) |
| `GEMINI_MODEL` / `--model` | `gemini-3.7-flash` | Primary model (agentic research + strict extraction) |
| `GEMINI_FALLBACK_MODELS` / `--fallback-models` | `gemini-3.6-flash,gemini-3.5-flash` | Comma-separated fallback chain, tried in order on rate limits |
| `CONTACT_TEMPERATURE` / `--temperature` | 0.2 | Sampling temperature |
| `CONTACT_MAX_ITERATIONS` / `--max-iterations` | 3 | Research passes per company |
| `CONTACT_LIMIT` / `--limit` | — | Process at most this many companies per session |
| `CONTACT_COMPANIES_CSV` / `--companies` | `data/discovered_companies.csv` | Phase 1 company list (input) |
| `CONTACT_CSV` / `--csv` | `data/contact_discovery_results.csv` | Contacts output (one row per email) |
| `CONTACT_OUTCOMES_CSV` / `--outcomes` | `data/contact_discovery_outcomes.csv` | Per-company outcome / progress tracker |
| `CONTACT_PROMPT` / `--prompt` | `prompts/contact_discovery_prompt.md` | Iteration-1 prompt template |
| `CONTACT_REPEAT_PROMPT` / `--repeat-prompt` | `prompts/contact_discovery_repeat_prompt.md` | Repeat-iteration prompt template |

## Output format

**Contacts CSV** (`contact_discovery_results.csv`) — one row per email:

```
company_name, website, contact_name, contact_email, iteration, discovered_at
```

**Outcomes CSV** (`contact_discovery_outcomes.csv`) — one row per company;
`status` is one of:

- `CONTACTS_FOUND` — at least one legitimate email was stored.
- `NO_PUBLIC_EMAIL_FOUND` — research completed, no legitimate public email
  exists (a first-class result, never padded with guesses).
- `ERROR` — every iteration failed with an API/network error.

## Modules

| Module | Responsibility |
|---|---|
| `config.py` | All knobs; env + CLI overrides |
| `context.py` | Fills `{{COMPANY_NAME}}` / `{{PREVIOUS_EMAILS}}` and builds each request |
| `parsing.py` | Parses `Name | Email` lines + the two sentinels; case-insensitive dedup |
| `validation.py` | Mechanical email sanity checks (structure, non-empty name) |
| `storage.py` | Companies/contacts/outcomes CSV read/write — the source of truth |
| `discovery.py` | The per-company loop: iterate, consolidate, persist |
| `gemini_client.py` | Thin wrapper over the Interactions API (+ `FakeGeminiClient` for dry runs) |
| `cli.py` | Entry point |

## Model fallback

The client holds a **model chain** (primary first):
`gemini-3.7-flash` → `gemini-3.6-flash` → `gemini-3.5-flash`. All three are
stable Flash-class models — aligned to this workload (deep web research with
strict `Name | Email` extraction; fast, cheap, strong instruction-following).
When the primary model hits a **rate limit, quota exhaustion, timeout, or
transient outage** (HTTP 408/429/500/502/503/504/529 or the corresponding
gRPC statuses), the next model is tried automatically. Hard errors (bad
request, blocked content, invalid key) **fail fast** — switching models would
not help. The iteration log shows which model actually served each response
(e.g. `[iter 2 · gemini-3.6-flash]`).

## Accuracy model

The hard accuracy rules (never guess an email, public evidence only, never
repeat) live in the **prompts** — the model verifies every address during
research. This codebase enforces what is mechanically checkable: output
format, structural email validity, and case-insensitive dedup. Because the
prompt format deliberately excludes source URLs, per-email evidence is not
stored; trust in the model's verification is by design.

## Tests

```bash
python -m pytest -q
```

Covers parsing (sentinels, format, dedup), context building, storage
round-trips, and the full loop (3-iteration arc, early stop, no-email
outcome, API-error handling, resume, limit, prompt selection).
