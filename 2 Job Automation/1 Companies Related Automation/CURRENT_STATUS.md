# CURRENT_STATUS.md — workspace restructured & verified 2026-09-24

Nine company folders, one shared resume hub, one uniform pipeline. This file
describes the **current** structure and state; dated history lives in
`_reports/` (APPLICATION_RUN / DRYRUN_REPORT, 2026-09-22) and `_archive/`.

---

## The one structure, everywhere

```
main.py in any company folder runs:
  1_*_jobs_fetching.py     fetch jobs        → *_results.csv / *_jobs_full.json
  2_language_filter.py     language filter   → in-place columns (Language_Filter / Filter_Evidence)
  3  resume creation       via ../resume_creation/ hub (shared V2 engine) → verified PDFs + job_resume_map_<company>.csv
  4  job application       ONLY in the 4 apply-capable folders (--apply; dry-run default, --submit gated)
```

| Folder | Fetch | Filter | Resume (hub) | Apply | Portal / notes |
|---|---|---|---|---|---|
| `1_BOSCH/` (renamed from `bosch/` 2026-09-24) | ✅ 350 | ✅ 125 ENGLISH_OK | ✅ 7 verified | ✅ bot healthy | SmartRecruiters; **all forms behind DataDome CAPTCHA — human must solve in the visible window** (`6_apply_to_jobs.py --all --submit --wait-after-captcha 300`) |
| `mercedes/` | ✅ 210 | ✅ 164 ENGLISH_OK | ✅ 47 verified | ✅ 2 submitted | Workday done; 15 Taleo jobs blocked on credentials (skip or add `TALEO_USERNAME/PASSWORD`); `batch_apply.py` tier-ordered |
| `infineon/` | ✅ | ✅ | ✅ 11 verified | ✅ 10 submitted | Eightfold; every auto-applicable ENGLISH_OK job done; 2 Villach/Graz blocked on personal documents; answers partly hardcoded (should read `config/candidate.json`) |
| `SAP FETCHER/` | ✅ | ✅ | ✅ | ✅ 21 submitted | SuccessFactors; **every ENGLISH_OK job exhausted**; 1 job needs a `QUESTION_SPECS` entry (variant question) |
| `bmw/` | ✅ 88 | ✅ 19 ENGLISH_OK | ✅ 2 verified (weak fits) | — | portal TBD |
| `simense/` | ✅ 151 | ✅ 63 ENGLISH_OK | ✅ | — | portal TBD |
| `bwi/` | ✅ 235 | ✅ 78 ENGLISH_OK | ✅ | — | own TYPO3 portal |
| `airbus/` | ✅ 169 | ✅ 51 ENGLISH_OK | ✅ | — | Workday (Mercedes bot is the template) |
| `simense_energy/` | ✅ 32 | ✅ 2 ENGLISH_OK | ✅ | — | Avature |

## resume_creation/ — the shared hub (step 3 for ALL folders)

- `resume_content_improve_research/` — the V2 engine, mirror of
  `E:\WorkSpace\2 Tech\2 Job Automation\Regular\resume_content_improve_research`
  (cover-letter/step-6 machinery stripped; domain-filter keyword list carries the
  2026-09-20 substring false-positive fixes). **114/114 engine tests pass.**
- Pipeline inside the hub per company: `prepare_jobs_csv.py` (maps the company's
  full fetch JSON/CSV → engine schema, union, dedup) → **domain gate**
  (`generation/domain_filter.py`, runs BEFORE any LLM call; keeps only
  in-domain jobs) → step 4 (LLM components, KB-grounded, honesty gates,
  429-key rotation) → step 5 (tectonic PDF/DOCX, post-build gates, scorecard).
- Per-company state: `program_files/output_v2/state/components_v2_<company>.json`,
  snapshots `resume_<company>/`, apply bridge `job_resume_map_<company>.csv`.
  Resumable; interrupted runs recover with slot-owner guards.
- Keys: `sub_program_files/{ollama_keys,active_ollama_keys}.json` — 4 keys, the
  3 rotation keys added 2026-09-22 are present; `generation/llm.py` rotates on
  HTTP 429 (exhausted key parked in-process).
