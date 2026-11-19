# SAP SuccessFactors sample dry-run

- Sample: job `744000155471239`, Diploma Student / Intern - Business Transformation Intern, tailored bundle score 68.0.
- Matching resume and cover-letter PDFs exist. SAP_EMAIL and SAP_PASSWORD were set in the environment, but the live run stopped before reaching authentication.
- Current outcome: `NEEDS_ATTENTION`, error `No 'Apply now' link found on the job page`. The old application helper expects a visible “Apply now” link and redirect into SuccessFactors. On Oct 14 the same current SAP job-page layout returned a “Just a moment...” challenge page; on Oct 15 this run again did not expose the expected link. This is a portal/browser challenge or current-site flow mismatch, not proof the user is ineligible.
- Never bypass a human verification challenge. The result does not reach form fields or the final review screen and must not be counted as a clean dry-run.
- There are many historical SAP SUCCESS result records. Before any next application, check the application ledger against the exact current numeric job ID; do not treat a fetched job's changing slug as a new requisition.
- Reusable command from `mixed/`: `python tools/auto_apply_sample_dryrun.py --company sap`.
- Artifact JSON: [sample_run.json](sample_run.json). The sibling result JSON and screenshot are written under `SAP FETCHER/results/`.
- The mixed adapter passes a per-job resume but does not upload the linked cover letter. SAP's job form has separate “My Documents” logic; inspect the actual required attachments on a clean portal load.
