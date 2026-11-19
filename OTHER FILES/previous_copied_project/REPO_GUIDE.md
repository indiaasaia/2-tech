# Repository Guide: Job Automation Pipeline

This file is a practical map of the repository, based on the source tree as inspected on 2026-10-11. It describes the current architecture, entrypoints, important data contracts, generated-output locations, test workflow, and known caveats. Treat source/configuration as authoritative if this guide ever drifts.

## 1. Project purpose

A Python job-application automation project focused on working-student and internship opportunities in Germany. It can collect postings from Stepstone and workingstudentjobs.de, filter jobs by freshness and domain/skill fit, create evidence-grounded resume content, verify and build resume PDFs/DOCX files, create tailored cover letters, score candidate-to-job fit, and prepare application bundles. A Streamlit dashboard provides scanning, resume browsing, and job tracking.

There are two generations of the pipeline in the repository:

- **Current generation (v2 engine):** `resume_content_improve_research/`; this is the verification-heavy implementation described below. The top-level `main.py` currently wires the older section-generation steps 1-5, not the v2 step4-6 runners.
- **Legacy generation (v1 / standalone prototype):** `sub_program_files/resume_content/` and `program_files/4_create_resume_components.py` + `program_files/5_create_resume.py` implement an older prompt-per-section path; `old_files/` contains an even earlier prototype. Some wrappers/docs still describe the legacy path, so check actual call sites before assuming all paths use v2.

## 2. Quick start and main commands

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run the legacy/top-level pipeline as currently wired:

```bash
python main.py
```

`README.md` also shows `python main.py --limit 3`, but the inspected `main.py` does not parse CLI arguments or forward a limit; do not rely on that option until the entrypoint is updated. For the v2 engine, use the direct stage commands in order after stages 1-3 have prepared the input and key files.

Launch the dashboard:

```bash
python run_dashboard.py
```

Run individual current-engine stages directly:

```bash
python resume_content_improve_research/run_step4.py --help
python resume_content_improve_research/run_step5.py --help
python resume_content_improve_research/run_step6.py --help
```

Run tests and KB validation:

```bash
python -m pytest resume_content_improve_research/tests -q
python resume_content_improve_research/knowledge_base/validate_kb.py
```

The full pipeline needs a working Ollama Cloud key, network access, reachable job sites/browser support (Selenium + Chrome/Chromium), and a LaTeX compiler for PDFs (`tectonic` preferred, otherwise `pdflatex`). DOCX output uses `python-docx`.

## 3. Top-level map

| Path | Role |
|---|---|
| `main.py` | Top-level orchestrator for legacy steps 1-5. Imports each independently, prints a summary, and catches exceptions per step; inspect the summary/exit code rather than assuming an early step stopped execution. |
| `README.md` | User-facing pipeline overview and original documented commands. Some portions still describe the v1 section-generator flow; compare with current step4-6 source. |
| `PROMPT_HANDBOOK.md` | Background on the original prompt-per-section system and its prompt design. It is historical documentation, not the authoritative description of v2. |
| `requirements.txt` | Runtime/test dependencies: pandas, requests, selenium, python-docx, rapidfuzz, streamlit, pytest. |
| `.gitignore` | Ignores local API-key JSON, caches, `program_files/output/`, logs, and `.freebuff/`. It does **not** ignore `program_files/output_v2/`. |
| `program_files/` | Job ingest/filter stages, compatibility/legacy stages, dashboard, dated run helpers and diagnostic logs. |
| `resume_content_improve_research/` | Current v2 resume/cover-letter engine, KB, templates, verification, tests, research and experiments. |
| `sub_program_files/` | Scraper wrappers, Ollama request helpers, legacy prompt files and v1 section-generation modules. |
| `old_files/` | Archived standalone three-phase prototype and candidate profile. Not the current engine, but some compatibility imports still reach its `app` package. |
| `make_resume.py` | Independent older/static ReportLab resume and cover-letter generator. Not called by current v2 pipeline. |
| `make_cert_bw.py` | Utility for rendering a certificate PDF into a black-and-white PDF/chunks. Requires `pypdfium2` and Pillow, which are not in the repository's top-level requirements list. |
| `file_server.py`, `bridge.html`, `bridge2.html` | Local HTTP/CORS file-transfer/bridge utilities; not part of resume generation. |
| `certificate_of_enrolment.pdf`, `certificate_of_enrolment_small.pdf` | Candidate source documents retained as inputs (not generated run output). Handle as sensitive personal data. |

