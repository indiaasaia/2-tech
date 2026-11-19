# Bosch (SmartRecruiters) — Automated Job Applications

One-file Playwright automation (`bosch_job_apply.py`) that applies to jobs at
Bosch Group through the Bosch career site / SmartRecruiters application portal
(`jobs.bosch.de` → `jobs.smartrecruiters.com/BoschGroup/...`).

Built to the Bosch automation spec:

- **Semantic automation only** — every field is located, its question text is
  read from the live DOM, normalized, and matched against bilingual (DE/EN)
  question patterns. No screen coordinates, no positional `nth()`, no
  index-based option selection.
- **Configuration-driven** — all candidate answers live in
  `config/candidate.json`; nothing personal is hardcoded in the flow.
- **Dry-run first** — the default walk fills everything, validates, and stops
  before `Absenden`. Submission only happens with `--submit` + typed `YES`.
- **Never guess** — unknown questions are reported and *block* submission;
  CAPTCHA stops the run with `CAPTCHA_DETECTED`; every fill/selection is read
  back from the DOM and verified.

---

## Flow implemented

```
Bosch job page
  → Apply now (same tab / new tab / redirect — all handled)
  → SmartRecruiters form detected (real form elements verified, not just URL)
  → [optional SmartRecruiters login if required — env credentials only]
  → Resume upload (RESUME section only, filename + processing verified)
  → Email (filled + read back)
  → Next / Continue / Weiter
  → Bosch pre-questions (DE/EN, order-independent, fuzzy matched):
       Immatrikulation ……… Ja/Yes        (config: enrolled_entire_period)
       Voll-/Teilzeitstudium … Vollzeit  (config: study_type)
       Duales Studium ……… Nein/No       (config: dual_study)
       Studiumpende (MM/JJJJ) 10.2027    (config: expected_graduation)
       Weiteres Studium ……… Nein/No     (config: intends_further_degree)
       Gewünschte Dauer …… 6 Months     (config: preferred_duration)
       Gewünschter Zeitraum … 01.10.2027 (config: preferred_period_start/end)
  → Einwilligungserklärung checkbox      (config: bosch_other_position_consent)
  → Additional attachments               (config: additional_attachments, ≤10MB)
  → Datenschutzerklärung checkbox (required)
  → Full pre-submit validation → Absenden
  → Confirmation detection (success text / application id)
```

## Files

```
bosch/
├── bosch_job_apply.py        ← THE automation (single file, importable + CLI)
├── config/
│   └── candidate.json        ← YOUR personal data (overrides script defaults)
└── results/                  ← per-run screenshots + result JSON (audit trail)
```

## Quick start

```bash
cd bosch

# 1) EDIT config/candidate.json first (email, dates, consents, resume path)

# 2) OPTIONAL but recommended on a new job: dump the live form structure
python bosch_job_apply.py --discover

# 3) Dry-run (browser opens, walks + fills + validates, does NOT submit):
python bosch_job_apply.py --dry-run

# 4) Real submission (asks you to type YES):
python bosch_job_apply.py --submit

# Variants:
python bosch_job_apply.py --url "<JOB_URL>" --resume "<RESUME.pdf>" --dry-run
python bosch_job_apply.py --submit --headless
python bosch_job_apply.py --submit --wait-after-captcha 120   # pause for manual CAPTCHA
```

## Programmatic use

```python
from pathlib import Path
from bosch_job_apply import apply_to_bosch_job

result = apply_to_bosch_job(
    job_url="https://jobs.smartrecruiters.com/BoschGroup/744xxxxxxx-...",
    resume_path=Path("E:/WorkSpace/2 Tech/Cold Emaling/RAVAL_MEETKUMAR_RESUME.pdf"),
    dry_run=True,     # 1. always dry-run first
    headless=False,
)
print(result["status"])          # DRY_RUN / SUCCESS / FAILED / CAPTCHA_DETECTED / UNKNOWN_FORM
print(result["questionsAnswered"])
print(result["unknownQuestions"])  # MUST be empty before a real submit
```

## What each run produces

In `results/`:

