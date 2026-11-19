# 1_BOSCH — Bosch Student-Jobs Pipeline (fetch → filter → hub resumes → apply)

Bosch Group student jobs, end to end. Steps 1–2 run here; resume creation is
delegated to the shared hub `../resume_creation/` (the proven V2 engine);
application automation drives the SmartRecruiters portal with the hub's
tailored resumes.

## Run

```bash
python main.py --limit 2        # steps 1–3: fetch -> filter -> hub resumes (first 2 jobs)
python main.py                  # steps 1–3 over everything (LLM cost! resumes are per-job)
python main.py --apply --job-url <url> --dry-run    # + step 4 (default without --submit)
python 6_apply_to_jobs.py --all --submit --wait-after-captcha 300   # supervised batch apply
```

## Steps

| Step | File | What it does | Output |
|---|---|---|---|
| 1 | `1_BOSCH_Jobs_fetching.py` | Bosch list API (Student entry-level) + SmartRecruiters posting API + BSH HTML details | `BOSCH_results.csv`, `BOSCH_jobs_detailed.csv`, `BOSCH_jobs_full.json` |
| 2 | `2_language_filter.py` | Rule-based ENGLISH_OK / GERMAN_REQUIRED / UNSURE, evidence sentence stored per job (in place) | `Language_Filter`, `Filter_Evidence` columns |
| 3 | `../resume_creation/run_resume_creation.py bosch` | Hub: prepare (full fetch JSON → engine schema) → domain gate → LLM components → tectonic PDF/DOCX + verification gates + scorecard | hub `output_v2/state/`, `resume_bosch/`, `job_resume_map_bosch.csv` |
| 4 | `6_apply_to_jobs.py` → `3_bosch_job_apply.py` | Playwright apply with the tailored resume per job (dry-run by default) | `results/` (screenshots + result JSONs) |

## The apply automation (`3_bosch_job_apply.py`)

One-file Playwright automation for `jobs.bosch.de` → `jobs.smartrecruiters.com/BoschGroup/...`
(oneclick form inside open shadow roots of `spl-*` web components).

- **Semantic only** — every control located by meaning; question text read from
  the live DOM, matched against bilingual DE/EN `QUESTION_SPECS`; no
  coordinates, no `nth()`, no index-based selection.
- **Config-driven** — all personal answers come from `config/candidate.json`;
  unknown questions are reported and block submission; nothing is invented.
- **Verified fills** — email, dates, dropdowns, checkboxes are read back from
  the DOM after filling.
- **Dry-run first** — full walk, stop before `Absenden`; submission requires
  `--submit` + typed `YES`.
- **CAPTCHA: never bypassed** — DataDome stops the run with `CAPTCHA_DETECTED`,
  or waits for a manual solve with `--wait-after-captcha N` (the gate is
  probabilistic per IP/session; in practice a human solves it once per
  application in the visible browser window).

Statuses: `SUCCESS` · `DRY_RUN` · `DISCOVERED` · `FAILED` · `CAPTCHA_DETECTED` · `UNKNOWN_FORM`.

Tests (run from this folder): `python -m pytest tests/ -v` — 8 deterministic
shadow-DOM tests against a local oneclick-identical fixture.

## Handling new / unknown questions

1. Dry-run stops with the question text in `unknownQuestions` + `unknown-questions.png`.
2. `python 3_bosch_job_apply.py --discover` → `results/bosch-discover-<jobid>.json`.
3. Add a spec to `QUESTION_SPECS` (key, kind, config name, DE+EN patterns) and
   the answer to `config/candidate.json`.
4. Re-run the dry-run.

## Notes

- The hub owns everything resume-related: keys (`resume_creation/sub_program_files/`),
  prompts, templates, tectonic, per-company state. This folder deliberately
  carries no resume machinery anymore.
- SmartRecruiters credentials, if the portal ever demands a login, come from the
  environment only (`SMARTRECRUITERS_EMAIL` / `SMARTRECRUITERS_PASSWORD`).