## 4. Current v2 architecture

The core package lives in `resume_content_improve_research/`:

- `config.py`: Central project/package paths, output paths, Ollama model/host, call budgets, gate/score thresholds, date rules and template tokens. Main output root is `program_files/output_v2/`; source job inputs are under `program_files/output/`.
- `knowledge_base/`: Approved candidate facts (`candidate_kb.json`), aliases (`alias_map.json`), domain filters (`domain_filters.json`), local ESCO English skill data, and `validate_kb.py`. The KB is the fact authority; generated content should not invent experience, tools, metrics, or projects.
- `generation/`: Domain filter and scored alignment; structured JD analyst; analyst post-checks; claimable-set construction; constrained LLM generation; deterministic tailoring; normalization/KB loading; factual static content; cover-letter generation; and portal bundle generation.
- `templates/`: Collision-resistant LaTeX token filling, resume/cover-letter templates, PDF compiler integration, and DOCX builders.
- `verification/`: Resume G1-G3 gates, letter L1-L4 gates, PDF parse simulation, factual/skill coverage, scorecard, and shortlist ranking.
- `tests/`: Unit, integration, template, verification, and real-JD tests for the v2 engine.
- `ab_test/`, `experiment/`, research reports and parser experiments: design evidence/history and measurement tools, not runtime dependencies of each normal job run.

### Step 1-3: ingest and preliminaries

1. `program_files/1_fetch_jobs.py` fetches Stepstone + workingstudentjobs.de via `sub_program_files/stepstone_scraper.py` and `workingstudent_scraper.py`. It independently catches each source's errors and writes `program_files/output/todays_overall_jobs.csv`.
2. `program_files/2_filter_jobs.py` reads that CSV, chooses `posted_time` then `detail_online_date`, parses English/German relative dates or ISO timestamps, drops unparseable/stale items and writes `program_files/output/2_filted_jobs.csv`. The current freshness rule is today/yesterday in local calendar time.
3. `program_files/3_test_ollama_keys.py` tests keys from ignored `sub_program_files/ollama_keys.json` against `${OLLAMA_HOST:-https://ollama.com}/v1/chat/completions`, model `${OLLAMA_MODEL:-gpt-oss:120b}`, and writes active keys to ignored `sub_program_files/active_ollama_keys.json`. Do not expose key values in logs or docs.

### Step 4: analyze, gate and generate truthful content

`resume_content_improve_research/run_step4.py` reads the filtered jobs CSV and processes serially (free Ollama plan constraint). Its per-job flow:

1. Deterministic domain family gate; jobs without a family signal go through a configurable skill-alignment score (default minimum 60%).
2. One structured LLM JD-analysis call (with repair behavior), followed by deterministic language/tier/dedup post-checks.
3. Build a claimable set from KB-licensed skills and JD tools that may only be mirrored as requirements, never claimed as owned.
4. Generate objective, skills, two real experience stints, and real projects (up to three prompt groups/calls), then apply deterministic tailoring.
5. Run pre-build hallucination/integrity gates; regenerate with explicit violations up to the configured limit, then park failures.
6. Checkpoint each job in `program_files/output_v2/components_v2.json`, preserving previous gated results when appropriate. Gated records include `analysis`, generated `components`, `letter_input`, and metadata. Parked records retain failure reasons.

Step4 options: `--limit N`, `--jobs URL_SUBSTRINGS`, `--force`, `--no-tailor`, `--no-domain-filter`, and `--loose-filter`. It requires an active Ollama key and an approved candidate KB.

### Step 5: build and verify resumes

`resume_content_improve_research/run_step5.py` consumes `components_v2.json`, builds the filled TeX, PDF and DOCX, parses the PDF back, checks artifact gates, scores factual/keyword coverage against the parsed artifact, produces gap reports, and writes:

- `program_files/output_v2/resume_report.json`
- `program_files/output_v2/shortlist.json`
- `program_files/output_v2/resume/{tex,pdf,docx}/...`
- failed artifacts/reasons under `program_files/output_v2/failed/`

