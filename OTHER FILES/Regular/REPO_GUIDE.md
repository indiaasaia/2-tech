# Repository Guide: Job Automation Pipeline

> **Moved (2026-10-17):** the runnable pipeline now lives in [`E:\WorkSpace\2 Tech\2 Job Automation\REGULAR_APPLICATION`](../REGULAR_APPLICATION/README.md) (`python run.py --days N` inside it; it does not depend on this repo). The engine package `resume_content_improve_research/` was renamed `REGULAR_APPLICATION/engine/`; paths below that name the old package refer to it. The old `main.py`, dashboard and tests no longer run from here.

This file is a practical map of the repository, based on the source tree as inspected on 2026-10-11. It describes the current architecture, entrypoints, important data contracts, generated-output locations, test workflow, and known caveats. Treat source/configuration as authoritative if this guide ever drifts.

## 1. Project purpose

A Python job-application automation project focused on working-student and internship opportunities in Germany. It can collect postings from Stepstone and workingstudentjobs.de, filter jobs by freshness and domain/skill fit, create evidence-grounded resume content, verify and build resume PDFs/DOCX files, create tailored cover letters, score candidate-to-job fit, and prepare application bundles. A Streamlit dashboard provides scanning, resume browsing, and job tracking.

There is a current verification-heavy engine and a retained legacy prompt implementation:

- **Current generation (v2 engine):** `resume_content_improve_research/`, now invoked by `main.py` after the source-fetch/filter/key steps.
- **Legacy section generation:** `sub_program_files/resume_content/` and `program_files/4_create_resume_components.py` + `program_files/5_create_resume.py` are retained for reference but not called by the current top-level orchestrator. The older standalone `old_files/` archive has been removed.

## 2. Quick start and main commands

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run the full pipeline:

```bash
python main.py
python main.py --limit 3
```

For targeted checks or resumable runs, invoke v2 stages directly after stages 1-3 have prepared the input and key files.

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
| `main.py` | Top-level orchestrator for active steps 1-6. Stops dependent downstream work after a failure and returns nonzero if any step fails. |
| `README.md` | User-facing pipeline overview, commands, stages, outputs and setup. |
| `PROMPT_HANDBOOK.md` | Background on the original prompt-per-section system and its prompt design. It is historical documentation, not the authoritative description of v2. |
| `requirements.txt` | Runtime/test dependencies: pandas, requests, selenium, python-docx, rapidfuzz, streamlit, pytest. |
| `.gitignore` | Ignores local API-key JSON, caches, `program_files/output/`, logs, and `.freebuff/`. It does **not** ignore `program_files/output_v2/`. |
| `program_files/` | Job ingest/filter stages, compatibility/legacy stages, dashboard, dated run helpers and diagnostic logs. |
| `resume_content_improve_research/` | Current v2 resume/cover-letter engine, KB, templates, verification, tests, research and experiments. |
| `sub_program_files/` | Scraper wrappers, Ollama request helpers, and retained legacy prompt/section-generation modules. |
| `app/` | Shared Stepstone/workingstudentjobs fetch implementations and common config/date/activity helpers imported by scraper wrappers. |
| `make_resume.py` | Independent older/static ReportLab resume and cover-letter generator. Not called by current v2 pipeline. |
| `make_cert_bw.py` | Utility for rendering a certificate PDF into a black-and-white PDF/chunks. Requires `pypdfium2` and Pillow, which are not in the repository's top-level requirements list. |
| `file_server.py`, `bridge.html`, `bridge2.html` | Local HTTP/CORS file-transfer/bridge utilities; not part of resume generation. |
| `certificate_of_enrolment.pdf`, `certificate_of_enrolment_small.pdf` | Candidate source documents retained as inputs (not generated run output). Handle as sensitive personal data. |

## 4. Current architecture (engine v3)

The core package lives in `resume_content_improve_research/`:

