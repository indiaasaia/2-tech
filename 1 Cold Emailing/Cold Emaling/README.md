# Cold Email Campaign — Final Structure

Automated cold-application pipeline: **find target organizations → find their
contacts → write a personalized hook → send the email → log everything**, then
repeat in batches of 10 until the day's limits are reached.

> **Current campaign:** targeting **Germany software companies & tech startups**
> building software products, pitching for **Working Student (Werkstudent) & Internship**
> technical positions (Software Engineering, AI/ML, Backend, Data). Each loop round
> discovers 10 companies, finds their engineering leadership/recruiters, and emails them
> automatically — up to **20 companies/day** (MAX_AGENCIES_PER_DAY).

## The two files you edit

Everything the campaign needs from you lives in two files at the project root:

### 1. `gemini_keys.json` — your API keys
```json
{
  "api_keys": [
    { "label": "Key 1", "value": "AIza...", "provider": "gemini", "enabled": true },
    { "label": "Key 2", "value": "AIza...", "provider": "gemini", "enabled": true }
  ]
}
```
- `enabled: false` turns a key off without deleting it.
- Add more keys the same way — the campaign rotates keys/models automatically
  and uses whichever still has free quota.
- `streamlit_app/settings.json` is the Streamlit app's own store; the campaign
  reads `gemini_keys.json` first and falls back to it.

### 2. `prompts.md` — every Gemini prompt, one file
Four sections, edited with any text editor:

| Section | Used by | Controls |
|---|---|---|
| `# SECTION: PHASE 1 - COMPANY DISCOVERY PROMPT` | Phase 1 | what kind of companies to find, where, and why (city, industry, role types, scoring) |
| `# SECTION: PHASE 2 - CONTACT DISCOVERY PROMPT (FIRST PASS)` | Phase 2 | how to find contact emails (which roles, which sources) |
| `# SECTION: PHASE 2 - CONTACT DISCOVERY PROMPT (REPEAT PASS)` | Phase 2 | the follow-up search pass for more emails |
| `# SECTION: PHASE 3 - COMPANY HOOK PROMPT` | Phase 3 | how the per-company opening sentence is written |

Each section keeps the `# SECTION:` header line; everything below it up to the
next header is that prompt. The campaign extracts them automatically on every
run (into `phase_3/data/prompts/`).

**To run a different campaign (e.g. agencies instead of tech companies):** edit
the Phase 1 section (what to find + city), the Phase 2 sections (contact
types), the Phase 3 section (the pitch), plus `phase_3/.env` (city, CV,
skills, identity) — the code does not need to change.

## The pipeline (`cd phase_3 && python campaign.py --loop`)

```
1  send already-queued emails          (daily cap aware)
2  discover contacts for pending companies   <- unfinished cycles first
3  research ONLY the deficit to fill the batch of 10
4  discover contacts for the newly researched
5  rebuild phase_3/contacts_to_send.csv
6  write personalized hooks (Gemini)
7  audit every email (no placeholders, hook present)
8  send the newly queued emails        (up to 6 per company, 120/day)
   -> repeat until today's agency cap (20) or the Gemini quota is reached
```

Flags: `--dry-run` (plan only) · `--skip-send` (research/discover, no emails) ·
`--loop --research-ahead` (keep discovering past the email cap).

## Where everything lives

```
gemini_keys.json          <- your API keys (edit here)
prompts.md                <- all Gemini prompts (edit here)
phase_1/                  company research (discovery pipeline + prompts)
phase_2/                  contact discovery (finds emails per company)
phase_3/                  sender: build list, hooks, audit, send, campaign loop
  .env                    sender identity, city, CV path, caps  (edit here)
  contacts_to_send.csv    planned recipients (rebuilt each round)
  sent_history.csv        every email: who, when, status, full body
  state.json              daily counters + anti double-send
  data/campaign_log.csv   round-by-round trail
  data/gemini_usage.json  Gemini calls per phase (quota tracking)
RAVAL_MEETKUMAR_RESUME.pdf  the attached CV (path set in phase_3/.env)
_archive/                 old/orphaned code, kept but unused
_backup_20260820/         full data backup from the fresh-start reset
```

## One run, day by day

- **Day 1:** `cd phase_3 && python campaign.py --loop` — researches the first
  10 companies from `phase_1/data/company_names.csv`, finds their contacts,
  hooks, audits, sends up to 30 emails, then stops (email cap reached).
- **Day 2+:** same command — sends the next 10. The 50-name pool ≈ 5 days.
- Every send is in `sent_history.csv` with timestamp, recipient, company,
  subject, status and body; `state.json` prevents ever double-sending.
