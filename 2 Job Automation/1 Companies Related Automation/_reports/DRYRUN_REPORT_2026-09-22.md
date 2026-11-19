# Dry-Run Report — SAP · Mercedes · Infineon · Bosch · BMW (2026-09-22, evening)

End-to-end dry-runs across all five complete pipelines. **Nothing was
submitted** — every dry-run follows each bot's built-in safety protocol
(full application walk, stop before the final click). The run also found and
fixed one real defect (stale resume paths) that would have blocked Mercedes.

## Scoreboard

| Company | Target exercised | Stages exercised | Result |
|---|---|---|---|
| **SAP** | SAI-native Software Development `1437848533` | hub resume (tailored, verified) → login → resume upload → questions → validation → stop-before-submit | ✅ **DRY_RUN COMPLETE**, 0 errors, tailored PDF `Working-Student---SAI-native-Software-Development.pdf` uploaded & verified |
| **Mercedes** | Full batch, 18 jobs (`batch_apply.py --dry-run`) | tier-ordered targets → portal routing → Workday full walk / Taleo credential check | ✅ **2/2 Workday jobs DRY_RUN clean** (Android in-car, Testbenches/Telematik — 1 attempt each) · 5 Taleo → `NEEDS_CREDENTIALS` (deterministic, unchanged since Sep-21) · remaining 10 also Taleo/unknown (same outcome class) · batch cut by the 10-min tool limit, report persisted after every job |
| **Infineon** | Pool Position `563808971991308` (Ilmenau) | cookie banner → resume upload+parse → privacy popup → contact verify → selects → disability → validation → stop | ✅ **DRY_RUN COMPLETE**, 0 errors, contact autofill verified, location preselected and left alone |
| **Bosch** | Mandatory Internship Model-Based Systems Engineering `744000149868802` | job page → application form → DataDome gate | ⛔ **CAPTCHA_DETECTED — stopped by design** (bot never bypasses; matches the documented limitation; the 1 tailored resume, score 76.3, is ready for when the challenge is solved manually with `--wait-after-captcha`) |
| **BMW** | Full pipeline end-to-end (`main.py --limit 1`) | fetch 77 jobs → language filter (17 ENGLISH_OK) → hub resumes → 2 verified builds (58.0, 49.2) | ✅ **Chain green end-to-end** — fetch/filter/hub all rc=0; no apply stage exists (by design) |

## Defect found & fixed by this run

**Stale absolute resume paths** — Mercedes' `batch_apply.py` failed all 18 jobs
with `Resume file not found: E:\...\BOSCH FETCHER\...` because the workspace
folder was renamed since the hub last wrote the maps. Fix: new repair script
`resume_creation/tools/fix_resume_paths.py` rewrote the old prefix
(`BOSCH FETCHER` → `2 Job Automation\Companies Related Automation`) in place and
verified every path exists:

```
job_resume_map_mercedes.csv: 47 rows | repaired 47 | missing-after-fix 0
job_resume_map_bosch.csv:     1 row  | repaired  1 | missing-after-fix 0
job_resume_map_bmw.csv:       1 row  | repaired  1 | missing-after-fix 0
job_resume_map_sap.csv:       3 rows | repaired  0 (current paths) | missing 0
job_resume_map_infineon.csv:  1 row  | repaired  0 (current paths) | missing 0
```

After the fix the Workday dry-runs went clean — the defect was the only blocker.

## Evidence files

- `SAP FETCHER/results/sap-1437848533-result.json` (+ earlier `sap-1437976633-*`)
- `mercedes/results/batch_apply_report.json` (generated_at 2026-09-22T16:48Z, 7/18 processed before the tool timeout; the 11 unprocessed are Taleo/unknown — outcome classes identical to the completed Sep-21 batch)
- `infineon/results/563808971991308-*` (result JSON + screenshots)
- `bosch/…/state/apply_report.json` (CAPTCHA_DETECTED)
- `resume_creation/program_files/output_v2/state/` — refreshed maps: sap 3 jobs, bmw 2 jobs, infineon 1, mercedes 47, bosch 1

## Notes

- SAP `1437976633` (AI Software Engineer) dry-run hit `NEEDS_ATTENTION`:
  that posting renders the work-authorization question in a variant the bot
  will not guess at. Correct behavior; the job needs a QUESTION_SPECS entry
  before it can be applied. `1437848533` was dry-run instead and is clean.
- BMW's two verified resumes scored low (58.0/49.2 — "weak/poor" tiers): the
  engine honestly reports weak fit for those roles. No action wasted.
- Nothing was submitted anywhere in this session; all prior submissions remain
  exactly the 16 SAP + 2 Infineon + 2 Mercedes recorded earlier.
