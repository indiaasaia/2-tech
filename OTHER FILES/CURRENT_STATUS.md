# Current Status — Whole Workspace (verified 2026-09-22)

One workspace, two independent automation projects, both aimed at the same goal:
**landing a Werkstudent / intern software / AI / data role in Germany for
Meetkumar Raval (M.Sc. AI @ BTU Cottbus-Senftenberg, B1 German)**.

```
CURRENT_STATUS.md          <- this file (workspace root)
step_1_updated_code.py     <- standalone optimized Stage-1 job fetcher (no project deps)
BOSCH FETCHER.zip          <- 118 MB snapshot of the Companies workspace (2026-09-20)
JOB_AUTOMATION - Copy.zip  <- 44 MB snapshot of Regular incl. .git (2026-09-22)
1 Cold Emailing/Cold Emaling/          <- Project 1: Gemini cold-outreach campaign (LIVE)
2 Job Automation/Regular/              <- Project 2A: daily job scanner -> verified resumes
2 Job Automation/Companies Related Automation/  <- Project 2B: 9 employers, fetch -> resume -> apply
```

Per-project status docs also exist: `2 Job Automation/Companies Related Automation/CURRENT_STATUS.md`
(detailed, current) and `2 Job Automation/Companies Related Automation/Backup_2026-09-18/CURRENT_STATUS.md`
(pre-restructure history).

---

## TL;DR

| Project | State | Last activity | Headline numbers |
|---|---|---|---|
| Cold Emailing | **PAUSED** — fully built & proven, no sends since 2026-08-31 | 2026-08-31 | 546 emails sent; 28 agencies / 347 contacts / 332 queued; 20 agencies & 120 emails/day caps |
| Job Automation · Regular | **ACTIVE** — scanner + engine fully working | 2026-09-21 | 70 verified resumes (34 strong-fit), 91 PDFs built, 251 jobs tracked, 0 quarantined |
| Job Automation · Companies | **ACTIVE** — SAP + Infineon English pools exhausted; Bosch staged | 2026-09-22 | SAP: **21 real submissions** (all ENGLISH_OK jobs); Infineon: **10** (all applicable ENGLISH_OK); Mercedes: 2 real Workday + 47 tailored; Bosch DataDome-gated (human solve needed); Taleo gated on credentials |

---

## Project 1 — Cold Emailing (`1 Cold Emailing/Cold Emaling/`)

**Campaign:** Germany recruiting / staffing / employment agencies that place
working students & interns; sender registers as a candidate. Fresh start
2026-08-29 (previous tech-company pool archived).

**Pipeline (all wired, `python -m phase_3.campaign --loop`):**
send queued → Phase 2 contact discovery (pending first) → Phase 1 research
(deficit only) → Phase 2 discovery (new) → build list → Gemini hooks →
personalization audit → send. Prompts for every phase live in one root
`prompts.md`; keys rotate across `gemini_keys.json` (4 Gemini keys) and
`streamlit_app/settings.json` (3 Yandex keys); model chain gemini-3.7 → 3.6 →
3.5-flash; Streamlit control center runs the same phases from a browser.

**Where it stands (from the state files):**

| Metric | Value | Source |
|---|---|---|
| Agencies researched (Phase 1) | 28 | `phase_1/data/discovered_companies.csv` |
| Phase 2 outcomes | 28 × `CONTACTS_FOUND` (0 pending, 0 error) | `phase_2/data/contact_discovery_outcomes.csv` |
| Contacts discovered | 347 | `phase_2/data/contact_discovery_results.csv` |
| Queued recipients | 332 | `phase_3/contacts_to_send.csv` |
| Emails sent | **546, all status `sent`** | `phase_3/sent_history.csv` |
| Send window | 2026-08-27 → **2026-08-31** (idle ~3 weeks) | `sent_history.csv` + `state.json` daily_counts (29th: 13, 30th: 71, 31st: 51) |
| Gemini calls logged | 109 (phase2: 76, hooks: 26, phase1: 7) | `phase_3/data/gemini_usage.json` |
| Name pool | `company_names.csv` is empty — research is prompt-driven | `phase_1/data/` |

