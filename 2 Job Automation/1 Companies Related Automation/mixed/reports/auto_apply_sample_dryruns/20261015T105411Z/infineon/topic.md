# Infineon Eightfold sample dry-run

- Sample: position `563808972143015`, Working Student - Sales & Marketing Strategy and Operations (f/m/div), bundle score 77.3.
- Matching resume and cover-letter PDFs were verified present; the resume was passed to the portal automation.
- Current outcome: `NEEDS_ATTENTION`. The application opened, cookie banner was handled, resume input upload and confirmation were reached, and the resume-processing wait ran. Contact autofill then returned blank for first name, last name, email and phone, so the automation stopped before filling remaining questions and before submit.
- This is not a clean dry-run. Do not mark this job application-ready or continue by filling private profile data blindly; inspect the current Eightfold form and candidate configuration in a supervised session. Treat a missing/failed resume parser or form-specific contact IDs as the likely areas to diagnose.
- No apply click/submit was made after validation failure. Existing sibling result now has this job's NEEDS_ATTENTION evidence and screenshots.
- Reusable command from `mixed/`: `python tools/auto_apply_sample_dryrun.py --company infineon`.
- Artifact JSON: [sample_run.json](sample_run.json).
- The adapter accepts a cover letter path but the Infineon portal implementation uploads only the resume in this flow; verify whether the posting requests a separate letter or additional documents before any future application.
