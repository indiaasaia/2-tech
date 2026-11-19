# Mixed Job Automation Ecosystem

A unified, modular, and extensible pipeline combining:
1. **`job_fetcher/`**: Dedicated job fetchers & rule-based language filtering per company.
2. **`resume_and_cover_letter/`**: Shared V2 Engine based on `Regular` generating ATS-proof Resumes + DIN 5008 German & English Cover Letters (`Anschreiben`) + Application Bundles.
3. **`auto_apply/`**: Playwright browser automation engines for apply-capable corporate portals.
4. **`main.py`**: Central orchestrator allowing single-command runs for any company.

---

## 1. Directory Structure

```text
mixed/
├── main.py                              # Central pipeline orchestrator
├── README.md                            # Complete architecture & extension guide
│
├── job_fetcher/                         # All company scrapers & API fetchers
│   ├── __init__.py
│   ├── base.py                          # BaseJobFetcher & NormalizedJob dataclass
│   ├── registry.py                      # Dynamic company fetcher registry
│   ├── language_filter.py               # Shared proximity & negation language filter
│   ├── bosch.py                         # SmartRecruiters & Bosch list API
│   ├── mercedes.py                      # Mercedes-Benz API
│   ├── infineon.py                      # Eightfold AI API
│   ├── sap.py                           # SuccessFactors / Next.js SPA
│   ├── bmw.py                           # BMW Group (curl_cffi Akamai bypass)
│   ├── siemens.py                       # Siemens AG (Avature platform)
│   ├── siemens_energy.py                # Siemens Energy (Avature platform)
│   ├── bwi.py                           # BWI GmbH (TYPO3 AJAX)
│   └── airbus.py                        # Airbus (Workday CXS API)
│
├── resume_and_cover_letter/             # Resume & Cover Letter Hub (V2 Engine from Regular)
│   ├── prepare_jobs.py                  # Normalizes jobs into engine CSV (2_filted_jobs.csv)
│   ├── run_hub.py                       # Runs Steps 4 + 5 + 6 with per-company state isolation
│   ├── resume_content_improve_research/ # Core engine (analyst, generator, LaTeX, gates G1-G3, L1-L4)
│   ├── tools/tectonic.exe               # Bundled LaTeX engine (Tectonic 0.17.0)
│   ├── sub_program_files/               # Keys (active_ollama_keys.json, ollama_keys.json)
│   └── program_files/output_v2/
│       ├── state/                       # Per-company components, reports, maps
│       ├── resume_<company>/            # Tailored PDF & DOCX resumes per company
│       └── letters_<company>/           # Tailored DIN 5008 PDF, DOCX, & TXT cover letters
│
└── auto_apply/                          # Automated browser application bots (Playwright)
    ├── __init__.py
    ├── base.py                          # BaseApplier & ApplicationResult
    ├── registry.py                      # Applier registry with has_applier() detection
    ├── config/candidate.json            # Unified candidate application profile & answers
    ├── bosch_apply.py                   # SmartRecruiters shadow DOM + DataDome handling
    ├── mercedes_apply.py                # Workday & Taleo routing
    ├── infineon_apply.py                # Eightfold AI OneTrust + custom comboboxes
    └── sap_apply.py                     # SuccessFactors cascading picklists & skill chips
```

---

## 2. Supported Companies

