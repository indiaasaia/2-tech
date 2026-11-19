# Mercedes-Benz Tech Innovation — Automated Job Applications (Workday)

Full 3-step pipeline: fetch all Mercedes Werkstudent jobs → generate one tailored
resume per job (Ollama LLM + LaTeX) → apply with Playwright using each job's own resume.

---

## What works today

| Stage | Status |
|---|---|
| Portal entry + job resolution from the search list (deep `/details/` links 404!) | ✅ verified |
| Start-Your-Application dialog → **Autofill with Resume** (never the other options) | ✅ verified |
| Resume upload with "Successfully Uploaded!" state verification | ✅ verified |
| My Information: autofill-aware filling, name correction, address, source picker, phone format fix | ✅ verified |
| My Experience: document verification, no touching of existing content | ✅ verified |
| Application Questions: date spinbuttons, disability, work permit, data transfer | ✅ verified |
| Voluntary Disclosures: DOB, gender, nationality, pronoun, terms checkbox | ✅ verified |
| Review page ground-truth verification before anything happens | ✅ verified |
| Dry-run: full walk, stops before Submit, prints `DRY_RUN_COMPLETE` | ✅ verified |
| Real submission with strong-evidence SUCCESS check | ✅ verified |
| CAPTCHA / MFA / human-verification detection → BLOCKED, no bypass attempts | ✅ built in |

## The pipeline (aligned with `E:\WorkSpace\2 Tech\SAP FETCHER`)

This folder is **fully self-contained** — it bundles its own resume stages,
prompts, LLM helper, Ollama keys, LaTeX template and tectonic.exe, so it runs
from anywhere with no outside project needed. Keep the folder structure intact.

```
1_MERCEDES_Jobs_fetching.py    STEP 1   fetch ALL Mercedes Werkstudent jobs (API, ~2 min)
                                        -> MERCEDES_results.csv / _detailed.csv / _full.json

2_MERCEDES_language_filter.py  STEP 2a  rule-based language filter
                                        -> Language_Filter column (ENGLISH_OK / GERMAN_REQUIRED / UNSURE)
2_MERCEDES_create_resumes.py   STEP 2b  keep ENGLISH_OK + recent jobs, generate the 4
                                        LLM component stores per job
                                        -> program_files/output_mercedes/*.json
3_MERCEDES_ollama_keys.py      STEP 3a  test Ollama keys -> active_ollama_keys.json
3_MERCEDES_final_resume.py     STEP 3b  build ONE TAILORED RESUME PER JOB (PDF + DOCX)
                                        -> program_files/output_mercedes/resume/{pdf,docx}
                                        -> job_resume_map.csv (job_url -> resume PDF)
4_MERCEDES_job_apply.py        STEP 4   apply to ONE job on the Workday portal, auto-using
                                        that job's tailored resume (or --resume to override)

main.py                        runs steps 1 -> 2 -> 3a -> 3b in order
recover_flagged_skills.py      regenerates flagged/missing skills records (merge-safe)
generate_resume_page.py        -> resumes.html: visual index of all built resumes
```

### Run everything

```bash
python main.py          # fetch -> components -> keys -> resumes (one command)
```

Or step by step:

```bash
python 1_MERCEDES_Jobs_fetching.py
python 2_MERCEDES_create_resumes.py --window-days 14      # --limit N for a test run
python 3_MERCEDES_final_resume.py
python generate_resume_page.py                            # resumes.html preview
python recover_flagged_skills.py                          # only when skills are flagged
```

### Step 4 — apply

```bash
# dry-run (browser opens, walks everything, does NOT submit):
python 4_MERCEDES_job_apply.py --url "<JOB_URL>" --dry-run

# real submission (asks you to type YES) - picks the tailored resume automatically:
python 4_MERCEDES_job_apply.py --url "<JOB_URL>" --submit

# explicit resume always wins over the auto-pick:
python 4_MERCEDES_job_apply.py --url "<JOB_URL>" --resume "path/to/resume.pdf" --submit
python 4_MERCEDES_job_apply.py --submit --headless        # unattended, no window
```

