# Bosch (SmartRecruiters) — End-to-End Job Application Pipeline

Fully self-contained pipeline for Bosch Group student jobs: **fetch → language
filter → LLM resume tailoring → per-job PDF/DOCX → automated application**.

Runs from this folder alone — it bundles its own copies of the resume stages,
prompts, Ollama helper, API keys, LaTeX template and `tectonic.exe`
(`program_files/`, `sub_program_files/`, `tools/`), exactly like the SAP FETCHER
project. No outside project needed.

Two automations live here:

- **`1_bosch_Jobs_fetching.py`** — scrapes all Bosch student jobs (list API +
  SmartRecruiters posting API + BSH HTML pages) into CSV/JSON.
- **`3_bosch_job_apply.py`** — Playwright automation that applies to ONE job
  through the Bosch career portal, semantic-only form filling, dry-run-safe.

---

## Pipeline

```
python main.py        # steps 1-5
```

| Step | File | What it does | Output |
|---|---|---|---|
| 1 | `1_bosch_Jobs_fetching.py` | Fetch every Bosch student job (list pages + per-job details, SmartRecruiters API + BSH HTML) | `BOSCH_results.csv`, `BOSCH_jobs_detailed.csv`, `BOSCH_jobs_full.json` |
| 2 | `2_language_differntiate.py` | Classify each posting: can an English-only applicant apply? (rule-based, auditable evidence per job) | `Language_Filter` / `Filter_Evidence` columns in place |
| 3 | `program_files/3_test_ollama_keys.py` | Test Ollama API keys, keep working ones | `sub_program_files/active_ollama_keys.json` |
| 4 | `4_resume_create.py` | Keep `ENGLISH_OK` jobs, map to the generator schema, run 4 LLM stages (objective, experience, projects, skills) | `program_files/output_bosch/*.json` + `2_filted_jobs.csv` |
| 5 | `5_final_resume.py` | Fill the LaTeX template per job, compile PDF (tectonic), mirror DOCX | `program_files/output_bosch/resume/{tex,pdf,docx}/`, `resume_report.json` |
| 6 | `6_apply_to_jobs.py` | Apply to jobs **with their tailored resumes** (dry-run by default) | `program_files/output_bosch/apply_report.json`, `results/` audit |

A failure in one step is reported with a traceback and does not stop the
others; `main.py` exits 0 only when every step succeeded.

## Quick start

```bash
# 1) full pipeline: fetch, filter, keys, components, resumes
python main.py

# 2) dry-run the job configured in config/candidate.json (no submission)
python 6_apply_to_jobs.py

# 3) dry-run a specific tailored job / all tailored jobs
python 6_apply_to_jobs.py --job-url "https://jobs.smartrecruiters.com/BoschGroup/..."
python 6_apply_to_jobs.py --all --limit 5

# 4) real submission (asks you to type YES)
python 6_apply_to_jobs.py --submit
python 6_apply_to_jobs.py --all --limit 3 --submit --headless
```

### Full run vs test run

Step 4 calls the LLM ~7x per job (objective, 2x experience, 2x projects,
skills). `4_resume_create.py` ships with `TEST_JOB_LIMIT = 3` for quick
verification runs — set it to `None` to process every `ENGLISH_OK` job
(~123 of 360 at last run), then re-run `main.py`.

## Configuration

### `config/candidate.json` — the applicant (used by step 6 / `3_bosch_job_apply.py`)

All personal answers live here; nothing personal is hardcoded in the flow.
Keys: `job_url`, `resume_path` (fallback when no tailored resume exists),
`candidate_email`, `expected_graduation` (MM/YYYY), `study_type`, `dual_study`,
`intends_further_degree`, `preferred_duration`, `preferred_period_start/_end`,
`bosch_other_position_consent`, `privacy_consent` (must stay `true`),
`additional_attachments` (≤10 MB each). SmartRecruiters credentials, if the
portal ever demands a login, come from the environment only
(`SMARTRECRUITERS_EMAIL` / `SMARTRECRUITERS_PASSWORD`).

### `sub_program_files/ollama_keys.json` — the LLM

Endpoint/model via `OLLAMA_HOST` / `OLLAMA_MODEL` env vars
(default `https://ollama.com`, `gpt-oss:120b`). Step 3 writes the working
keys to `active_ollama_keys.json`, which the resume stages read.

### `sub_program_files/prompt/` — the tailoring prompts

Six ATS prompt files (career objective, experience 1+2, projects 1+2, skills).
They generate ONLY from the fixed truthful candidate profile embedded in them.