- `bosch-<jobid>-01_job_page.png` … `bosch-<jobid>-08_success.png`
- `bosch-<jobid>-error.png` / `bosch-<jobid>-captcha.png` / `unknown-questions.png`
- `bosch-<jobid>-result.json` — full audit record: status, stages reached,
  every question answered with its value, unknown questions, attachments,
  confirmation message / application id, screenshots, timestamps.
- `bosch-discover-<jobid>.json` — `--discover` dump: every button, file
  section, question group and control with its computed path, labels and
  options. Use this to extend `QUESTION_SPECS` when Bosch adds questions.

## Handling new / unknown questions

Bosch can change question wording, order, or add questions per posting:

1. The script detects any question-like block it cannot map (`UNKNOWN_FORM`
   risk) and **stops before submit** with the question text in
   `unknownQuestions` and `unknown-questions.png`.
2. Run `--discover`, open `bosch-discover-<jobid>.json`, find the question
   text and its option labels.
3. Add a spec to `QUESTION_SPECS` in `bosch_job_apply.py` (key, kind
   `yesno|study_type|duration|date_mm_yyyy|date_range`, config name, DE+EN
   patterns — matching is fuzzy/normalized, umlauts folded, punctuation
   ignored) and add the answer to `config/candidate.json`.
4. Re-run the dry-run.

## Configuration reference (`config/candidate.json`)

| Key | Meaning | Example |
|---|---|---|
| `job_url` | Bosch job posting URL | `https://jobs.bosch.de/...` |
| `resume_path` | Resume PDF/DOCX (same file as Mercedes) | `E:\...\RAVAL_MEETKUMAR_RESUME.pdf` |
| `candidate_email` | Contact email | `ravalmeett@gmail.com` |
| `expected_graduation` | Expected graduation MM/YYYY | `10.2027` |
| `study_type` | `Vollzeit / full-time` or `Teilzeit / part-time` | `Vollzeit / full-time` |
| `dual_study` | Dual curriculum program? | `false` |
| `intends_further_degree` | Another degree after this one? | `false` |
| `preferred_duration` | Working-student duration | `6 Months` |
| `preferred_period_start` / `_end` | Preferred period (DD.MM.YYYY); end optional | `01.10.2027` / `""` |
| `bosch_other_position_consent` | Einwilligungserklärung (other open positions) | `true` |
| `privacy_consent` | Must stay `true` to submit | `true` |
| `additional_attachments` | Extra files (≤10 MB each); `[]` = none | `[]` |
| `smartrecruiters_email` / `_password` | **Leave empty** — use env vars | see below |

Credentials, if the portal ever demands a login, are read from the
environment (`SMARTRECRUITERS_EMAIL`, `SMARTRECRUITERS_PASSWORD`) — never from
source or committed config. If login is required and no credentials exist, the
run stops instead of guessing.

## Safety rules baked into the script

1. **Never invents data** — every answer comes from `config/candidate.json`;
   unknown questions are reported and block submission.
2. **Never confuses resume and attachments** — every file input is classified
   by its surrounding section text; the resume is only uploaded to a
   RESUME/CV-labeled section, attachments only to the additional-attachments
   section, and nothing at all when the attachment list is empty.
3. **Never bypasses CAPTCHA** — detection stops with `CAPTCHA_DETECTED`
   (optionally waiting for you to solve it manually with
   `--wait-after-captcha`).
4. **Never trusts a click** — email values, date fields, dropdown selections
   and checkbox states are all read back from the DOM and verified.
5. **Wrong-application guard** — the opened page must be a Bosch page, and if
   `expected_job_title` is configured, a title mismatch aborts before Apply.
6. **Dry-run cannot submit** — `Absenden` is only reachable via `--submit`
   behind a typed `YES` confirmation, after full validation.
7. **No positional automation** — no coordinates, no `nth()`, no index-based
   `selectOption`; scrolling uses `scrollIntoViewIfNeeded` per element.
8. **No arbitrary waits in the flow** — condition-based waiting
   (`waitForSelector`-equivalent locator waits, state polling) with only small
   animation-margin sleeps.

## Statuses

`SUCCESS` · `DRY_RUN` · `DISCOVERED` · `FAILED` · `CAPTCHA_DETECTED` ·
`UNKNOWN_FORM` — a run prints `SUCCESS` only when a confirmation message was
found after submit (and `application_id` when the portal exposes one).