Resume resolution order: explicit `--resume` > tailored PDF for the job URL from
`program_files/output_mercedes/job_resume_map.csv` > configured fallback in
`config/candidate.json`.

Exit codes / printed final status: `SUCCESS`, `DRY_RUN`, `NEEDS_ATTENTION`, `FAILED`,
`BLOCKED`. A run only prints `SUCCESS` when the Workday finalize endpoint returned
HTTP 200 AND a confirmation message was found AND the submit button disappeared —
a click alone is never trusted.

## What works today

| Stage | Status |
|---|---|
| Step 1 fetch: 205 jobs, 0 failures (2026-09-17) | ✅ verified |
| Step 2a language filter: 163 ENGLISH_OK / 42 GERMAN_REQUIRED | ✅ verified |
| Step 2b component stages + Step 3b resumes (self-contained) | ✅ verified (test run) |
| Step 4 tailored-resume auto-pick + fallback | ✅ verified |
| main.py runner, resumes.html index, flagged-skills recovery | ✅ verified |
| Portal entry + job resolution from the search list (deep `/details/` links 404!) | ✅ verified |
| Start-Your-Application dialog → **Autofill with Resume** (never the other options) | ✅ verified |
| Resume upload with "Successfully Uploaded!" state verification | ✅ verified |
| My Information: autofill-aware filling, name correction, address, source picker, phone format fix | ✅ verified |
| My Experience: document verification, no touching of existing content | ✅ verified |
| Application Questions: date spinbuttons, disability, work permit, data transfer | ✅ verified |
| Voluntary Disclosures: DOB, gender, nationality, pronoun, terms checkbox | ✅ verified |
| Review page ground-truth verification before anything happens | ✅ verified |
| Dry-run: full walk, stops before Submit, prints `DRY_RUN_COMPLETE` | ✅ verified |
| Real submission with strong-evidence SUCCESS check | ✅ verified |
| CAPTCHA / MFA / human-verification detection → BLOCKED, no bypass attempts | ✅ built in |

## Files

```
mercedes/
├── 1_MERCEDES_Jobs_fetching.py      ← STEP 1: job fetcher (API search -> CSV/JSON)
├── 2_MERCEDES_language_filter.py    ← STEP 2a: rule-based EN/DE language filter
├── 2_MERCEDES_create_resumes.py     ← STEP 2b: schema bridge + 4 LLM component stages
├── 3_MERCEDES_ollama_keys.py        ← STEP 3a: key tester wrapper
├── 3_MERCEDES_final_resume.py       ← STEP 3b: LaTeX/DOCX assembly + job_resume_map.csv
├── 4_MERCEDES_job_apply.py          ← STEP 4: the Workday automation (importable + CLI)
├── main.py                          ← runs steps 1 → 2 → 3a → 3b in order
├── recover_flagged_skills.py        ← regenerates flagged skills records (merge-safe)
├── generate_resume_page.py          ← writes resumes.html (visual resume index)
├── resumes.html                     ← the generated index (open in a browser)
├── program_files/
│   ├── 3_test_ollama_keys.py        ← bundled key tester
│   ├── 5_create_resume.py           ← bundled resume assembler (LaTeX + DOCX)
│   └── output_mercedes/             ← ALL pipeline output lives here:
│       ├── 2_filted_jobs.csv / todays_overall_jobs.csv   (filtered master lists)
│       ├── career_objective.json / experience.json / projects.json / skills.json
│       ├── resume/{tex,pdf,docx}/                         (the tailored resumes)
│       ├── resume_report.json / job_resume_map.csv
├── sub_program_files/
│   ├── ollama_request_response.py   ← LLM helper (send_prompt, load_first_key)
│   ├── ollama_keys.json / active_ollama_keys.json
│   ├── prompt/                      ← the 6 LLM prompt templates
│   └── resume_content/              ← 4 stage modules + core_resume_template.tex
├── tools/tectonic.exe               ← bundled LaTeX engine
├── config/
│   └── candidate.json               ← YOUR personal data (overrides script defaults)
├── docs/
│   └── WORKDAY_DOM_FINDINGS.md      ← all verified DOM/selector research (read before extending!)
├── results/                         ← per-run screenshots + result JSON (audit trail)
├── MERCEDES_jobs_detailed.csv       ← STEP 1 output (flat columns + Language_Filter)
├── MERCEDES_jobs_full.json          ← STEP 1 output (everything)
└── MERCEDES_results.csv             ← STEP 1 output (title + link)
```

