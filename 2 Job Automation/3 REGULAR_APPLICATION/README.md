# REGULAR_APPLICATION

One command fetches new working-student / internship jobs from the last N days,
keeps the relevant ones, and creates a tailored resume and cover letter for each.

```bash
pip install -r requirements.txt     # once
python run.py --days 1              # jobs from the last 24 hours (default)
python run.py --days 3              # jobs from the last 3 days
```

## What a run does

| Step | What happens | Output |
|---|---|---|
| 1 Fetch | Stepstone (opens a Chrome window) + workingstudentjobs.de, last N days | `output/jobs/fetched_jobs.csv` |
| 2 Filter | keeps jobs posted in the last N days, removes duplicates | `output/jobs/filtered_jobs.csv` |
| 3 Keys | tests your Ollama keys | `keys/active_ollama_keys.json` |
| 3b Screen | one `gpt-oss:120b` call per job: role type (working student / internship / senior / full-time ...), German requirement (CEFR level), country. Keeps student roles in Germany whose German demand is at most your level (A2, from your KB) | `output/jobs/screened_jobs.csv`, `screening_report.csv` (every job + reason) |
| 4 Analyze | AI/tech domain filter, job analysis, keyword plan, resume content, truth checks | `output/applications/components_v2.json` |
| 5 Resumes | PDF + DOCX (max 2 pages), every job keyword checked in both files | `output/applications/resume/` |
| 6 Letters | cover letter (PDF, DOCX, paste-ready TXT), fact-checked | `output/applications/letters/` |

At the end the run prints each job of this run with its resume and letter path.
Interview prep sheets (keywords on your resume that your KB does not back yet)
are in `output/applications/prep/`, with a cross-job list in
`prep/learning_priorities.md`.

Jobs from earlier runs are kept; a new run only builds documents for its own
jobs. A job that already has documents is skipped unless you pass `--force`
(resume) or `--force-letters` (letter).

## Options

| Option | Meaning |
|---|---|
| `--days N` | posting window in days (decimals allowed, e.g. `0.5`) |
| `--max-jobs N` | create documents for at most N new jobs (useful for a quick test) |
| `--skip-fetch` | do not scrape; reuse `output/jobs/fetched_jobs.csv` |
| `--pages N` | max listing pages per source/keyword (default: automatic, more pages for more days) |
| `--headless` | run Stepstone's Chrome without a window |
| `--force` / `--force-letters` | rebuild resumes / letters for jobs that already have them |
| `--no-domain-filter` | also process jobs outside the AI/tech filter |
| `--no-screen` | skip the LLM screening |
| `--include-thesis` | screening: also keep Bachelor/Master thesis positions |
| `--keep-abroad` | screening: also keep jobs outside Germany |

Each step also runs alone: `python steps/fetch_jobs.py --days 3`,
`python steps/filter_jobs.py --days 3`, `python steps/test_keys.py`, `python steps/screen_jobs.py`,
`python engine/run_step4.py`, `python engine/run_step5.py`, `python engine/run_step6.py`.

## Folder contents

```
run.py                      the one command
steps/                      fetch_jobs.py, filter_jobs.py, test_keys.py, screen_jobs.py
fetching/                   Stepstone + workingstudentjobs.de scrapers and their settings (config.py)
engine/                     resume + cover letter engine
  run_step4.py / 5 / 6      analyze + generate, build resumes, write letters
  generation/               analyst, keyword plan, LLM generation, truth checks, letters
  verification/             gates (ATS parse, keywords, claims), scorecard, prep sheets
  templates/                resume + letter LaTeX templates, PDF/DOCX builders
  knowledge_base/           candidate_kb.json = YOUR FACTS (the only source of truth), lexicon, ESCO skills
  config.py                 paths, limits, documents to attach
keys/ollama_keys.json       your Ollama API keys (not committed)
documents/                  enrolment certificate attached to bundles that ask for it
tools/tectonic.exe          PDF compiler (bundled)
output/                     everything generated (not committed)
```

## Things you may edit

- **Your facts:** `engine/knowledge_base/candidate_kb.json`. After editing, check it with
  `python engine/knowledge_base/validate_kb.py`. A skill you add with real evidence
  can then be used in bullets and letters, not only in the Skills section.
- **Keys:** `keys/ollama_keys.json` (`{"keys": ["..."]}`).
- **Search terms / pages:** `fetching/config.py` (`STEPSTONE_SEARCH_KEYWORDS`, `WSJ_SEARCH_TEMPLATE`).
- **Documents for bundles:** `engine/config.py` -> `APPLICATION_DOCUMENTS` (e.g. set your transcript).

## Screening rules (steps/screen_jobs.py)

The LLM only reads the ad and reports facts; `decide()` applies the rules, so you
can change them in one place:

- **Role:** keep `working_student`, `internship`, `student_assistant` (`thesis` with
  `--include-thesis`). A title with Senior/Lead/Principal/Head of overrules a student label.
- **German:** dropped only when German is *required* above your level. "Nice to have"
  never drops a job; "required" without a level counts as B2. Your level is read from
  `languages_spoken` in your KB, so updating it to B1 later changes the filter automatically.
- **Country:** jobs outside Germany are dropped (your permit is Germany-only).

Decisions are cached in `output/jobs/screening_cache.json`, so overlapping runs do
not pay twice. If the LLM fails for a job, title/text rules decide (marked `rule`
in the report).

## Requirements

Python 3.11+, Google Chrome (for Stepstone), an Ollama Cloud key (`gpt-oss:120b`).
LaTeX is not needed: `tools/tectonic.exe` builds the PDFs (first run downloads
its fonts once).

## Policy (how the documents are written)

Every job keyword is printed in the Skills section (100 % ATS coverage). Facts,
bullets, the profile and letter claims come only from your knowledge base: a
keyword you do not have evidence for appears only as a skill, never as work you
did. Read each letter once before sending.
