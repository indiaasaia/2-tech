# Current Status — All Folders (restructured 2026-09-20)

## The one structure, everywhere

Every company folder now has the **same numbered sequence**:

```
main.py  orchestrates:
  1_*_jobs_fetching.py     fetch jobs        → *_results.csv / *_jobs_full.json
  2_language_filter.py     language filter   → in-place columns (Language_Filter / Filter_Evidence)
  3  resume creation       via ../resume_creation/ hub (shared V2 engine)  → verified PDFs + job_resume_map_<company>.csv
  4  job application       ONLY in the 4 folders that have an apply bot
```

`python main.py` in any folder runs steps 1→3. Apply-capable folders add `--apply`
(+ `--dry-run` default / `--submit`, `--url`, `--resume`, `--headless` as applicable).
Fetch-only folders accept `--limit N` and `--force`.

**Apply automation exists in exactly 4 folders** (we are OK with that):

| Folder | Fetch | Filter | Resume (hub) | Apply | Apply scripts |
|---|---|---|---|---|---|
| `bosch/` | ✅ | ✅ | ✅ | ✅ | `3_bosch_job_apply.py` + `6_apply_to_jobs.py` |
| `mercedes/` | ✅ | ✅ | ✅ | ✅ | `4_MERCEDES_job_apply.py` (Workday) + `5_apply_taleo.py` + `batch_apply.py` |
| `infineon/` | ✅ | ✅ | ✅ 11 verified (1 honesty-parked) | ✅ | `infineon_job_apply.py` — **10 × SUCCESS, every applicable ENGLISH_OK job applied** (2026-09-22); 2 Villach/Graz internships blocked on personal documents (enrollment cert, transcript, degree cert, motivation letter); 1 job parked by the engine's honesty gate |
| `SAP FETCHER/` | ✅ | ✅ | ✅ | ✅ | `sap_job_apply.py` (SuccessFactors) — **21 × SUCCESS, all ENGLISH_OK jobs applied** (verified 2026-09-22) |
| `bmw/` | ✅ | ✅ | ✅ | — | — |
| `simense/` | ✅ | ✅ | ✅ | — | — |
| `bwi/` | ✅ | ✅ | ✅ | — | — |
| `airbus/` | ✅ | ✅ | ✅ | — | — |
| `simense_energy/` | ✅ | ✅ | ✅ | — | — |

## resume_creation/ — shared hub (drives step 3 for ALL folders)

- `resume_content_improve_research/` — the proven V2 engine, byte-identical copy from
  `E:\WorkSpace\2 Tech\JOB_AUTOMATION` (zero code changes; 114/114 of its tests pass here).
- `prepare_jobs_csv.py` — universal connector: maps each company's fetch data
  (`*_jobs_full.json`; SAP: `sap_results.csv`) to the engine schema
  (`job_url, title, company, job_description`). `--list` resolves all 9 companies.
- `run_resume_creation.py <company> [--limit N] [--jobs substr] [--force]` —
  prepare → step 4 (LLM components) → step 5 (tectonic PDF/DOCX + honesty gates +
  scorecard), **per-company state** (`output_v2/state/components_v2_<company>.json`),
  artifacts snapshotted to `output_v2/resume_<company>/`, and an apply bridge
  `job_resume_map_<company>.csv` (job_url / status OK / resume_pdf) written after step 5.
- Ships its own `sub_program_files/active_ollama_keys.json` + `tools/tectonic.exe`.
- Resumable: already-processed jobs are skipped (no re-paid LLM calls). Interrupted runs
  recover via step-4 checkpoints, guarded by a **slot-owner check** so one company's
  recovery can never ingest another company's records.

## Restructure performed (2026-09-20)

- **Removed** all old stair code (per-folder resume/keys steps: bosch 3/4/5, mercedes 2b/3a/3b,
  infineon/SAP equivalents), all old `program_files/output*` trees, superseded helper
  scripts, and run logs. Old numbered apply scripts were NOT renumbered — apply bots load
  by filename, and their consumers were updated to match.
- **Backed up first**: `Backup_2026-09-20/` holds every removed file (112 files) plus the
  pre-restructure `CURRENT_STATUS.md`. Nothing was deleted without a backup.
- **Uniform `main.py`** written for all 9 folders (the old bosch `main.py` — which crashed
  on a missing `3_test_ollama_keys` import — is gone with the stair code it orchestrated).
- **Apply bots re-pointed** to hub outputs: bosch/mercedes/infineon/SAP apply scripts and
  `batch_apply.py` now read resumes and `job_resume_map_<company>.csv` from
  `resume_creation/program_files/output_v2/` instead of the deleted per-folder outputs.
  `batch_apply.py`'s `load_targets` now accepts the fetcher's `link` column too, and its
  portal classifier recognizes `jobs.mercedes-benz.com` posting URLs (the Workday bot
  resolves them via search-list).

## Mercedes apply batch (2026-09-21)

- `batch_apply.py` upgraded: targets ordered **strong → good → weak → poor** (tier + score
  from the hub shortlist), per-job retry loop (**23 attempts**, 10s backoff — but
  deterministic blockers like `NEEDS_CREDENTIALS`/`NEEDS_ATTENTION` are non-retryable),
  report persisted after every job, Taleo `apply_url` resolved from `custom_fields`,
  missing `RESULTS_DIR` fixed.
- `4_MERCEDES_job_apply.py` fix: the bot never filled **city** on My Information (only
  street/postal), failing verification every time — now filled from
  `config/candidate.json` (`city`).