## Programmatic use (for future batch systems)

```python
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "mercedes_apply", Path(__file__).parent / "4_MERCEDES_job_apply.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

result = module.apply_to_mercedes_job(
    job_url="https://mercedesbenztechinnovation.wd3.myworkdayjobs.com/en-US/MBTI_JOBPORTAL/job/..._R0006xxx",
    resume_path=Path("path/to/resume.pdf"),
    dry_run=True,    # 1. always dry-run first
    headless=False,
)
print(result["status"])          # DRY_RUN / SUCCESS / NEEDS_ATTENTION / FAILED / BLOCKED
print(result["stagesReached"])   # which of the 9 flow stages completed
print(result["fields"])          # everything that was changed/verified, with values
```

(The file name no longer matches the module name, so load it by path as above.)

Batch loop (when you connect many jobs — do dry-runs first, review, then submit):

```python
jobs = [{"url": "...", "resume": "..."}, ...]
for job in jobs:
    outcome = apply_to_mercedes_job(job["url"], Path(job["resume"]), dry_run=True)
    # collect statuses, review NEEDS_ATTENTION cases manually, then submit the good ones
```

## What each run produces

In `results/`:

- `R<requisition>-01-job-page.png` … `R<requisition>-08-review-before-submit.png`
- `R<requisition>-09-after-submit.png` (after a real submission)
- `R<requisition>-error-<status>.png` (on any failure)
- `mercedes-R<requisition>-result.json` — the full audit record: stages reached,
  every field changed/verified with values, success indicators incl. the finalize
  HTTP status, screenshots list, timestamps, duration.

## Personal data & credentials

- All personal answers live in `config/candidate.json`. The script never hardcodes
  personal data beyond the fallback defaults, and never prints or screenshots
  passwords (none are needed — the MBTI portal flow requires no login).
- No login is required for guest applications on this tenant; if a future flow
  needs credentials, read them from environment variables (e.g. `MB_EMAIL`,
  `MB_PASSWORD`) — never from source or config committed to a repo.

## Safety rules baked into the script

1. Never invents data — every answer comes from `config/candidate.json` or the
   resume autofill; unknown required fields stop the run (`NEEDS_ATTENTION`).
2. Never bypasses CAPTCHA/MFA — detection stops with `BLOCKED`.
3. Never trusts an unverified click — every picker selection, date, and checkbox
   is read back from the DOM before continuing.
4. Escape key is never used to close an open picker (Workday reverts uncommitted
   selections on Escape — verified live; Tab or click-away is used instead).
5. Dry-run physically cannot submit: Submit is only reachable in `--submit` mode
   behind a typed `YES` confirmation, and only after full Review verification.

## Extending to many jobs / other portals

- **More Mercedes jobs:** nothing in the flow is requisition-specific. Pass any
  MBTI job URL; the script resolves the requisition id itself and auto-picks the
  job's tailored resume when step 2 has built one.
  Read `docs/WORKDAY_DOM_FINDINGS.md` first — it lists the behaviors that vary
  (question sets differ per requisition; the script maps fields by label keywords
  and hard-fails on ambiguity, which is exactly what you want for new jobs).
- **Other companies (BMW, Bosch, Siemens…):** the architecture is portal-agnostic:
  the same result-dict/screenshot/verification pattern from the SAP reference
  (`../SAP FETCHER/sap_job_apply.py`) is reimplemented here with Workday-specific
  primitives. Copy the file into each portal folder, replace the DOM primitives
  with that portal's verified selectors (do live probes first, as done here), and
  keep the same `apply_to_<portal>_job()` signature so a future orchestrator can
  call them uniformly.

See `docs/WORKDAY_DOM_FINDINGS.md` for the complete verified selector/behavior
reference — it is the distilled knowledge of this entire research session, so a
future session does not need to re-probe Workday from scratch.
