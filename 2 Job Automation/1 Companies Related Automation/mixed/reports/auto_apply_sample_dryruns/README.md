# Auto-application sample dry-run notes

This is a reusable troubleshooting/runbook location for the mixed application pipeline. The runner at [auto_apply_sample_dryrun.py](../../tools/auto_apply_sample_dryrun.py) invokes the registered application adapters with `dry_run=True`; it never sets submit mode. Run from `mixed/`:

```bash
python tools/auto_apply_sample_dryrun.py --company infineon
python tools/auto_apply_sample_dryrun.py --company sap
python tools/auto_apply_sample_dryrun.py --company mercedes
python tools/auto_apply_sample_dryrun.py --company bosch
python tools/auto_apply_sample_dryrun.py --all
```

Each invocation saves a timestamped `sample_run.json` plus portal screenshots/result output under `reports/auto_apply_sample_dryruns/<UTC run id>/<company>/`. A portal result other than `DRY_RUN` intentionally returns non-zero. Do not interpret a successful harness invocation as successful application validation unless the result says `DRY_RUN` and records the complete pre-submit stages.

## Session verification (2026-10-15)

| Company | Sample | Outcome | What was exercised / why it stopped |
|---|---|---|---|
| Infineon | Position `563808972143015`, Working Student - Sales & Marketing Strategy and Operations | `NEEDS_ATTENTION` | Eightfold application opened, tailored resume selected and uploaded, resume processing waited for, but contact fields remained blank (first name, last name, email, phone). No submit. Record: `20261015T105411Z/infineon/sample_run.json`. |
| SAP | `744000155471239`, Diploma Student / Intern - Business Transformation Intern | `NEEDS_ATTENTION` | The current `jobs.sap.com/en/jobs/...` page did not expose the expected “Apply now” link. The page saved `sap-744000155471239-result.json` and screenshot in the SAP results directory. No submit. Record: `20261015T105740Z/sap/sample_run.json`. |
| Mercedes-Benz | Historical MBTI Workday `R0006913` | `NEEDS_ATTENTION` on fresh smoke test; clean DRY_RUN historical | Sep 30 evidence reached Review with all fields validated. On Oct 15, the exact Workday portal search returned 0 jobs for R0006913, so this requisition appears closed/unavailable. The mixed current bundle `238227-J000238227` is a different public listing and cannot be passed to the Workday applier. No current Taleo run was made: recent Taleo jobs lack exact resume/letter bundle and credentials. |
| Bosch | `744000151829278`, internship in manufacturing planning/automated optical inspection | `CAPTCHA_DETECTED` | Bosch/SmartRecruiters redirects to its one-click form, but bot protection is detected at the application-opening stage. The automation stopped as designed; no attempt to bypass it and no submit. Record: `20261015T110411Z/bosch/sample_run.json` plus screenshot. |

## Known interface / output gaps

- The mixed adapter (`auto_apply/*_apply.py`) calls the sibling applier with URL and tailored resume. It accepts `letter_path` as bookkeeping, but currently the sibling portals do not upload the cover letter through the adapter path; `BaseApplier.apply_batch()` does not check bundle-file existence or complete-letter state.
- Mercedes `auto_apply/mercedes_apply.py` chooses the Workday applier for any non-Taleo URL; current public Mercedes job links can still route to Taleo through `custom_fields.apply_url`. The `mixed` current sample `238227` is not included in the latest fetched JSON, and the newer Taleo sample `241977` has no exact resume/letter bundle. Do not run either with stale/mismatched docs. Separate historical MBTI Workday requisition `R0006913` reached Review cleanly Sep 30, but the portal now returns 0 jobs; its clean evidence fixture is preserved at `mercedes/historical_workday_R0006913.json`.
- Current Hub maps are not uniformly complete/current: mixed SAP map has 19 entries, Infineon 25, Bosch 1, Mercedes 1. The Oct 14 Mercedes fetch contains newer job IDs that are not in the current mixed bundle. Its matching tailored cover-letter PDF is not available for the targeted fresh posting, so do not invent/substitute another job's letter.
- Additional company-specific notes: [Bosch topic](20261015T110411Z/bosch/topic.md), [Infineon topic](20261015T105411Z/infineon/topic.md), [SAP topic](20261015T105740Z/sap/topic.md), [Mercedes topic](mercedes/TOPIC.md), [immutable historical Workday fixture](mercedes/historical_workday_R0006913.json).
- External account credentials were not visible for Infineon, SmartRecruiters or Taleo in this run environment. Do not put credentials in source or result files. SAP credentials were present, but SAP was blocked before login.
- Existing user changes under the sibling company directories and the separate `resume_creation/` checkout are not owned by this sample harness; avoid overwriting or regenerating those outputs casually.

## Next-session protocol

1. Fetch current postings and apply the language/domain filters.
2. For each company, match the job ID to a per-job resume AND cover letter by exact source URL/ID; reject stale, score-parked, missing, or mismatched documents.
3. Check each company's result ledger / applied-job list before starting; skip confirmed SUCCESS jobs.
4. Use the correct portal route: SAP SuccessFactors; Infineon Eightfold; Bosch SmartRecruiters; Mercedes Taleo vs Workday based on the actual application URL.
5. Run a single dry-run. Continue only after a clean `DRY_RUN` that reaches the portal's last review/validation stage with all required fields/documents verified. A CAPTCHA, login wall, stale posting, blank contact field, unknown question, or validation error is a stop condition.
6. Keep the final submit button untouched unless the user gives a specific, current instruction to submit. This harness only supports steps 1-5.