- `config.py`: Central project/package paths, output paths, Ollama model/host, call budgets, gate/score thresholds, date rules and template tokens. Main output root is `program_files/output_v2/`; source job inputs are under `program_files/output/`.
- `knowledge_base/`: Approved candidate facts (`candidate_kb.json`), aliases (`alias_map.json`), domain filters (`domain_filters.json`), local ESCO English skill data, and `validate_kb.py`. The KB is the fact authority; generated content should not invent experience, tools, metrics, or projects.
- `generation/`: Domain filter and scored alignment; structured JD analyst; analyst post-checks (incl. posting-language detection); **keyword plan** (`keywords.py`, lexicon `knowledge_base/tech_lexicon.json`); **truthful per-entry vocabulary** (`evidence_vocab.py`, `knowledge_base/evidence_synonyms.json`); **keyword injector** (`keyword_injector.py`, category Skills rows); **claim check** (`claim_check.py`, unbacked keywords never stated as work done); typography normalization (`text_norm.py`); claimable-set construction; constrained LLM generation; deterministic tailoring; factual grounding; cover-letter generation (LLM paragraphs + deterministic logistics); and portal bundle generation. Policy: every job keyword is printed (Skills rows); facts and bullets stay KB-only. See RESUME_CREATION.md section 0.
- `templates/`: Collision-resistant LaTeX token filling, the v3 resume template (`core_resume_template_v3.tex`, max 2 pages), the document model (`render.py`) that feeds both PDF and DOCX, cover-letter templates, PDF compiler integration, and DOCX builders.
- `verification/`: Resume G1-G3 gates, the **keyword gate** (`keyword_gate.py`: every plan keyword in PDF and DOCX text; KB-backed share), letter L1-L4 gates, PDF parse simulation, coverage, scorecard, fit-tier triage, and **interview prep** sheets (`prep.py` -> `output_v2/prep/`, `learning_priorities.md`).
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
3. Build the keyword plan (analyst terms + lexicon sweep of the whole ad, ad spelling wins; achievement terms like "Published CVE" go to eligibility, never printed) and the claimable set (KB skills + plan keywords).
4. Generate objective, skills, two real experience stints, and real projects (up to three prompt groups/calls), then apply deterministic tailoring.
5. Run pre-build G2/G3 gates plus the per-entry vocabulary check; regenerate with the findings fed back into the prompts, up to the configured limit. Hard G2/G3 failures park the job; leftover vocabulary findings are resolved in step 5 by dropping exactly those bullets.
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

- The legacy steps 4/5 remain standalone scripts; the README's pipeline table now describes the active v2 flow.
- `main.py` imports fetch/filter/key functions, then directly invokes v2 `run_step4.run_pipeline`, `run_step5.main`, and `run_step6.run_pipeline` in dependency order. It exposes generation options (`--limit`, `--jobs`, `--force`, `--no-tailor`, `--no-domain-filter`, `--loose-filter`) and `--force-letters`. Nonzero stage results halt downstream stages. `run_dashboard.py` separately launches the Streamlit UI.
- `program_files/4_create_resume_components.py` and `program_files/5_create_resume.py` remain as legacy standalone steps; they are not used by `main.py`.
- The v2 step4 expects `program_files/output/2_filted_jobs.csv`. Generated output directories are recreated by successful pipeline runs.

Do not use `program_files/_generate_approved_applications.py` without supplying/reviewing its expected explicit allowlist at `program_files/output/fresh_run_2026-10-05/FINAL_eligible_jobs.csv`; it is a dated, approved-CSV-only delivery runner, not the default scraper pipeline. Other underscored scripts are one-off helpers or validation/recovery tools; inspect their header and input paths before running.

## 6. v1 and archived code

- `sub_program_files/resume_content/1_career_objective.py` through `4_skills.py` implement per-section LLM prompts and store JSON under `program_files/output/`; the old `program_files/4_create_resume_components.py` invokes them.
- `program_files/5_create_resume.py` is a legacy LaTeX+DOCX assembler consuming those four JSON stores and `sub_program_files/resume_content/core_resume_template.tex`.
- `app/core` and `app/phase1` hold the shared scraper implementations formerly nested under `old_files/`; scraper wrappers import these as `app.phase1.*` from the project root.
- `sub_program_files/resume_content/` and the numbered legacy step4/5 scripts remain separate v1 code paths, not part of the main v2 run.
- `make_resume.py` is an independent hard-coded, static PDF generator and should not be mistaken for the generated-per-job pipeline.

