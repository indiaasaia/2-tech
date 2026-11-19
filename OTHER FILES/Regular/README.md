# Job -> Verified Resume Pipeline

> **Moved (2026-10-17):** the runnable pipeline now lives in [`E:\WorkSpace\2 Tech\2 Job Automation\REGULAR_APPLICATION`](../REGULAR_APPLICATION/README.md) (`python run.py --days N` inside it; it does not depend on this repo). The engine package `resume_content_improve_research/` was renamed `REGULAR_APPLICATION/engine/`; paths below that name the old package refer to it. The old `main.py`, dashboard and tests no longer run from here.

Scrapes fresh working-student jobs in Germany, filters out-of-domain postings,
then generates **one gate-verified ATS resume per job** (PDF + DOCX, up to 2
pages) that carries **100% of the job ad's keywords**, a cover letter per job,
an interview-prep sheet, and a shortlist ranked by real fit.

```text
python main.py                 # full pipeline: fetch -> filter -> keys -> generate -> verify -> letters
python main.py --limit 3       # first run: generate for at most 3 jobs
python main.py --jobs URL_PART # restrict generation and letters to matching job URLs
python run_dashboard.py        # dashboard: scanner, resumes + letters, learn-before-interview, tracker
python main.py --jobs URL_PART --force   # regenerate selected jobs with the current engine (uses the LLM)
```

## Pipeline

| Step | Script | What it does | Main output |
|------|--------|--------------|-------------|
| 1 | `program_files/1_fetch_jobs.py` | Scrape Stepstone + workingstudentjobs.de | `program_files/output/todays_overall_jobs.csv` |
| 2 | `program_files/2_filter_jobs.py` | Keep postings from yesterday or today | `program_files/output/2_filted_jobs.csv` |
| 3 | `program_files/3_test_ollama_keys.py` | Test Ollama keys, keep the working ones | `sub_program_files/active_ollama_keys.json` |
| 4 | `resume_content_improve_research/run_step4.py` | Domain gate -> JD analyst -> claimable set -> constrained generation -> gates | `program_files/output_v2/components_v2.json` |
| 5 | `resume_content_improve_research/run_step5.py` | Build PDF + DOCX -> parse back -> gates -> scorecard -> triage | `program_files/output_v2/resume_report.json`, `shortlist.json` |
| 6 | `resume_content_improve_research/run_step6.py` | Generate/gate cover letters and portal bundles | `letters_report.json`, `application_bundles.json` |

`main.py` runs all six in dependency order, stops downstream work if a step
fails, and forwards generation options (`--limit`, `--jobs`, `--force`,
`--no-tailor`, `--no-domain-filter`, `--loose-filter`). Use `--force-letters`
to regenerate letters already verified in a previous run. Each step can also
be invoked directly.

## Engine (steps 4-6)

Everything lives in `resume_content_improve_research/`:

```text
config.py                 all paths, tokens, thresholds in one place
generation/
  domain_filter.py        two-stage domain gate (family keywords + 60% skill alignment)
  scored_filter.py        the 60% skill-alignment scoring engine
  analyst.py              LLM JD analyst over the WHOLE ad (+ JSON repair)
  analyst_postcheck.py    deterministic fixes: languages, tools, posting language
  keywords.py             per-job keyword plan: analyst terms + full-ad lexicon sweep
  evidence_vocab.py       which job keywords truthfully describe each real KB entry
  keyword_injector.py     every keyword into category skill rows; gap phrases removed
  claimable_set.py        printable universe = KB skills ∪ JD tools ∪ job keywords
  generator.py            profile / bullets / projects in job-ad vocabulary
  tailoring.py            per-job tailoring + keyword placement
  factual_content.py      grounding: KB facts, per-entry vocabulary check, fallbacks
  cover_letter.py         LLM letter body + deterministic logistics paragraph
  llm.py                  Ollama Cloud client (serial, backoff)
  kb_loader.py            candidate KB + ESCO skills + alias map
knowledge_base/           candidate_kb.json, tech_lexicon.json, evidence_synonyms.json,
                          alias_map.json, domain_filters.json, ESCO
templates/                v3 template + render.py (one document model -> PDF and DOCX)
verification/             parse-back, G1/G2/G3 + keyword gate, letter gates L1-L4,
                          scorecard, triage (fit tiers), prep sheets
run_step4.py / run_step5.py / run_step6.py
```

Policy (plan v3, 2026-10-17; details in `RESUME_ATS_REVIEW.md`):

