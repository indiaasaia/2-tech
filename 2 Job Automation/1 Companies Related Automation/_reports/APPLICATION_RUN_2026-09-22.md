# Application Run Report — SAP & Infineon (executed 2026-09-22)

Two real job applications were submitted today, one per company, each through its
own Playwright bot following the full safety protocol: **fresh fetch → language
filter → dry-run → verified → real submit**. No duplicates: both target jobs were
cross-checked against every previously submitted job ID before starting.

---

## 1. SAP — SUCCESS ✅

| | |
|---|---|
| **Job** | Working Student (f/m/d) for Agentic AI and Robot Learning Research in Cooperation with KIT |
| **Job ID** | `1439977333` |
| **Location / posted** | Walldorf, DE — posted **Sep 22, 2026 (today)** |
| **URL** | https://jobs.sap.com/job/Walldorf-Working-Student-%28fmd%29-for-Agentic-AI-and-Robot-Learning-Research-in-Cooperation-with-KIT-69190/1439977333/ |
| **Resume used** | `RAVAL_MEETKUMAR_RESUME.pdf` (verified in the portal's My Documents: chip shows the filename, `verified: true`) |
| **Flow** | 8/8 stages — job page → Apply + auto-login (env credentials) → resume replaced (previous: *Autonomous Suite Transformation Office*, a job applied to earlier) → skills capped (61 stale chips removed) → questions filled → validated → **submitted** |
| **Answers** | Legally authorized to work: **Yes** · Currently employed by: **None of the Above** · Previously employed by SAP: **No** · Country of residence: **Germany** · Gender: **Male** · Consent: **checked** |
| **Proof** | `SAP FETCHER/results/sap-1439977333-result.json` → `status: SUCCESS`, `confirmationMessage: true`, `errors: []`, success screenshots |
| **Dry-run before submit** | `DRY_RUN COMPLETE` — identical walk, submit intentionally skipped |

SAP totals: **16 real submissions on record** (15 previous + this one).

### SAP notes / incidents handled
- First dry-run attempt hit `NEEDS_ATTENTION: No 'Apply now' link found` — the
  SPA was still on its "Loading…" screen. Verified server-side that the job was
  open (`/talentcommunity/apply/1439977333/` present in HTML) and retried: clean.
- The bot itself detected an **"Already applied"** state on some pages and treats
  it as SUCCESS (dedup guard built in).

---

## 2. Infineon — SUCCESS ✅

| | |
|---|---|
| **Job** | Working Student - AI-Assisted Embedded Software Development (f/m/div) |
| **Position ID** | `563808972009600` |
| **Location** | Munich (site-preselected, left unchanged per spec) |
| **URL** | https://jobs.infineon.com/careers/apply?pid=563808972009600 |
| **Resume used** | `RAVAL_MEETKUMAR_RESUME.pdf` — Eightfold parsed it; contact autofill **verified read-only**: Raval Meetkumar · ravalmeett@gmail.com · 🇩🇪 +49 phone |
| **Flow** | 8/8 stages — cookie banner (OneTrust) dismissed → resume upload + confirm dialog + parser wait → privacy popup → contact verification → location (preselected `Munich`) → selects (Gender **Male** / Country of residence **Germany** / Language **English** — exact-match combobox selection with read-back) → disability: **No selection** (never `Disabled`) → validated → **submitted** |
| **Proof** | `infineon/results/563808972009600-result.json` → `status: SUCCESS`, confirmation page **"Thank you"**, `errors: []` |
| **Dry-run before submit** | `DRY_RUN_COMPLETE` — zero errors |

Infineon totals: **2 real submissions on record** (1 previous + this one), plus 2 dry-runs.

---

## Why these two jobs

Both companies' resume hubs could not generate tailored PDFs today: the single
Ollama Cloud key (`gpt-oss:120b`) returned **HTTP 429** for the entire session
(≥13 min of retries across all key files in the workspace — one distinct key
exists, shared between Regular and Companies). Rather than stall, the bots' own
`--resume` override was used with the candidate's real base CV (the same file the
cold-email campaign attaches). Both submissions were verified end-to-end by the
bots' built-in checks, so nothing was at risk.

Targets were chosen by: `ENGLISH_OK` filter + **not in the already-applied ID
list** (SAP: 15 IDs, Infineon: 3 IDs) + best profile fit:

- **SAP**: 6 new ENGLISH_OK candidates appeared after today's fresh fetch; the
  Agentic-AI/Robot-Learning job (posted today) is the strongest AI-profile match.
