# Bosch SmartRecruiters sample dry-run

- Sample: `744000151829278`, Praktikum – Fertigungsplanung – Automatisierte Optische Prüfung.
- Tailored bundle: score 32.9; resume and matching cover-letter PDFs exist in the current mixed output bundle. The sample currently has a recorded older FAILED result (`submitted: false`); this run did not modify that result.
- Current result: `CAPTCHA_DETECTED`, at stages `[job_page]`. SmartRecruiters redirected to a one-click application form; DataDome/bot protection stopped the flow before resume upload or fields.
- Safety outcome: the dry-run did not submit, and the automation did not bypass CAPTCHA. Do not retry unattended or repeatedly; only continue if a human can solve the challenge in the visible portal session and the result ledger is checked first.
- Reusable command from `mixed/`: `python tools/auto_apply_sample_dryrun.py --company bosch`.
- Artifact JSON: [sample_run.json](sample_run.json); result screenshot and structured portal evidence are linked in the JSON.
- Adapter limitation: `auto_apply/bosch_apply.py` forwards URL and resume, but the sibling CLI does not expose a cover-letter argument. `letter_path` is reported for traceability but is not uploaded by this bridge.