**Config right now:** `MAX_PER_DAY=120`, `MAX_PER_COMPANY=6`,
`MAX_AGENCIES_PER_DAY=20`, 45s delay + 15s jitter, `SEND_MODE=test`
(real sends go through `--mode all` / the campaign loop), CV attached via
`../RAVAL_MEETKUMAR_RESUME.pdf`.

**Known quirks (harmless but real):**
- `data/gemini_usage.json` starts with a stray `[]` before the JSONL records —
  cosmetic; every consumer tolerates it.
- Campaign loop stop conditions (email cap, agency cap, Gemini empty ×2/×3)
  mean an idle-looking run can simply be quota exhaustion — check
  `data/campaign_log.csv` for the `loop_stop` reason before assuming breakage.

**Next levers:** rerun the campaign loop for a new batch of 10 agencies/day;
widen `{{CITIES}}` (currently Munich in streamlit settings); the 332 queued
recipients still have sends left under the caps.

---

## Project 2A — Regular scanner (`2 Job Automation/Regular/`)

**Pipeline (all 5 steps verified end-to-end, `python main.py`):**
1. Fetch Stepstone + workingstudentjobs.de (Selenium / urllib + JSON-LD)
2. Freshness (today/yesterday) + English stopword filter + loose domain buckets
3. Ollama key test → `active_ollama_keys.json`
4. Engine step 4: domain gate (family keywords + 60% skill alignment) → JD
   analyst → claimable set (KB ∪ mirrorable JD tools) → constrained generation →
   deterministic tailoring → G2/G3 pre-build gates (regenerate loop)
5. Engine step 5: `@@TOKEN@@` LaTeX → tectonic PDF + DOCX → parse-back →
   G1/G3 post-build gates → coverage → scorecard → triage

The root `step_1_updated_code.py` is the optimized standalone variant of step 1
(parallel listings, listing-level prefilter, atomic 24 h detail cache).

**Where it stands (from the output tree, last run 2026-09-21):**

| Metric | Value | Source |
|---|---|---|
| Jobs in last filtered batch | 95 | `program_files/output/2_filted_jobs.csv` |
| Jobs tracked in dashboard | 251 | `program_files/output/job_status.csv` |
| Engine store | 88 records (`gated_ok` / `parked`) | `output_v2/components_v2.json` |
| **Verified resumes** | **70** | `output_v2/shortlist.json` |
| Tier split | strong 34 · good 17 · weak 11 · poor 8 | `shortlist.json` |
| PDFs on disk | 91 (incl. superseded builds) · `failed/` empty | `output_v2/resume/pdf/` |
| Recommendation | "apply to the 34 strong-fit job(s) first; 19 below the 50-point effort line" | `shortlist.json` |
| Engine tests | 114/114 (last verified 2026-09-20) | `resume_content_improve_research/tests` |

**Git:** only this folder is a repo (2 commits, branch `main` + origin). The
v1→v2 restructuring (old files moved to `old_files/`, dashboard rename, new
requirements.txt) is **still uncommitted** — worth committing once reviewed.

**Next levers:** apply to the 34 strong-fit jobs (bot exists for SAP/Bosch/
Mercedes/Infineon portals only); re-run the scanner for a fresh day's batch;
commit the pending restructure.

---

## Project 2B — Companies (`2 Job Automation/Companies Related Automation/`)

Uniform sequence in all 9 folders: `main.py` = fetch → language filter →
shared `resume_creation/` hub (same V2 engine, per-company state) → apply
(exactly 4 folders have apply bots).