- **Result: 2 real submissions SUCCESS** — Testbenches/Telematikentwicklung (R0006913) and
  Android Entwicklung in-car (R0006909), the only 2 Workday (MBTI) jobs, both submitted
  with their tailored resumes after clean dry-runs.
- **15 Taleo jobs blocked on credentials**: `tas-DAIMLER.taleo.net` requires a login
  (`TALEO_USERNAME`/`TALEO_PASSWORD` env vars or `taleo_username`/`taleo_password` in
  `mercedes/config/candidate.json`). User chose to skip Taleo and apply manually. 1 job
  routes to mercedes-benz-consulting.de (no automation — manual apply URL in the report).
- Full record: `mercedes/results/batch_apply_report.json` + `batch_apply_workday.log`.

## Verified this session

| Check | Result |
|---|---|
| `py_compile` every `.py` in all 9 folders + hub | ✅ |
| All 9 `main.py --help` (uniform CLI) | ✅ |
| Hub connector `--list`: all 9 companies resolve | ✅ bosch 358, mercedes 210, infineon 27, sap 55, bmw 88, simense 151, bwi 235, airbus 169, simense_energy 32 |
| All 5 apply bots import with hub paths | ✅ |
| bosch `tests/` | ✅ 8/8 |
| mercedes full hub run (210-job union) | ✅ superseded by the role-filter pass below: **47 verified / 7 parked of 54**, map written (47 rows) |

## Role-filter + dot-free education pass (2026-09-20, session 2)

- **Education dots removed everywhere** — the template's education block now renders as
  `itemize[leftmargin=0.15in, label={}]` (plain lines, no bullet dots). All saved components
  were rebuilt with `--build-only` (zero LLM re-spend): mercedes 47 PDF+DOCX, bosch 1, bmw 1.
- **Engine keyword false positives fixed** (`knowledge_base/domain_filters.json`): substring
  tokens no longer gate in irrelevant roles — `sem` vs "Semester", `erp` vs "Erprobung",
  `bank` vs "Datenbank" etc. Engine test suite 110/110 green after the edit.
- **Strict role filter added** — `resume_creation/role_filter.py` + `role_filter_config.json`:
  title keep/drop patterns plus a skill-alignment bar (a title kept only by family signals
  must also clear 60% skill alignment over a real denominator ≥ 4, so sparse business JDs
  can't auto-pass). Runner wiring: `--refilter` (prune saved state, rebuild without new LLM
  calls) and `--build-only`. The runner also re-attaches gated_ok records outside a `--jobs`
  selection (fixes the targeted-run state-drop bug that once cost 12 paid records — they
  were recovered from the backup).
- **Mercedes final set** — 210-job union → 54 relevant records: **47 verified PDFs/DOCX +
  7 parked**, map `job_resume_map_mercedes.csv` = 47 rows. Business roles are out
  (Sekretariatsmanagement, Schadenmanagement, Strategic Retail, Preissteuerung & Marketing,
  Rohbau-Planung, Controlling, NVH, Key Account, Arbeitssicherheit, …); kept roles span
  Android In-Car, Ladekommunikation, KI-Automatisierung, Drive Systems Software, Data
  Engineering/Science, Engineering IT, Testbenches/Telematik, EE-Integration, Charging & HV.
- **Safety** — pre-change backup in `Backup_2026-09-20/pre_rolefilter/` (state + artifacts,
  5.2 MB) before any pruning.
- **Parked 7 (by design)** — the honesty gate refuses these because generated components
  echoed unlicensed numbers straight from the JD (e.g. "12V", "365"); deterministic, so
  retries don't change the outcome. Hand-edit the parked components if those roles are wanted.
| bosch chain end-to-end (fetch → filter → hub --limit 1) | ✅ 1/1 verified + map written |
| Cross-company state contamination | ✅ fixed + owner-guard added; both state files verified clean |

## Language-filter results (step 2, all in place in each folder's CSV)

| Folder | Jobs | ENGLISH_OK | GERMAN_REQUIRED | UNSURE |
|---|---|---|---|---|
| bosch | 358 (full) | from previous filter run | — | — |
| mercedes | 210 | 164 | 46 | 0 |
| bmw | 88 | 19 | 65 | 4 |
| simense | 151 | 63 | 84 | 4 |
| bwi | 235 | 78 | 157 | 0 |
| airbus | 169 | 51 | 70 | 48 |
| simense_energy | 32 | 2 | 1 | 29 |

## Remaining gaps

1. **No apply bots** in bmw, simense, bwi, airbus, simense_energy (accepted for now).
   Airbus = Workday (Mercedes bot is the template); Siemens Energy = Avature; BWI = own
   TYPO3 portal; BMW/Simense portals TBD.
2. **infineon**: apply script still uses hardcoded answers (ignores `config/candidate.json`).
3. **mercedes**: review-page verification has hardcoded email/resume-name (should read config).
4. Fetch-only filters for bosch detail CSV: bosch's `Language_Filter` columns predate the
   restructure and came from its own filter variant; re-running `2_language_filter.py`
   refreshes them in place if desired.

## Layout snapshot

```
Backup_2026-09-20/      ← pre-restructure snapshot (112 files) + Backup_2026-09-18 inside history
resume_creation/        ← shared hub (engine + connector + runner + state/PDF outputs)
bosch/ mercedes/ infineon/ "SAP FETCHER"/    ← fetch → filter → hub → apply
bmw/ simense/ bwi/ airbus/ simense_energy/   ← fetch → filter → hub
CURRENT_STATUS.md       ← this file
```
