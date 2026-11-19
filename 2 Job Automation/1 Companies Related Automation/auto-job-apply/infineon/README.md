# Infineon Job Automation (Eightfold portal)

Self-contained pipeline, identical in method to the `mercedes/` folder twin: fetch Infineon Werkstudent jobs from jobs.infineon.com (Eightfold API), filter English-friendly ones, generate an LLM-tailored resume per job (Ollama `gpt-oss:120b`), build PDF+DOCX, and apply through the Eightfold application form with each job's own resume.

## Pipeline

| Step | Script | What it does |
|---|---|---|
| 1 | `1_INFINEON_Jobs_fetching.py` | Pages the Eightfold search API (`start=0,10,20,...` until empty), then enriches every job via the official `position_details` API (full description, raw payload, dates, locations). |
| 2 | `2_INFINEON_language_filter.py` | Rule-based DE/EN classifier (requirement-strength proximity, negation-aware, CEFR levels). Adds `Language_Filter` + evidence. |
| 3 | `3_INFINEON_ollama_keys.py` | Tests Ollama keys, keeps working ones in `sub_program_files/active_ollama_keys.json`. |
| 4 | `4_INFINEON_create_resumes.py` | Recency + language filter, maps Eightfold data onto the resume-generator schema, runs the 4 LLM stages (objective/experience/projects/skills). **Resumable** — finished jobs are never re-paid. |
| 5 | `5_INFINEON_final_resume.py` | Fills the LaTeX template, compiles PDFs via bundled `tools/tectonic.exe`, mirrors DOCX, writes `job_resume_map.csv` (`job_url -> resume_pdf`). |
| — | `generate_resume_page.py` | `resumes.html` index of all built resumes (verified links). |
| Apply | `infineon_job_apply.py` | Playwright automation of the Infineon application form. Auto-picks each job's tailored resume from the map. |
| Repair | `recover_flagged_experience.py` / `recover_flagged_skills.py` | Regenerates only flagged/missing LLM records, merge-safe. |
| Runner | `main.py` | fetch → keys → components → resumes in one command. |

## Usage

```bash
python main.py                                # whole pipeline (fetch -> resumes)
python 4_INFINEON_create_resumes.py --limit 3 # test slice
python 4_INFINEON_create_resumes.py --window-days 14   # full batch (long)
python recover_flagged_experience.py          # only if flagged
python recover_flagged_skills.py              # only if flagged
python 5_INFINEON_final_resume.py             # rebuild PDFs/DOCX + map
python generate_resume_page.py                # refresh resumes.html

# Apply (auto-picks the tailored resume from job_resume_map.csv):
python infineon_job_apply.py --url "https://jobs.infineon.com/careers/apply?pid=<ID>" --dry-run
python infineon_job_apply.py --url "https://jobs.infineon.com/careers/apply?pid=<ID>" --submit   # asks YES
```

## Apply automation notes (verified live)

- OneTrust cookie banner dismissed first (its overlay blocks every click).
- Resume upload → confirm dialog (`#confirmUploadResume`) → parsing wait (done when the email autofills) → never overwrite autofilled contact fields.
- All selects are custom comboboxes matched via `aria-labelledby` labels with **exact-option** selection + read-back verification (substring matching provably picks the wrong option, e.g. "Male" → "Female").
- Single-location jobs are preselected by the site in React state — left unchanged (spec: never invent preferences).
- Disability field options are exactly `['No selection', 'Disabled']`; the script treats "No selection" as the no-answer state and refuses "Disabled".
- Statuses: `SUCCESS | DRY_RUN | FAILED | BLOCKED | NEEDS_ATTENTION`; screenshots in `results/`.

## Structure

```
infineon/
├── 1_INFINEON_Jobs_fetching.py      # fetch + enrich (Eightfold APIs)
├── 2_INFINEON_language_filter.py    # EN/DE classifier
├── 3_INFINEON_ollama_keys.py        # key tester wrapper
├── 4_INFINEON_create_resumes.py     # filter + bridge + 4 LLM stages
├── 5_INFINEON_final_resume.py       # PDF/DOCX + job_resume_map.csv
├── infineon_job_apply.py            # Playwright apply automation
├── main.py / generate_resume_page.py / recover_flagged_*.py
├── program_files/output_infineon/   # all artifacts (components, resumes, map)
├── sub_program_files/               # bundled LLM stages, prompts, keys
├── tools/tectonic.exe               # bundled LaTeX engine
└── config/candidate.json            # candidate data
```