- **Infineon**: 11 new ENGLISH_OK candidates; the AI-Assisted Embedded SW job is
  the only software/AI match (the rest are facility/legal/lab/mechanical roles).

## Pending follow-up — UPDATE (same day, later session)

1. **✅ DONE — Key rotation added:** 3 fresh Ollama keys (all live-tested) were
   added to all 6 `ollama_keys.json` / `active_ollama_keys.json` files, and both
   engine copies' `llm.py` now **rotate keys automatically on HTTP 429** (the
   dead key is parked in-process, the next key takes over). Verified live: the
   old 429 key was skipped and a fresh key answered. Engine tests: 109 passed.
2. **✅ DONE — Tailored resumes built:** hub runs with the rotated keys produced
   verified per-job resumes — SAP Agentic AI job **score 73.8**, Infineon
   AI-Assisted Embedded SW job **score 69.2** (`job_resume_map_sap.csv` /
   `job_resume_map_infineon.csv` written). The applications above went out with
   the base CV; these tailored PDFs are banked for future submissions (do NOT
   re-apply to the same jobs — they are already submitted).
3. **Open:** 5 more new ENGLISH_OK SAP jobs await the same dry-run→submit flow
   (1437947533 HR L&D, 1437176333 MT/NLP, 1437848533 SAI-native SW Dev,
   1437976633 AI Software Engineer, 1435713633 IT Portfolio) — now with
   tailored resumes available via the hub.
## Files touched today

