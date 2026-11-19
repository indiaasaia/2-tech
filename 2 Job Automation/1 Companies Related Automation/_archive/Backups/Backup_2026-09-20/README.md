# resume_creation — shared V2 resume engine for ALL company folders

One central, verbatim copy of the proven V2 engine
(`resume_content_improve_research`, taken unchanged from
`E:\WorkSpace\2 Tech\JOB_AUTOMATION`) plus a thin connector layer that feeds
every company folder's job data into it. **The engine code itself is not
modified** — new companies are supported purely by mapping their job source
to the engine's input schema.

## Quick start

```bash
cd resume_creation

python run_resume_creation.py mercedes            # full run: prepare -> step4 -> step5
python run_resume_creation.py bmw --limit 2       # first 2 jobs only (smoke test)
python run_resume_creation.py mercedes --jobs 7440001   # job_url substring filter
python run_resume_creation.py mercedes --force    # re-run even gated_ok jobs
python run_resume_creation.py --list              # companies + resolved sources
python prepare_jobs_csv.py --list                 # mapping preview only (no LLM)
```

## Supported companies

| company    | folder          | phase coverage in own folder | source fed to engine |
|------------|-----------------|------------------------------|----------------------|
| bosch      | `bosch/`        | fetch + resume + apply       | filtered CSV **+ full fetch JSON (union)** |
| mercedes   | `mercedes/`     | fetch + resume + apply       | filtered CSV **+ full fetch JSON (union)** |
| infineon   | `infineon/`     | fetch + resume + apply       | filtered CSV **+ full fetch JSON (union)** |
| sap        | `SAP FETCHER/`  | fetch + resume + apply       | filtered CSV **+ full fetch CSV (union)** |
| bmw        | `bmw/`          | fetch only                   | `BMW_jobs_full.json` |
| simense    | `simense/`      | fetch only                   | `SIMENSE_jobs_full.json` |
| bwi        | `bwi/`          | fetch only                   | `BWI_jobs_full.json` |
| airbus     | `airbus/`       | fetch only                   | `AIRBUS_jobs_full.json` |
| simense_energy | `simense_energy/` | fetch only             | `SIMENSE_ENERGY_jobs_full.json` |

Adding a new company = one entry in `COMPANY_SOURCES` +
one small row-mapper function in `prepare_jobs_csv.py` (map its columns to
`job_url / title / company / job_description`).

## How it works

1. **prepare** (`prepare_jobs_csv.py`) — reads the company's job source(s) and
   writes the engine input: `program_files/output/2_filted_jobs.csv`.
   For bosch/mercedes/infineon/sap **all sources are unioned**: the jobs their
   own filter kept PLUS the full unfiltered fetch data — nothing is eliminated
   upfront, so the engine's domain gate applies its own (different) perspective
   to every job. Dedup is by normalized job_url (filtered rows load first).
2. **step 4** (`run_step4.run_pipeline`) — domain gate → analyst LLM →
   claimable set (KB-grounded) → constrained generation → pre-build gates.
   Resumable: `gated_ok` records are kept, parked ones retried.
3. **step 5** (`run_step5.main`) — fills the @@TOKEN@@ LaTeX template,
   compiles PDF via bundled `tools/tectonic.exe`, mirrors DOCX, parses the PDF
   back, runs post-build gates + scorecard, writes `resume_report.json` +
   `shortlist.json`.

Everything the engine needs travels with the package:
`sub_program_files/active_ollama_keys.json` (LLM key) and
`tools/tectonic.exe` (PDF compiler) — both resolved relative to this folder,
exactly as in the original project.

## Outputs

```
program_files/output_v2/
├── components_v2.json                  engine slot (current company's run)
├── resume_report.json / shortlist.json engine slot
├── resume/{tex,pdf,docx}/              current run's artifacts (cleared per run)
├── resume_<company>/{tex,pdf,docx}/    per-company snapshot after each run
└── state/
    ├── components_v2_<company>.json    persistent per-company components
    ├── resume_report_<company>.json
    └── shortlist_<company>.json
```

Per-company state isolation means runs for different companies never bleed
into each other: each run restores that company's components, keeps its
`gated_ok` results (no re-paid LLM calls), and snapshots its artifacts.

## Verification (2026-09-20)

- Engine integrity: `114/114` tests pass (`pytest resume_content_improve_research/tests`)
- Live end-to-end: mercedes 16 jobs → **15 verified** (1 parked by design) in ~110 s
- Fetch-only folder: bmw 88 jobs → domain gate kept 82 → verified builds work
- Engine package copied **byte-identical** (only `__pycache__` removed)