- **Every job-ad keyword is printed**: all of them in the Technical Skills rows
  (job-ad spelling, acronym pairs like "Machine Learning (ML)"); in experience
  and project bullets only where the KB evidence supports them
  (`knowledge_base/evidence_synonyms.json`).
- **Verifiable facts stay KB-only**: employers, job titles held, dates, degrees,
  certificates and numbers; no invented accomplishments at real employers; G2
  still rejects technology the job never mentioned.
- **Never ship a broken artifact**: pre-build gates (G2/G3) with a regenerate
  loop; post-build G1/G3 on the parsed-back PDF (<= 2 pages); the **keyword gate**
  requires every job keyword in the parsed PDF *and* the DOCX. Failures are moved
  to `output_v2/failed/` instead of shipped.
- **Real-fit ranking**: `kb_backed_share` (share of the job's technical keywords
  the KB backs) ranks `shortlist.json` (strong >= 0.6, good >= 0.4, stretch);
  the rest become `prep_terms` in the interview-prep sheet.
- **Cover letters**: the LLM writes opening / fit / motivation from the ad's
  tasks and real evidence; the last paragraph (enrolment, hours, permit) is
  deterministic; L1-L4 gates incl. a biography check; one repair round, then a
  KB-grounded fallback letter.

## Domain gate

The gate runs before any LLM call. Stage 1 keeps any job with a signal in the
target families: software, AI/data, automation, computer
hardware/IoT/robotics, finance (banking/trading/investment), and business+tech.
Stage 2 scores the remaining jobs: >= 60% of the job's detectable demands must
be covered by the candidate's KB skills (plus degree match and a capped
tech-employer industry bonus). Jobs below the bar are eliminated with a reason
in `output_v2/domain_filter_report.json`. Thresholds are tunable in
`resume_content_improve_research/knowledge_base/domain_filters.json`.

## Outputs

```text
program_files/output/          jobs CSVs (steps 1-2) + dashboard state
program_files/output_v2/
  components_v2.json           step-4 store (status per job: gated_ok / parked)
  resume_report.json           step-5 report (gates, keyword gate, kb_backed_share, prep_terms)
  shortlist.json               ranking by real fit (strong/good/stretch) + prep terms
  resume/{pdf,docx,tex}/       Meetkumar_Raval_CV_<Company>_<Role>.{pdf,docx,tex}
  prep/                        <Company>_<Role>.md prep sheets + learning_priorities.{md,json}
  letters/{pdf,docx,tex,textfield}/ Meetkumar_Raval_{Cover_Letter|Anschreiben}_<Company>_<Role>
  letters_report.json          step-6 letter gates and results
  application_bundles.json     portal-specific upload manifest
  failed/                      quarantined artifacts (never shipped)
  domain_filter_report.json    why each eliminated job was cut
```

## Setup

```bash
python -m pip install -r requirements.txt
```

- Ollama keys go into `sub_program_files/ollama_keys.json` (gitignored); step 3
  writes the working subset to `sub_program_files/active_ollama_keys.json`.
- PDF compilation prefers the bundled `tools/tectonic.exe`, then `tectonic` /
  `pdflatex` on PATH. Without an engine, DOCX builds still work but PDFs fail.
- Scraping needs Chrome/Chromium (Selenium).

## Tests

```bash
python -m pytest resume_content_improve_research/tests -q
```

## Project structure

- `app/`: shared Stepstone/workingstudentjobs.de scraper implementations and common configuration used by the current scraper wrappers.
- `program_files/`: pipeline stages 1-3, dashboard, and dated audit/recovery helpers.
- `resume_content_improve_research/`: current v2 generation, verification, resume/letter building, tests, and research notes.
- `sub_program_files/`: scraper wrappers, Ollama transport/key helpers, and legacy prompt-based resume-section code retained for reference.
- `tools/tectonic.exe`: bundled PDF compiler.
- `REPO_GUIDE.md`: expanded architecture, data contracts, dependencies, test notes, and cleanup history.

The older standalone `old_files/` archive has been removed. Candidate facts for the active engine live in `resume_content_improve_research/knowledge_base/candidate_kb.json`.

## Tests

```bash
python -m pytest resume_content_improve_research/tests -q
python resume_content_improve_research/knowledge_base/validate_kb.py
```

The test suite must not depend on a previous generated `program_files/output_v2/` run; keep fixtures temporary and deterministic.