## 7. Candidate KB and truthfulness policy

`resume_content_improve_research/knowledge_base/candidate_kb.json` is the current source of truth. It was observed with status `APPROVED`, a profile, 2 education entries, 2 experience records, 7 project records (only marked real/main projects are eligible according to policy), 1 research item, 25 global skills, 10 certifications, and 4 achievements. `alias_map.json` provides 48 alias entries in the checked-in version; `domain_filters.json` defines families, demand/industry terms and score policy.

KB runtime loading requires `status == APPROVED`. `validate_kb.py` validates evidence references, allowed/forbidden skills, project reality, and no-fabricated-metrics policy. Do not loosen gates to force a resume through; update candidate-approved evidence/KB facts when genuinely appropriate.

## 8. Configuration, secrets and external dependencies

- Ollama endpoint/model can be changed with `OLLAMA_HOST` / `OLLAMA_MODEL`. Default host is `https://ollama.com`; default model is `gpt-oss:120b`.
- Keys are local ignored JSON files in `sub_program_files`; active keys are selected by step3 and consumed by current engine helpers. Keep credentials out of source, reports, or this guide.
- Selenium scraping needs Chrome/Chromium and external sites may change selectors or rate limits.
- PDF generation uses the bundled `tools/tectonic.exe`, then PATH `tectonic` or `pdflatex`.
- Streamlit is used for dashboard; python-docx for Word output; pandas for job CSVs; rapidfuzz and the ESCO/alias data for matching; requests for Ollama and scraping.
- No Docker/service/database is required by the core project.

## 9. Tests and fixture isolation

The v2 test suite is `resume_content_improve_research/tests/`. It covers analyst postchecks, cover letters, domain filtering, motivation profiling, token fill, gates, hardening, date parsing, KB flow, end-to-end document construction, and tailoring. Research script `empirical_parser_test.py` and files under `experiment/` are benchmark/research tools, not ordinary unit tests.

Tests are completely isolated from previous generated outputs (`program_files/output_v2/`). `tests/test_tailoring.py` includes a self-contained fallback fixture so that test collection and execution succeed on a completely fresh/purged repository (all 234 unit tests pass).

## 10. Generated output policy / current workspace state

Generated runtime outputs are recreated by the pipeline and should not be checked into source control:

- `program_files/output/`: raw and filtered job CSVs and dashboard state/logs.
- `program_files/output_v2/`: v2 components, reports, shortlist, resume and cover-letter artifacts, quarantined failures, and bundle manifest.
- `jsdata/` (historical tree): prior browser-transfer payloads, PDFs, Base64 chunks and evaluation JS; not part of core pipeline.
- Root-level prior output payloads included generated resume/letter/highlight PDFs, certificate conversion PDF/previews, base64/chunk transfer text, and render intermediates. The original certificate PDFs remain as user-provided inputs.

Generated output folders were cleaned and will be recreated as needed after pipeline execution. `.gitignore` now excludes both pipeline output directories and known browser-transfer payloads.

## 11. Suggested first-read order for a future session

1. Read this guide and `README.md` for orientation.
2. For current behavior, inspect `main.py`, `resume_content_improve_research/config.py`, `run_step4.py`, `run_step5.py`, `run_step6.py`.
3. For facts and filter policy, inspect `knowledge_base/candidate_kb.json` (avoid echoing personal data), `alias_map.json`, `domain_filters.json`.
4. For a bug, read the corresponding module and nearby tests before editing.
5. Inspect `git status` first. The preceding cleanup intentionally removed tracked generated output files; do not restore them unless explicitly requested.

## 12. Working conventions

- Prefer current v2 implementation for new generation/verification changes; avoid adding behavior to the retained legacy v1 section scripts unless explicitly requested.
- Keep generated artifacts out of source control; generated data can contain personal and job-application information.
- Do not run live scraping, Ollama calls, or document generation just to inspect the project; those make external requests or recreate output files.
- Treat candidate profile and certificate PDFs as private. Avoid quoting their personal details in logs, guides, commits, or user-facing summaries.
- Keep tests deterministic and independent of previous-run files; tests should use temporary directories/fixtures rather than `program_files/output_v2` state.