| Folder | Fetch | Language filter | Hub resumes | Apply | Notes |
|---|---|---|---|---|---|
| `bosch/` | ✅ 350 | ✅ 125 EN | ✅ 7 verified | ✅ SmartRecruiters (+ DataDome pause-and-solve, 8/8 shadow-DOM tests) | automation healthy but **every form is DataDome-gated** — needs a human at the browser (2026-09-22 verified on 2 jobs); 7 tailored resumes staged, one command applies them all |
| `mercedes/` | ✅ 210 | ✅ 164 EN / 46 DE | ✅ **47 verified + 7 parked** | ✅ Workday + Taleo + `batch_apply.py` | see batch results below |
| `infineon/` | ✅ 26 | ✅ 12 EN | ✅ 11 verified (1 honesty-parked) | ✅ Eightfold | **10 × SUCCESS — every applicable ENGLISH_OK job applied (2026-09-22)**; 2 Villach/Graz internships blocked on personal docs; 1 parked by honesty gate; Eightfold shows no applied-status server-side → local ledger is the duplicate guard |
| `SAP FETCHER/` | ✅ 51 | ✅ | ✅ 6 verified | ✅ SuccessFactors | **21 × SUCCESS — every ENGLISH_OK job applied (2026-09-22)**; question-forms hardened: exact-option popover wait + already-applied detector as strong SUCCESS evidence |
| `bmw/` | ✅ 88 | ✅ 19 EN / 65 DE | ✅ 1 verified | — | fetch-only |
| `simense/` | ✅ 151 | ✅ 63 EN / 84 DE | ✅ | — | fetch-only (Avature) |
| `bwi/` | ✅ 235 | ✅ 78 EN / 157 DE | ✅ | — | fetch-only (TYPO3 AJAX) |
| `airbus/` | ✅ 169 | ✅ 51 EN / 70 DE / 48 UNSURE | ✅ | — | fetch-only (Workday CXS) |
| `simense_energy/` | ✅ 32 | ✅ 2 EN / 1 DE / 29 UNSURE | ✅ | — | fetch-only (Avature) |

**Mercedes apply batch (2026-09-21, `mercedes/results/batch_apply_report.json`):**
18 targeted jobs → **2 real submissions SUCCESS** (Testbenches/Telematik
R0006913, Android in-car R0006909 — the only 2 Workday jobs), **15 Taleo jobs
blocked on credentials** (`NEEDS_CREDENTIALS`, user chose manual apply), 1 job
outside any automation. Tier-ordered targets, 23-attempt retry budget,
non-retryable blockers respected.

**Hub guarantees:** per-company state files (`state/components_v2_<company>.json`
+ `job_resume_map_<company>.csv`), slot-owner check so interrupted runs of one
company never bleed into another's recovery, resumable without re-paying LLM
calls, artifacts snapshotted to `resume_<company>/`. `role_filter.py` prunes
non-technical titles (Mercedes: 210 → 54 relevant → 47 verified).

**Backups:** `Backup_2026-09-18/` and `Backup_2026-09-20/` (112 files +
`pre_rolefilter/` state) hold every removed file. Nothing was ever deleted
without a backup.

**Known gaps (documented, accepted):**
1. No apply bots in bmw / simense / bwi / airbus / simense_energy.
2. Infineon apply: gender/residence selects are fixed constants (they match the candidate); contact data comes from resume autofill, verified read-only — no candidate.json wiring needed for these fields.
3. Mercedes review-page verification has hardcoded email/resume-name.
4. The two engine copies drifted: `Regular/…` vs
   `Companies/resume_creation/…` differ only in `knowledge_base/domain_filters.json`
   (154 keyword leaves; Companies copy is newer) and
   `templates/core_resume_template_v2.tex` (Companies copy has the dot-free
   education itemize + `\linewidth` fixes). Engine code is otherwise identical.

---

## Operational notes (whole workspace)

- **Secrets live in plain files** (fine locally, but mind the zips):
  `phase_3/.env` (Gmail app password), `gemini_keys.json` (4 Gemini keys),
  `streamlit_app/settings.json` (3 Yandex keys),
  `sub_program_files/ollama_keys.json` in both projects, personal data in
  `*/config/candidate.json` and `phase_3/.env`. Regular's `.gitignore` covers
  its keys; the root is not a git repo; the two zips contain copies.- **LLM stack:** Ollama Cloud (`https://ollama.com`, `gpt-oss:120b`) for resumes — 4 keys on file, engine rotates to the next key on 429 (`_EXHAUSTED_KEYS`); Gemini Flash chain + YandexGPT for research/contacts/hooks.
- **Safety conventions everywhere:** dry-run-first apply bots with typed-YES
  submission gates, CAPTCHA never bypassed, every field read back from the DOM,
  CSV/JSON-as-source-of-truth with save-after-every-unit, deterministic
  checks before any LLM spend, honesty gates so resumes only ever contain
  KB-licensed claims.
- **Redundant copies:** two backup folders, two zips, `old_files/` trees and the
  `_archive` inside Cold Emailing — all intentional history, not clutter to
  clean blindly.