| Company | Fetcher | Language Filter | Resume & Cover Letter | Auto-Apply | Portal Type |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **bosch** | ✅ `job_fetcher/bosch.py` | ✅ `ENGLISH_OK` | ✅ Resumes + Letters + Bundles | ✅ `auto_apply/bosch_apply.py` | SmartRecruiters |
| **mercedes** | ✅ `job_fetcher/mercedes.py` | ✅ `ENGLISH_OK` | ✅ Resumes + Letters + Bundles | ✅ `auto_apply/mercedes_apply.py` | Workday / Taleo |
| **infineon** | ✅ `job_fetcher/infineon.py` | ✅ `ENGLISH_OK` | ✅ Resumes + Letters + Bundles | ✅ `auto_apply/infineon_apply.py` | Eightfold |
| **sap** | ✅ `job_fetcher/sap.py` | ✅ `ENGLISH_OK` | ✅ Resumes + Letters + Bundles | ✅ `auto_apply/sap_apply.py` | SuccessFactors |
| **bmw** | ✅ `job_fetcher/bmw.py` | ✅ `ENGLISH_OK` | ✅ Resumes + Letters + Bundles | ❌ Fetch & Documents only | BMW Portal (Akamai) |
| **siemens** | ✅ `job_fetcher/siemens.py` | ✅ `ENGLISH_OK` | ✅ Resumes + Letters + Bundles | ❌ Fetch & Documents only | Avature |
| **siemens_energy** | ✅ `job_fetcher/siemens_energy.py` | ✅ `ENGLISH_OK` | ✅ Resumes + Letters + Bundles | ❌ Fetch & Documents only | Avature |
| **bwi** | ✅ `job_fetcher/bwi.py` | ✅ `ENGLISH_OK` | ✅ Resumes + Letters + Bundles | ❌ Fetch & Documents only | TYPO3 |
| **airbus** | ✅ `job_fetcher/airbus.py` | ✅ `ENGLISH_OK` | ✅ Resumes + Letters + Bundles | ❌ Fetch & Documents only | Workday CXS |

---

## 3. Quick Start & CLI Usage

### List all companies and capabilities
```powershell
python mixed/main.py --list
```

### Run complete pipeline for an apply-capable company
```powershell
# Runs Fetch -> Filter -> Resumes + Cover Letters -> Dry-run Apply
python mixed/main.py bosch --limit 2 --dry-run

# Real submission (requests typed confirmation before final submit)
python mixed/main.py mercedes --limit 1 --submit
```

### Run for a fetch-and-document company (BMW, Siemens, Airbus, etc.)
```powershell
# Automatically fetches jobs, filters language, builds tailored resumes and cover letters,
# and outputs verified PDF/DOCX files ready for manual application:
python mixed/main.py bmw --limit 3
```

### Targeted Flags
- `--limit N`: Restrict execution to the first $N$ jobs.
- `--jobs <substr>`: Substring filter on job URLs.
- `--skip-fetch`: Skip fetching and reuse existing cached job data.
- `--skip-resume`: Skip document generation and run apply only.
- `--skip-apply`: Skip auto-apply (fetch and create documents only).
- `--build-only`: Recompile PDF/DOCX from saved components without spending LLM tokens.
- `--force`: Force refresh for job fetching and LLM component generation.
- `--force-letters`: Force re-generation of cover letters.
- `--headless`: Run browser automation in headless mode.

---

## 4. How to Add a New Company

The architecture is **100% plug-and-play**. To add a new company (e.g. `porsche`):

### 1. Add the Job Fetcher
Create `mixed/job_fetcher/porsche.py`:
```python
from job_fetcher.base import BaseJobFetcher, NormalizedJob
from job_fetcher.language_filter import classify_text
from job_fetcher.registry import register_fetcher

@register_fetcher("porsche")
class PorscheJobFetcher(BaseJobFetcher):
    company_id = "porsche"
    display_name = "Porsche AG"
    portal_type = "Job Portal"

    def fetch_jobs(self, force: bool = False, limit: int | None = None) -> list[NormalizedJob]:
        # 1. Fetch raw jobs via requests/API/scraper
        # 2. Run classify_text(description) -> (language_filter, filter_evidence)
        # 3. Return list of NormalizedJob(...)
        ...
```

### 2. (Optional) Add the Auto-Applier
If the portal can be automated, create `mixed/auto_apply/porsche_apply.py`:
```python
from auto_apply.base import BaseApplier, ApplicationResult
from auto_apply.registry import register_applier

@register_applier("porsche")
class PorscheApplier(BaseApplier):
    company_id = "porsche"
    display_name = "Porsche AG"
    portal_name = "Porsche Careers"

    def apply_one(self, job_url, resume_path, letter_path=None, dry_run=True, **kwargs) -> ApplicationResult:
        # Implement Playwright walk: upload resume, cover letter, fill candidate data
        ...
```
*(If no auto-applier is added, the system automatically marks `porsche` as Fetch & Documents only and skips Stage 3 without error!)*

### 3. Run Immediately
```powershell
python mixed/main.py porsche --limit 2
```
Everything else (schema preparation, domain filtering, LLM analyst, ATS resume generation, DIN 5008 German & English cover letters, application bundling, and scorecard verification) works out of the box!
