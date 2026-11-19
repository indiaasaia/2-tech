# Current Status — All Folders (2026-09-18)

## Folder Inventory

| Folder | Status | Note |
|---|---|---|
| `bosch/` | ✅ REAL — full pipeline (3 phases) | fetch → filter → LLM resumes → apply |
| `mercedes/` | ✅ REAL — full pipeline (3 phases) | fetch → filter → LLM resumes → apply (+ Taleo) |
| `infineon/` | ✅ REAL — full pipeline (3 phases) | fetch → filter → LLM resumes → apply |
| `bmw/` | ⚠️ FETCH ONLY (phase 1) | single fetcher script + fetched data |
| `simense/` | ⚠️ FETCH ONLY (phase 1) | single fetcher script + fetched data |
| `SAP FETCHER/` | ✅ REAL — full pipeline (3 phases) | fetch → filter → LLM resumes → apply; **live submits already recorded** |
| `boasch_copy/` | 🗑️ DUPLICATE copy of bosch | ignore / safe to delete |
| `mercedes_copy/` | 🗑️ DUPLICATE copy of mercedes | ignore / safe to delete |

## The 3 phases checked
1. **Job fetching** (scrape/search API → CSV/JSON)
2. **Resume generation** (language filter → LLM component stages → tailored PDF/DOCX)
3. **Apply automation** (browser bot with dry-run safety, submit only on explicit flag)

## Folder Details

### bosch/ — COMPLETE pipeline ✅
- Steps: `1_bosch_Jobs_fetching.py` → `2_language_differntiate.py` → `4_resume_create.py` → `5_final_resume.py` → `6_apply_to_jobs.py`, orchestrated by `main.py`.
- Known issue: `main.py` step 3 imports `3_test_ollama_keys` but the module lives in `program_files/` — step 3 crashes without a root-level wrapper (mercedes/infineon have one; bosch is missing it).
- Apply: `3_bosch_job_apply.py` (portal) + `6_apply_to_jobs.py` (orchestrator).
- Tests: `tests/` — 8/8 passed this session.
- Artifacts present: BOSCH_results.csv, _detailed.csv, _full.json, output_bosch/ with resume PDFs.

### mercedes/ — COMPLETE pipeline ✅ (deepest, verified end-to-end this session)
- Steps: `1_MERCEDES_Jobs_fetching.py` (beesite API, paginated) → `2_MERCEDES_language_filter.py` (rule-based DE/EN; ran live: 210 jobs → 164 ENGLISH_OK / 46 GERMAN_REQUIRED) → `2_MERCEDES_create_resumes.py` (resumable LLM stages) → `3_MERCEDES_ollama_keys.py` (live key test ✅) → `3_MERCEDES_final_resume.py` (tectonic PDF) → `4_MERCEDES_job_apply.py` (Workday bot, dry-run default) + `5_apply_taleo.py` + `batch_apply.py`.
- Artifact chain verified: 16 adapted jobs → 18 map rows (2 aliases) → all 16 PDFs/DOCX exist.
- Minor: hardcoded email/resume-name in `_verify_review_page` (~line 864) instead of config.

### infineon/ — COMPLETE pipeline ✅
- Steps: `1_INFINEON_Jobs_fetching.py` → `4_INFINEON_create_resumes.py` (includes language filter + LLM components) → `5_INFINEON_final_resume.py`, orchestrated by `main.py` (per-step error isolation).
- Apply: `infineon_job_apply.py` (standalone; does NOT read `config/candidate.json` — answers are hardcoded; config file there is a stale Mercedes copy).
- Extras: `recover_flagged_experience.py` / `recover_flagged_skills.py`, resume HTML page.

### bmw/ — FETCH ONLY ⚠️
- `BMW_Jobs_fetching.py` (uses curl_cffi) + fetched data (results/detailed/full). No filter, no resume generation, no apply automation. Phase 1 of 3.

### simense/ — FETCH ONLY ⚠️
- `SIMENSE_jobs_fetching.py` (scrapes Siemens jobs site, extracts apply_url etc.) + fetched data. No filter, no resume generation, no apply automation. Phase 1 of 3.

### SAP FETCHER/ — COMPLETE pipeline ✅ (newest, fully working)
- Steps (orchestrated by `main.py`): `1_sap_job_fetcher.py` (stdlib-only scrape of jobs.sap.com, paginated, → `sap_results.csv`) → `2_language_differntiate.py` (EN/DE filter; 17 ENGLISH_OK in current data) → `3_ollama_keys.py` → `4_resume_create.py` → `5_final_resume.py` (all compile OK).
- Apply: `sap_job_apply.py` (1,121 lines, SuccessFactors bot; dry-run default, `--submit` + YES confirmation required).
- **Proven working live:** `results/` contains screenshots + result JSONs for multiple jobs with `"status": "SUCCESS", "dryRun": false` — e.g. job 1387969433 submitted 2026-09-14 with confirmation message verified.
- Resume artifacts present in `program_files/output_sap/` (components JSONs, resume PDFs, report).
- Extras: `generate_resume_page.py`, `recover_flagged_skills.py`.

## Gaps / Action Items
1. **bosch/**: add root-level `3_test_ollama_keys.py` wrapper (or fix main.py import path) — step 3 crash.
2. **infineon/**: apply script ignores config/candidate.json; config is a stale Mercedes copy.
3. **bmw/ & simense/**: missing phases 2 (resume generation) and 3 (apply) — need pipeline port from mercedes/infineon template.
4. **mercedes/**: replace hardcoded review-page checks with config values.
5. **Delete duplicates**: `boasch_copy/`, `mercedes_copy/` (user confirmation recommended).
