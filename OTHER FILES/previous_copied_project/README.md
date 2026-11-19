# Job -> Verified Resume Pipeline

Scrapes fresh working-student jobs in Germany, filters out-of-domain postings,
then generates **one KB-grounded, gate-verified ATS resume per job** (PDF + DOCX)
with a fit score and an apply-first shortlist.

```text
python main.py                 # full pipeline: steps 1-5, end to end
python main.py --limit 3       # first run: try 3 jobs before spending the full budget
python run_dashboard.py        # Streamlit dashboard (scanner, resumes, tracker)
```

## Pipeline

| Step | Script | What it does | Output |
|------|--------|--------------|--------|
| 1 | `program_files/1_fetch_jobs.py` | Scrape Stepstone + workingstudentjobs.de | `program_files/output/todays_overall_jobs.csv` |
| 2 | `program_files/2_filter_jobs.py` | Keep postings from yesterday or today | `program_files/output/2_filted_jobs.csv` |
| 3 | `program_files/3_test_ollama_keys.py` | Test Ollama keys, keep the working ones | `sub_program_files/active_ollama_keys.json` |
| 4 | `resume_content_improve_research/run_step4.py` | Domain gate -> JD analyst -> claimable set -> constrained generation -> gates | `program_files/output_v2/components_v2.json` |
| 5 | `resume_content_improve_research/run_step5.py` | Fill template -> compile PDF + DOCX -> parse back -> gates -> scorecard -> triage | `program_files/output_v2/resume_report.json`, `shortlist.json` |

Each step also runs standalone; `main.py` only orchestrates and forwards
step-4 flags (`--limit`, `--jobs`, `--force`, `--no-tailor`,
`--no-domain-filter`, `--loose-filter`).

## Engine (steps 4-5)

Everything lives in `resume_content_improve_research/`:

```text
config.py                 all paths, tokens, thresholds in one place
generation/
  domain_filter.py        two-stage domain gate (family keywords + 60% skill alignment)
  scored_filter.py        the 60% skill-alignment scoring engine
  analyst.py              LLM JD analyst (+ JSON repair)
  claimable_set.py        what the candidate is licensed to claim (KB ∪ mirrorable JD tools)
  generator.py            constrained generation (KB-only skills, real projects only)
  tailoring.py            per-job tailoring pass over the generated components
  llm.py                  Ollama Cloud client (serial, backoff)
  kb_loader.py            candidate KB + ESCO skills + alias map
knowledge_base/           candidate_kb.json, alias_map.json, domain_filters.json, ESCO
templates/                @@TOKEN@@ template (collision-proof), tex/docx builders
verification/             parse-back simulation, G1/G2/G3 gates, coverage, scorecard, triage
run_step4.py / run_step5.py
```

Key guarantees (see `resume_content_improve_research/FINAL_MODEL.md`):

- **No fabrication**: skills come only from the candidate KB (plus mirrorable
  JD tools); projects are the two real projects re-angled per job; the only
  allowed numbers are the licensed ones.
- **Never ship a broken artifact**: pre-build gates (G2/G3) with a regenerate
  loop, then post-build gates (G1/G3) on the *parsed-back PDF*; failures are
  moved to `output_v2/failed/` instead of shipped.
- **Honest scoring**: coverage over the extracted PDF text drives the 0-100
  fit score and the tier ranking in `shortlist.json`.

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
  resume_report.json           step-5 verification report (score, coverage, gates)
  shortlist.json               apply-first ranking (strong/good/weak/poor)
  resume/pdf|docx|tex          verified artifacts
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

## Archived code

`old_files/` contains earlier generations kept for reference (not part of the
pipeline): the standalone three-phase prototype, the v1 prompt-per-section
resume pipeline (`old_files/v1_resume_pipeline/`), and its generated outputs.