The source-intent JSON is not treated as proof of the built artifact: gates and coverage inspect parsed PDF text. A verified resume must pass pre-build and post-build checks; the configured scorecard ranks strong/good/weak/poor fit and reports gaps rather than fabricating qualifications.

### Step 6: cover letters and portal bundles

`resume_content_improve_research/run_step6.py` consumes the step4 record (including `letter_input`) and step5 report. It builds a deterministic letter skeleton, generates/gates the content, fills German or English LaTeX template, compiles PDF and creates DOCX/plain-text copies. It writes separate letter artifacts and:

- `program_files/output_v2/letters_report.json`
- `program_files/output_v2/application_bundles.json`
- `program_files/output_v2/letters/{tex,pdf,docx,textfield}/...`

Letters run after resumes so a parked letter does not invalidate the already-verified resume. Portal manifests describe the likely upload slot and missing artifacts; they are guidance, not automatic submission. No job application is submitted automatically.

## 5. Entry-point discrepancy to know

There is a notable mismatch between docs and `main.py`:

- `README.md` says `main.py` runs steps 1-5 and that steps 4/5 are `program_files/4_create_resume_components.py` / `program_files/5_create_resume.py` (the older section-JSON flow).
- Current `main.py` imports `1_fetch_jobs.fetch_jobs`, `2_filter_jobs.filter_jobs`, `3_test_ollama_keys.test_ollama_keys`, `4_create_resume_components.main`, and `5_create_resume.main`. Its step4/5 targets are legacy v1 implementations; it does not call v2 `run_step4/5/6`. `6_dashboard.py` is the separately launched Streamlit app, not a pipeline stage.
- The v2 direct stage scripts are the explicit entrypoints for the current engine. To process v2 end-to-end, run steps 1-3, then `run_step4.py`, `run_step5.py`, and `run_step6.py` in that order. Note that the v2 step4 expects `program_files/output/2_filted_jobs.csv`; the legacy step4 wrapper instead writes older component JSON under `program_files/output/`, so do not run both paths against shared state without understanding the input/output contracts.
- `README.md` does not yet mention step 6 in its documented pipeline table and old output locations described there have been deleted during cleanup. Generated output directories are recreated by successful pipeline runs.

Do not use `program_files/_generate_approved_applications.py` without supplying/reviewing its expected explicit allowlist at `program_files/output/fresh_run_2026-10-05/FINAL_eligible_jobs.csv`; it is a dated, approved-CSV-only delivery runner, not the default scraper pipeline. Other underscored scripts are one-off helpers or validation/recovery tools; inspect their header and input paths before running.

## 6. v1 and archived code

- `sub_program_files/resume_content/1_career_objective.py` through `4_skills.py` implement per-section LLM prompts and store JSON under `program_files/output/`; the old `program_files/4_create_resume_components.py` invokes them.
- `program_files/5_create_resume.py` is a legacy LaTeX+DOCX assembler consuming those four JSON stores and `sub_program_files/resume_content/core_resume_template.tex`.
- `old_files/app/phase1`, `phase2`, `phase3`, `app/core` and `old_files/run*.py` form the standalone earlier prototype. Its candidate profile is `old_files/data/candidate_profile.json`; generated outputs formerly went to `old_files/data/output/` (now cleaned).
- The wrappers in `sub_program_files/stepstone_scraper.py` and `workingstudent_scraper.py` import `app.phase1.*`; current `program_files/1_fetch_jobs.py` inserts `old_files` into `sys.path` to satisfy that. This is a compatibility dependency even though `old_files` is archived.
- `make_resume.py` is another independent hard-coded, static PDF generator and should not be mistaken for the generated-per-job pipeline.

## 7. Candidate KB and truthfulness policy

`resume_content_improve_research/knowledge_base/candidate_kb.json` is the current source of truth. It was observed with status `APPROVED`, a profile, 2 education entries, 2 experience records, 7 project records (only marked real/main projects are eligible according to policy), 1 research item, 25 global skills, 10 certifications, and 4 achievements. `alias_map.json` provides 48 alias entries in the checked-in version; `domain_filters.json` defines families, demand/industry terms and score policy. `old_files/data/candidate_profile.json` is legacy and should not supersede the current KB.

