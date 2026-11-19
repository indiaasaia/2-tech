# JOB_AUTOMATION

Standalone three-phase job-application preparation pipeline. It does not import from `OLD_PROJECT` or `OLD_FILES`.

## Structure

```text
JOB_AUTOMATION/
├── app/
│   ├── core/       # configuration, date filtering, Ollama client
│   ├── phase1/     # Stepstone, workingstudentjobs.de, CSV combining
│   ├── phase2/     # tailored resume generation
│   └── phase3/     # cover letters and application manifest
├── data/
│   ├── candidate_profile.json
│   ├── output/     # jobs.csv and reports
│   ├── phase2/     # components and resumes
│   └── phase3/     # cover letters
├── tests/
├── run_phase1.py
├── run_phase2.py
└── run_phase3.py
```

## Install

```bash
python -m pip install -r requirements.txt
```

Stepstone requires Chrome/Chromium. Selenium Manager can obtain a compatible driver when network access allows it.

PDF compilation needs a LaTeX engine. The pipeline prefers, in order: `JOB_AUTOMATION_TECTONIC` (env var), `tools/tectonic.exe` inside this repo, `OLD_FILES/tectonic.exe`, then `tectonic`/`pdflatex` on PATH. The self-contained `tectonic.exe` (Windows) can be placed in `tools/`:

```bash
mkdir -p tools
curl -L -o tools/tectonic.zip https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.17.0/tectonic-0.17.0-x86_64-pc-windows-msvc.zip
cd tools && unzip -o tectonic.zip && rm tectonic.zip && cd ..
```

## Workflow

Phase 1 fetches both sources, fetches details, filters strictly to postings from the last 48 hours, deduplicates, and writes `data/output/jobs.csv`:

```bash
python run_phase1.py --source both
```

Useful Phase 1 options:

```bash
python run_phase1.py --source stepstone --stepstone-pages 1
python run_phase1.py --source workingstudent --workingstudent-pages 1
python run_phase1.py --source both --stepstone-pages 1 --workingstudent-pages 1 --no-details
python run_phase1.py --headed
```

Phase 2 reads `jobs.csv` and creates truthful, job-tailored resumes. Ollama is used by default, with a deterministic fallback:

```bash
python run_phase2.py --limit 5
python run_phase2.py --limit 5 --no-llm
```

Phase 3 creates tailored cover letters and a review manifest:

```bash
python run_phase3.py --limit 5
python run_phase3.py --limit 5 --no-llm
```

No application is submitted automatically. Every output is marked for review.

## Unified CLI

`run.py` wraps all three phases plus tracking into one interface:

```bash
python run.py fetch                          # Phase 1: scrape listings
python run.py resumes --limit 5              # Phase 2: tailored resumes
python run.py letters --limit 5              # Phase 3: cover letters + manifest
python run.py all --sample                   # End-to-end offline demo (no live scraping)
python run.py all                            # End-to-end: live fetch, then per-job resumes + letters
python run.py demo                           # Write a sample jobs.csv for offline runs
python run.py status                         # Show tracked activity + latest run reports
```

Every step (page fetched, job filtered, resume/cover generated, PDF compiled) is written to `data/output/activity.log` with a timestamp, phase, step, and status. `python run.py status` summarizes those events and the latest reports, and `python run.py all --sample` runs the complete pipeline offline so nothing depends on external websites.

Use `--no-llm` for deterministic local generation (or when no Ollama endpoint/API key is configured) and `--no-pdf` to skip PDF compilation. Live scraping still requires network access, Chrome/Chromium, and the target sites being reachable.

## Recommended sequential workflow

The system uses two logical stages:

1. Phase 1 fetches all listings, fetches their details, applies the 48-hour filter, removes duplicates, and finalizes `data/output/jobs.csv`.
2. The sequential workflow then takes one finalized row at a time. It completes that job's Phase 2 resume components and resume PDF, then completes its Phase 3 cover letter and cover-letter PDF, records the result, and only then moves to the next job.

Run the complete per-job workflow:

```bash
python run_phase1.py --source both
python run_all_sequential.py
```

For the first five jobs:

```bash
python run_phase1.py --source both --stepstone-pages 1 --workingstudent-pages 1
python run_all_sequential.py --limit 5
```

Use `--no-llm` for deterministic local generation or `--no-pdf` for a fast document-source smoke test. A job is marked `ready_for_review` only when both its resume PDF and cover-letter PDF are successfully produced; otherwise it is marked `needs_attention` and the next job still continues.

## Outputs

```text
data/output/jobs.csv
data/output/stepstone_jobs.csv
data/output/workingstudent_jobs.csv
data/output/phase1_report.json
data/phase2/components/*.json
data/phase2/resumes/tex/*.tex
data/phase2/resumes/pdf/*.pdf
data/phase2/phase2_report.json
data/phase3/cover_letters/*.md
data/phase3/cover_letters/tex/*.tex
data/phase3/cover_letters/pdf/*.pdf
data/output/applications.csv
data/phase3/phase3_report.json
```

Ollama settings are read from `JOB_AUTOMATION_OLLAMA_HOST`, `JOB_AUTOMATION_OLLAMA_MODEL`, and `OLLAMA_API_KEY`. For local development, the client may also read the existing archived key file, but secrets are never copied into source code.

## Verification

```bash
python -m pytest -q
python -m compileall -q .
python run_phase1.py --help
python run_phase2.py --help
python run_phase3.py --help
```

Live scraping still depends on website availability, anti-bot behavior, current selectors, network access, and a functioning browser. The pipeline records source errors rather than silently treating failures as successful data.
