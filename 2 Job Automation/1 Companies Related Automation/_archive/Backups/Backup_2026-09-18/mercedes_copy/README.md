# Mercedes-Benz Tech Innovation — Automated Job Applications (Workday)

One-file Playwright automation (`mercedes_job_apply.py`) that applies to jobs on the
Mercedes-Benz Tech Innovation candidate portal (`mercedesbenztechinnovation.wd3.myworkdayjobs.com`,
Workday platform). **Status: production-tested end-to-end on 2026-09-15** — a real
application (requisition R0006909) was submitted successfully with full server-side
verification (finalize endpoint HTTP 200 + confirmation message + submit button gone).

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

## Files

```
mercedes/
├── mercedes_job_apply.py        ← THE automation (single file, importable + CLI)
├── config/
│   └── candidate.json           ← YOUR personal data (overrides script defaults)
├── docs/
│   └── WORKDAY_DOM_FINDINGS.md  ← all verified DOM/selector research (read before extending!)
├── results/                     ← per-run screenshots + result JSON (audit trail)
│   └── R0006909-*.png, mercedes-R0006909-result.json
├── MERCEDES_Jobs_fetching.py    ← existing job-fetcher (unchanged, separate concern)
├── MERCEDES_jobs_detailed.csv   ← existing job listings
├── MERCEDES_jobs_full.json      ← existing job listings
└── MERCEDES_results.csv         ← existing fetcher output
```

## Quick start

```bash
cd "E:\WorkSpace\2 Tech\BOSCH FETCHER\mercedes"

# 1) Put your current personal data in config/candidate.json (see that file)

# 2) Dry-run (browser opens, walks everything, does NOT submit):
python mercedes_job_apply.py --dry-run

# 3) Real submission (asks you to type YES):
python mercedes_job_apply.py --submit

# Variants:
python mercedes_job_apply.py --url "<JOB_URL>" --resume "<RESUME.pdf>" --dry-run
python mercedes_job_apply.py --submit --headless          # unattended, no window
```

Exit codes / printed final status: `SUCCESS`, `DRY_RUN`, `NEEDS_ATTENTION`, `FAILED`,
`BLOCKED`. A run only prints `SUCCESS` when the Workday finalize endpoint returned
HTTP 200 AND a confirmation message was found AND the submit button disappeared —
a click alone is never trusted.

## Programmatic use (for future batch systems)

```python
from pathlib import Path
from mercedes_job_apply import apply_to_mercedes_job

result = apply_to_mercedes_job(
    job_url="https://mercedesbenztechinnovation.wd3.myworkdayjobs.com/en-US/MBTI_JOBPORTAL/job/..._R0006xxx",
    resume_path=Path("path/to/resume.pdf"),
    dry_run=True,    # 1. always dry-run first
    headless=False,
)
print(result["status"])          # DRY_RUN / SUCCESS / NEEDS_ATTENTION / FAILED / BLOCKED
print(result["stagesReached"])   # which of the 9 flow stages completed
print(result["fields"])          # everything that was changed/verified, with values
```

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
  MBTI job URL + resume path; the script resolves the requisition id itself.
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