- `SAP FETCHER/sap_results.csv` (fresh fetch + filter, in place) ·
  `SAP FETCHER/results/sap-1439977333-*` (result JSON + screenshots) ·
  `infineon/INFINEON_jobs_detailed.csv` + `INFINEON_jobs_full.json` (fresh fetch) ·
  `infineon/results/563808972009600-*` (result JSON + screenshots) ·
  `CURRENT_STATUS.md` (updated company rows) ·
  `resume_creation/program_files/output_v2/` (one parked SAP record from the
  429'd hub attempt — retried automatically on the next hub run; no cost incurred).
- **No source code was modified.** The `str`→`Path` resume-argument quirk in
  `apply_to_sap_job` was worked around by passing a `Path`, not patched.

---

# Evening update — SAP exhausted end-to-end (2026-09-22, later)

The 5 open jobs above were all executed through the gated runner
(`sap_apply_new_jobs.py`: skip-if-SUCCESS → resolve hub resume → dry-run →
submit-with-retries). **All 5 submitted successfully: 1437848533 (SAI-native
SW Dev, after one transient server-side rejection cleared on retry),
1437947533 (HR L&D), 1437176333 (MT/NLP), 1435713633 (IT Portfolio —
separate requisition 460103 from Sep-14's 460102), 1437976633 (AI Software
Engineer, Garching).**

**SAP totals: 21 real submissions — every ENGLISH_OK job in the dataset is
now applied.** GERMAN_REQUIRED postings stay untouched by design.

## Hardening added to `sap_job_apply.py` (both fixes live-verified)

1. **Dropdown popover race:** `_select_combo_option` now waits up to 5 s for
   the exact option to render before counting. Root cause of the earlier
   `option 'Yes' not found` blocker on 1437976633 — the read-only probe
   (`probe_sap_form.py`) proved the option existed (`No Selection / No / Yes`).
2. **Post-submit verdict race:** SAP's confirmation can render slower than
   the old 15 s poll. Verification now polls 75 s and also accepts the
   `_detect_already_applied` server-side detector as strong SUCCESS evidence.

## Incident & resolution on 1437976633

The submit click landed with all fields verified, but the old 15 s window
expired before SAP rendered its confirmation → `NEEDS_ATTENTION`. A new
read-only checker (`check_sap_applied.py`, validated with a positive control
1437176333 → applied, and a negative control 1427772233 → form present)
confirmed SAP shows **"You already applied for this position."** with the
submit form gone → result JSON reconciled to SUCCESS with the evidence note
appended (`results/sap-1437976633-result.json`, `check-1437976633.json`).

## New tools (read-only unless run with submit gates)

- `SAP FETCHER/probe_sap_form.py` — dumps every form combobox + exact option
  names for one requisition (fills nothing, submits nothing).
- `SAP FETCHER/check_sap_applied.py` — read-only already-applied check with
  raw evidence + screenshot; controls recorded in `results/check-*.json`.
- `SAP FETCHER/sap_apply_new_jobs.py` — the gated per-job runner described above.
- `resume_creation/tools/fix_resume_paths.py` — one-shot repair of stale
  absolute resume paths in the hub maps (49 paths fixed after the folder rename).

---

# Infineon exhausted end-to-end (2026-09-22, night)

Request: "do for Infineon, check everything is already applied". Audit found
**2 of 12 ENGLISH_OK jobs applied** (…922747, …009600), 2 more dry-run-only,
and 9 never touched. All applicable gaps have now been closed:

| Job | Result |
|---|---|
| 563808971794202 Foundry Supplier Market Intelligence | **SUCCESS** |
| 563808971991308 Pool Position (Ilmenau) | **SUCCESS** |
| 563808972041838 Automotive Project Office | **SUCCESS** |
| 563808971620732 Lab Verification AMS | **SUCCESS** |
| 563808971118853 High Speed & RF Lab Validation | **SUCCESS** |
| 563808971879852 Supplier Sustainability | **SUCCESS** |
| 563808971880480 Technisches Gebäudemanagement | **SUCCESS** |
| 563808959893172 Warstein general pool | **SUCCESS** (after fix, see below) |
| 563808971793447 Legal Compliance ESH&E (Villach) | ⛔ blocked: requires enrollment certificate + transcript + degree certificate + motivation letter |
| 563808971906944 Project Management Support (Graz) | ⛔ blocked: same document set |
| 563808971994519 Interface wafer production | ⛔ parked by the honesty gate (generator wanted non-KB number '365'; engine refused, correctly) |

**Infineon totals: 10 × SUCCESS — every ENGLISH_OK job that CAN be applied
automatically has been applied.**

## Audits & fixes made along the way (all live-verified)

1. **Eightfold shows no applied-status anywhere** (positive + negative
   controls via `check_infineon_applied.py` render identical forms) → the
   local result-JSON ledger is the only duplicate-application guard; the
   gated runner enforces skip-if-SUCCESS.
2. **Austrian postings (Villach/Graz) have no Germany-specific section** →
   disability step is now conditional (section absent = nothing to answer);
   30s+ render wait. The blocked pair additionally demands 4 personal
   documents that do not exist in the workspace — never fabricated.
3. **Position-specific questions (Warstein-style forms)** — a checkbox group
   ("form of employment") + availability text — previously unknown to the
   bot, caused a silent client-side reject on 563808959893172 (form stayed
   open, "2 errors found"; screenshots prove nothing was submitted). New
   handler answers truthfully ("Working Student position" +
   declared-availability text from the campaign profile) with read-backs.
   Retry allowlisted explicitly for that one job (`RETRY_AFTER_CLIENTSIDE_REJECT`).

New tools: `infineon/check_infineon_applied.py` (read-only evidence dumper),
`infineon/infineon_apply_new_jobs.py` (gated skip→dry-run→submit runner).

---

# Bosch capability run (2026-09-22, night)

Request: check whether Bosch has application automation; if yes try it; if it
succeeds, apply to all jobs.

**Answer: the automation exists and is healthy — but every Bosch application
form is gated by DataDome bot protection, which the bot correctly refuses to
bypass.** Two live dry-runs (744000149868802 MBSE, 744000149826650 ML
Predictive Reliability) both walked to the application form and stopped with
CAPTCHA_DETECTED; the 180s/90s manual-solve windows passed unsolved because
nobody was at the browser. A human must solve the DataDome challenge once per
application in the visible browser window — by design, the bot never bypasses.

## Staged and ready for a supervised session

- Fresh fetch: 350 jobs (125 ENGLISH_OK / 204 GERMAN_REQUIRED / 21 UNSURE).
- **7 tailored resumes verified** for the best AI/software English fits:
  ML Predictive Reliability (76.3), MBSE internship (76.3), Software Quality
  Engineering (62.9), Softwareentwicklung & Datenanalyse (55.5), ML für
  prädiktive Zuverlässigkeit (48.2), Data Engineering Akustik (29.7),
  Digitale Bildung (28.0). Engine honestly flags weak fits — truthfulness
  over volume.
- One command applies them all when you are present:
  `python 6_apply_to_jobs.py --all --submit --wait-after-captcha 300`
  (typed YES gate; solve each DataDome challenge in the opened window).

## Fixed en route

- `resume_report_bosch.json` held stale old-tree paths AND a generic
  `resume\` dir that no longer holds artifacts (per-company snapshot
  `resume_bosch\` does) — `tools/fix_resume_paths.py` now repairs report
  JSONs too; 7/7 PDFs verified on disk.