- Runner: `python run_resume_creation.py <company> [--limit N] [--jobs substr]
  [--force] [--refilter] [--build-only]`. Company/source listing = run with NO
  args (`--list` does not exist despite older docs).

## Verified 2026-09-24 (restructure day)

- Every live `.py` in all 9 folders + hub + tools compiles clean.
- `1_BOSCH` shadow-DOM apply tests: **8/8**.
- Engine tests: **114/114**.
- Hub `--list` equivalent: all 9 companies resolve to their fetch sources
  (bosch → `1_BOSCH/BOSCH_jobs_full.json`, 350 rows mapped).
- Domain gate on Bosch: 350 → **314 kept / 36 eliminated**.
- Bosch resume rebuild from saved state (`--build-only`, zero LLM cost):
  **7/7 verified PDFs** in 40s, map rewritten, all paths valid.

## Changes made 2026-09-24

1. `bosch/` → **`1_BOSCH/`**; fetcher renamed `1_BOSCH_Jobs_fetching.py`;
   all live references updated (main.py, README, filter comment, hub sources).
2. `prepare_jobs_csv.py`: Bosch entry re-pointed to `1_BOSCH/…`; dead
   `program_files/output_*/2_filted_jobs.csv` source entries removed for all
   companies (those trees are gone; the engine's domain gate filters instead).
3. **Cleanup** (nothing deleted without a check that nothing references it):
   - Root: 3 dated reports → `_reports/`; `Backup_2026-09-18/20` folders +
     3 backup zips → `_archive/Backups/` (zips in `_archive/Backups/_zips/`).
   - Deleted: all `__pycache__/` + `.pytest_cache/` workspace-wide; stale
     `mercedes/results/*.log` + `state/batch_mercedes*.log`; `1_BOSCH/`
     legacy `sub_program_files/` (old stair prompts/scripts, unused since the
     restructure); `resume_creation/program_files/output/` (legacy tree;
     `prepare()` mkdirs its own); orphan `mercedes/filtered_jobs.csv` (no code
     reads it) → `_archive/`.
   - Deleted 4 duplicate `tectonic.exe` copies (~150 MB): `1_BOSCH/`,
     `mercedes/`, `infineon/`, `SAP FETCHER/` — no company code references
     tectonic; the hub's `resume_creation/tools/tectonic.exe` is the only one used.
   - Mercedes/Infineon/SAP `sub_program_files/` kept (apply bots in those
     folders still load keys from them).
4. `1_BOSCH/README.md` rewritten for the current pipeline; `resume_creation/
   README.md` corrected (source table, `--list` removal, note about dropped
   per-company filtered-CSV sources).

## Remaining gaps / next actions

1. **Bosch applications** need a supervised session: `python 6_apply_to_jobs.py
   --all --submit --wait-after-captcha 300` (typed YES; solve each DataDome
   challenge in the opened window). 7 tailored resumes are staged.
2. **Mercedes Taleo**: add `TALEO_USERNAME`/`TALEO_PASSWORD` (env or
   `mercedes/config/candidate.json`) to unlock 15 blocked jobs.
3. **Infineon**: apply script should read answers from `config/candidate.json`
   instead of hardcoded values.
4. **SAP 1437976633**: needs a `QUESTION_SPECS` entry for its work-authorization
   question variant before it can be applied.
5. No apply bots in bmw/simense/bwi/airbus/simense_energy (by design for now).
6. Fetch-only filters: rerunning `2_language_filter.py` in bosch refreshes
   columns in place if ever needed.

## Layout snapshot

```
1_BOSCH/  mercedes/  infineon/  "SAP FETCHER"/    ← fetch → filter → hub → apply
bmw/  simense/  bwi/  airbus/  simense_energy/    ← fetch → filter → hub
resume_creation/                                   ← shared hub (engine + connector + runner + state/PDFs)
_reports/          ← APPLICATION_RUN_2026-09-22.md, DRYRUN_REPORT_2026-09-22.md, archived status docs
_archive/          ← Backups/ (2026-09-18 + 2026-09-20 snapshots, zips in _zips/), legacy extras
CURRENT_STATUS.md  ← this file
```
