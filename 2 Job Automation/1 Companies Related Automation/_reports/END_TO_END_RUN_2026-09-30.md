# End-to-End Run — 2026-09-30 (Bosch, Mercedes, Infineon, SAP)

## Executive summary

| Company | Fetch | Filter | Resumes built | Submitted this run | Total (ledger) | Blocker |
|---|---|---|---|---|---|---|
| Bosch | ✅ 353 fetched | ✅ | ✅ 19 tailored (scores 28–76) | **0** | 0 | DataDome flags Playwright-driven Chrome as "Automated (bot) activity"; needs one human RETRY click per session |
| Mercedes | ✅ | ✅ | ✅ | **0** | 2 (Workday) | All strong-fit jobs route to Taleo → login credentials required |
| Infineon | ✅ | ✅ | ✅ | **+2** | 12 | Remaining jobs blocked on mandatory certificate/transcript uploads (docs not provided) |
| SAP | ✅ (fetcher rewritten) | ✅ | — | **0** | 21 | New site layout handled; 0 of 12 open "werkstudent" jobs are in Germany |

## Bosch — details

- Pipeline ran fully: fetch 353 → language/domain filter → hub built **19 tailored resumes** (`job_resume_map_bosch.csv`, best score 76.3).
- `patient_apply.py` ran 2 full rounds over all 19 jobs with real Chrome (`BOSCH_BROWSER_CHANNEL=chrome`), 600s human-RETRY budget per job. Result: 0 submitted — DataDome's "Verification Required" interstitial appeared on every form load with reason **"Automated (bot) activity"** and never auto-cleared; nobody clicked RETRY in the visible window during the waits.
- Bot bugs found and FIXED during this run (all py_compile clean, 8/8 tests pass):
  1. `upload_resume` verification never succeeded because the 31k-char page always contains the word "uploading" somewhere (i18n strings). The uploading-guard is now scoped to a ±60-char window around the filename.
  2. `fill_email` refused the unlabeled Email + Confirm-Email pair ("Multiple email-like fields"). It now fills all `type=email` inputs with the same address (not a guess by definition), only bailing when matches are label-fuzzy and not type=email.
  3. `_fill_text` crashed on shadow-DOM inputs Playwright locators can't reach (`#email-input` is an `spl-input` host); now falls back to the JS resolver (`_js_set_value`).
  4. Resolver `set` mode threw `TypeError: Illegal invocation` when applying the HTMLInputElement value setter to `oc-input` custom-element hosts; now guards on element type and sets via the inner input.
- Status: bot reaches the upload → questions → consent → (would-be) submit flow whenever the gate clears; earlier evidence (error screenshots) shows the resume chip renders and the form fills. The only remaining blocker is the DataDome human click.
- Policy kept: CAPTCHAs/challenges are never bypassed; the bot parks and waits (semi-attended mode) or stops.

## Mercedes

- Full refresh: fetch → filter → resume hub → batch apply driver. All strong-fit jobs route to **Taleo**, which requires login credentials we don't have (15 jobs). The single automatable Workday job scored 35 (below the 50-point effort line) and was deliberately not submitted. Totals: 2 submitted (earlier Workday).

## Infineon

- Full refresh found **2 new applyable jobs** → both **submitted successfully** via the Eightfold apply driver (`infineon_apply_new_jobs.py` + `check_infineon_applied.py`). Ledger: 12 total. Remaining gated jobs need certificate/transcript documents from you.

## SAP

- Careers site migrated to a Next.js SPA; old `data-careersite-propertyid` markup is gone. `1_sap_job_fetcher.py` rewritten with a JSON-LD JobPosting parser (title, location, date, employment type, full description) + `/en/jobs/<id>/<slug>/` anchor list parser; legacy parsers kept as fallback. Verified live: 12 jobs fetched with full descriptions.
- Of those 12 "werkstudent" results, **0 are located in Germany** (Jeddah, Levallois-Perret, Sofia, Prague, Tokyo, etc.), so the language/location gate correctly yields nothing new to apply for. Ledger: 21 submitted (exhausted).

## What's needed to unblock

1. **Bosch (19 staged jobs, resumes ready):** run `patient_apply.py --captcha-wait 600` again and **click RETRY once in the visible Chrome window** when "Verification Required" appears. Everything after that click is fully automated. (Note: DataDome may hard-block this fingerprint regardless; a fully manual browser session or credential-based apply is the fallback.)
2. **Mercedes:** provide Taleo login credentials to unlock the 15 strong-fit jobs.
3. **Infineon:** provide certificate/transcript documents for the doc-blocked jobs.
4. **SAP:** nothing — no Germany-located matches currently.

## Artifacts

- Bosch results: `1_BOSCH/results/*.json`, ledger `1_BOSCH/results/patient_apply_ledger.json`
- SAP fetcher: `SAP FETCHER/1_sap_job_fetcher.py` (v2 JSON-LD parser)
- Resume map: `resume_creation/program_files/output_v2/state/job_resume_map_bosch.csv`
- Engine tests: 114/114 passing; Bosch tests 8/8 passing.