## The apply automation (`3_bosch_job_apply.py`)

One-file Playwright automation for the Bosch / SmartRecruiters application
portal (`jobs.bosch.de` → `jobs.smartrecruiters.com/BoschGroup/...`).

- **Semantic automation only** — every field is located, its question text is
  read from the live DOM, normalized, and matched against bilingual (DE/EN)
  question patterns. No coordinates, no positional `nth()`, no index-based
  option selection.
- **Dry-run first** — the walk fills everything, validates, and stops before
  `Absenden`. Submission only happens with `--submit` + typed `YES`.
- **Never guesses** — unknown questions are reported and *block* submission;
  CAPTCHA stops the run with `CAPTCHA_DETECTED`; every fill/selection is read
  back from the DOM and verified.
- **Wrong-application guard** — the page must be a Bosch page and (if
  configured) match the expected job title.

Flow: job page → Apply now (same tab / new tab / redirect) → form verified →
resume upload (RESUME section only, verified) → email → Next → Bosch
pre-questions (DE/EN, fuzzy matched, config-driven) → consents → attachments →
full pre-submit validation → `Absenden` → confirmation detection.

Statuses: `SUCCESS` · `DRY_RUN` · `DISCOVERED` · `FAILED` · `CAPTCHA_DETECTED`
· `UNKNOWN_FORM`.

### DataDome / CAPTCHA on the oneclick form

SmartRecruiters' `oneclick-ui` application form (which Bosch postings open)
is protected by DataDome. The automation **never bypasses it**: it stops with
`CAPTCHA_DETECTED`, or pauses so you can solve the challenge manually in the
opened browser window:

```bash
python 6_apply_to_jobs.py --all --limit 1 --wait-after-captcha 240
```

The gate is probabilistic (per IP + session): runs sometimes pass untouched,
sometimes need one manual solve. The form itself renders inside open shadow
roots (`spl-*` web components); the inventory, upload, fill, question matching
and read-backs all pierce those — verified by `tests/test_oneclick_shadow.py`
(`python -m pytest tests/ -v`) against a local oneclick-identical fixture.

Direct CLI (bypassing step 6):

```bash
python 3_bosch_job_apply.py --discover        # dump the live form structure
python 3_bosch_job_apply.py --dry-run
python 3_bosch_job_apply.py --url "<JOB_URL>" --resume "<RESUME.pdf>" --submit
```

## Outputs at a glance

```
BOSCH_results.csv                  360 listings (title + link)
BOSCH_jobs_detailed.csv            30 columns + Language_Filter + Filter_Evidence
BOSCH_jobs_full.json               everything incl. raw description sections
program_files/output_bosch/
  2_filted_jobs.csv                ENGLISH_OK jobs in generator schema
  career_objective.json            per-job LLM components (4 files)
  experience.json / projects.json / skills.json
  resume/tex|pdf|docx/             one tailored resume per job
  resume_report.json               per-job build results
  apply_report.json                per-job application results (step 6)
results/                           apply-run audit: screenshots + result JSON
```

## Handling new / unknown questions

Bosch can change question wording, order, or add questions per posting:

1. The script detects any question block it cannot map and **stops before
   submit** with the text in `unknownQuestions` and `unknown-questions.png`.
2. Run `python 3_bosch_job_apply.py --discover`, open
   `results/bosch-discover-<jobid>.json`, find the question text and options.
3. Add a spec to `QUESTION_SPECS` in `3_bosch_job_apply.py` (key, kind
   `yesno|study_type|duration|date_mm_yyyy|date_range`, config name, DE+EN
   patterns — matching is fuzzy/normalized, umlauts folded, punctuation
   ignored) and add the answer to `config/candidate.json`.
4. Re-run the dry-run.

## Safety rules baked into the apply script

1. **Never invents data** — every answer comes from `config/candidate.json`;
   unknown questions are reported and block submission.
2. **Never confuses resume and attachments** — file inputs are classified by
   their surrounding section text.
3. **Never bypasses CAPTCHA** — detection stops with `CAPTCHA_DETECTED`
   (optionally waiting for manual solving with `--wait-after-captcha`).
4. **Never trusts a click** — email values, dates, dropdown selections and
   checkbox states are read back from the DOM and verified.
5. **Dry-run cannot submit** — `Absenden` is only reachable via `--submit`
   behind a typed `YES`, after full validation.
6. **No positional automation** — no coordinates, no `nth()`, no index-based
   `selectOption`.
7. **No arbitrary waits in the flow** — condition-based waiting only.