KB runtime loading requires `status == APPROVED`. `validate_kb.py` validates evidence references, allowed/forbidden skills, project reality, and no-fabricated-metrics policy. Do not loosen gates to force a resume through; update candidate-approved evidence/KB facts when genuinely appropriate.

## 8. Configuration, secrets and external dependencies

- Ollama endpoint/model can be changed with `OLLAMA_HOST` / `OLLAMA_MODEL`. Default host is `https://ollama.com`; default model is `gpt-oss:120b`.
- Keys are local ignored JSON files in `sub_program_files`; active keys are selected by step3 and consumed by current engine helpers. Keep credentials out of source, reports, or this guide.
- Selenium scraping needs Chrome/Chromium and external sites may change selectors or rate limits.
- PDF generation uses bundled tectonic candidates in `old_files/tools/tectonic.exe` or `tools/tectonic.exe`, then PATH `tectonic` or `pdflatex` (per engine config/build logic). The old_files tool may be archived but referenced as first preference.
- Streamlit is used for dashboard; python-docx for Word output; pandas for job CSVs; rapidfuzz and the ESCO/alias data for matching; requests for Ollama and scraping.
- No Docker/service/database is required by the core project.

## 9. Tests and known test limitation

The v2 test suite is `resume_content_improve_research/tests/`. It covers analyst postchecks, cover letters, domain filtering, token fill, gates, hardening, date parsing, KB flow, end-to-end document construction, and tailoring. `old_files/tests/test_phase1.py` belongs to the archived prototype. Research script `empirical_parser_test.py` and files under `experiment/` are not all ordinary unit tests.

After generated outputs were cleaned, running `python -m pytest resume_content_improve_research/tests -q` was attempted and **collection failed** in `tests/test_tailoring.py` because its module-level fixture reads a specific previous run artifact at an absolute path ending in `program_files/output_v2/components_v2.json`. The test needs fixture isolation or a temporary test fixture; do not restore the old generated outputs merely to make collection pass. This failure is an existing test coupling to generated state, not evidence that output cleanup damaged maintained source.

## 10. Generated output policy / current workspace state

Generated runtime outputs are recreated by the pipeline and should not be checked into source control:

- `program_files/output/`: raw and filtered job CSVs, v1 component JSON, dashboard state/logs.
- `program_files/output_v2/`: v2 components, reports, shortlist, resume and cover-letter artifacts, quarantined failures, and bundle manifest.
- `old_files/data/output/`: legacy prototype outputs.
- `jsdata/` (historical tree): prior browser-transfer payloads, PDFs, Base64 chunks and evaluation JS; not part of core pipeline.
- Root-level prior output payloads included generated resume/letter/highlight PDFs, certificate conversion PDF/previews, base64/chunk transfer text, and render intermediates. Original certificate PDFs were preserved as input.

These output directories were removed in the cleanup preceding creation of this guide; they will reappear as needed after pipeline execution. Note `.gitignore` currently ignores only `program_files/output/`, not v2 output or all root transfer artifacts. Consider expanding ignore policy in a separate change.

## 11. Suggested first-read order for a future session

1. Read this guide and `README.md` for orientation.
2. For current behavior, inspect `main.py`, `resume_content_improve_research/config.py`, `run_step4.py`, `run_step5.py`, `run_step6.py`.
3. For facts and filter policy, inspect `knowledge_base/candidate_kb.json` (avoid echoing personal data), `alias_map.json`, `domain_filters.json`.
4. For a bug, read the corresponding module and nearby tests before editing.
5. Inspect `git status` first. The preceding output cleanup intentionally left a large set of tracked deletions; do not restore or overwrite them unless explicitly asked.

## 12. Working conventions

- Prefer current v2 implementation for new generation/verification changes; avoid adding more behavior to the legacy v1 section scripts unless explicitly requested.
- Keep generated artifacts out of source control; generated data can contain personal and job-application information.
- Do not run live scraping, Ollama calls, or document generation just to inspect the project; those make external requests or recreate output files.
- Treat candidate profile and certificate PDFs as private. Avoid quoting their personal details in logs, guides, commits, or user-facing summaries.
- Keep tests deterministic and independent of previous-run files; tests should use temporary directories/fixtures rather than `program_files/output_v2` state.
