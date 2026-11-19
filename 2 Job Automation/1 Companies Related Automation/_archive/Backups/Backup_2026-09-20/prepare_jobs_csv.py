"""Universal connector: company job data -> engine input (2_filted_jobs.csv).

Maps each company folder's job sources onto the V2 engine's input schema
(job_url, title, company, job_description). For companies with their own
filter stage, ALL sources are UNIONED: their filtered CSV (jobs their own
filter kept) plus the full unfiltered fetch data — so nothing is eliminated
upfront; the engine's domain gate applies its own, different perspective.
Dedup is by normalized job_url; filtered-CSV rows are loaded first so their
(possibly richer) description text wins for overlapping jobs.

Usage (library):
    from prepare_jobs_csv import prepare, COMPANY_SOURCES, list_companies
    prepare("mercedes")                      # -> writes 2_filted_jobs.csv
    n = prepare("mercedes", force=True)      # re-map even if up to date
Usage (CLI):
    python prepare_jobs_csv.py mercedes bosch ...     # prepare selected companies
    python prepare_jobs_csv.py --list                 # show companies + sources
"""
from __future__ import annotations

import csv
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # resume_creation/
WORKSPACE = ROOT.parent                         # workspace root (company folders live here)
OUT_CSV = ROOT / "program_files" / "output" / "2_filted_jobs.csv"

CANDIDATE_EXTS = (".json", ".csv")

# ---------- per-company source configuration ----------
# Each entry: list of (relative path, loader name). ALL existing sources are
# UNIONED (dedup by normalized job_url, listed order = priority). For the
# end-to-end folders the filtered CSV comes first, the full fetch data second,
# so jobs their own filter eliminated still reach the engine's domain gate.
COMPANY_SOURCES: dict[str, list[tuple[str, str]]] = {
    # End-to-end folders (fetch -> filter -> resumes -> apply)
    "bosch":    [("bosch/program_files/output_bosch/2_filted_jobs.csv", "passthrough"),
                 ("bosch/BOSCH_jobs_full.json", "full_json")],
    "mercedes": [("mercedes/program_files/output_mercedes/2_filted_jobs.csv", "passthrough"),
                 ("mercedes/MERCEDES_jobs_full.json", "full_json")],
    "infineon": [("infineon/program_files/output_infineon/2_filted_jobs.csv", "passthrough"),
                 ("infineon/INFINEON_jobs_full.json", "full_json")],
    "sap":      [("SAP FETCHER/program_files/output_sap/2_filted_jobs.csv", "passthrough"),
                 ("SAP FETCHER/sap_results.csv", "sap_csv")],
    # Fetch-only folders (detailed enrichment already produced by their fetchers)
    "bmw":      [("bmw/BMW_jobs_full.json", "full_json")],
    "simense":  [("simense/SIMENSE_jobs_full.json", "simense_json")],
    # Additional fetch-only folders created later
    "bwi":      [("bwi/BWI_jobs_full.json", "bwi_json")],
    "airbus":   [("airbus/AIRBUS_jobs_full.json", "airbus_json")],
    "simense_energy": [("simense_energy/SIMENSE_ENERGY_jobs_full.json", "se_json")],
}


# ---------- helpers ----------
def _clean(text) -> str:
    return str(text or "").strip()


def _row(records: list[dict], key: str) -> dict[str, dict]:
    return {_clean(r.get(key)): r for r in records if _clean(r.get(key))}


def _join(*parts: str) -> str:
    return "\n\n".join(p for p in (_clean(x) for x in parts) if p)


def _norm_url(url: str) -> str:
    """Workday list URLs -> canonical detail URLs so resume/park state is stable."""
    url = _clean(url)
    if "myworkdayjobs.com" in url and "/job/" not in url:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        host = url.split("/wday/", 1)[0] if "/wday/" in url else url.split("/en/", 1)[0]
        return f"{host}/job/{slug}" if slug else url
    return url


# ---------- row mappers (company row -> engine schema) ----------
def _m_passthrough(row: dict) -> dict | None:
    if not _clean(row.get("job_description")):
        return None
    return {
        "job_url": _norm_url(_clean(row.get("job_url"))),
        "title": _clean(row.get("title")),
        "company": _clean(row.get("company")) or "Unknown",
        "job_description": _clean(row.get("job_description")),
    }


def _m_full_json(row: dict) -> dict | None:
    """Fetcher full-JSON rows (bosch/mercedes/infineon/bmw *_jobs_full.json)."""
    desc = _join(row.get("description_text"), row.get("start_info"))
    if not desc:
        return None
    return {
        "job_url": _norm_url(_clean(row.get("link") or row.get("job_url"))),
        "title": _clean(row.get("title")),
        "company": _clean(row.get("company")) or "Unknown",
        "job_description": desc,
    }


def _m_sap(row: dict) -> dict | None:
    desc = _clean(row.get("Description"))
    if not desc:
        return None
    return {
        "job_url": _norm_url(_clean(row.get("Link"))),
        "title": _clean(row.get("Job Title")),
        "company": _clean(row.get("company")) or "SAP",
        "job_description": desc,
    }


def _m_bmw(row: dict) -> dict | None:
    desc = _join(row.get("description_text"), row.get("start_info"))
    if not desc:
        return None
    return {
        "job_url": _clean(row.get("link") or row.get("job_url")),
        "title": _clean(row.get("title") or row.get("job_title")),
        "company": _clean(row.get("company")) or "BMW Group",
        "job_description": desc,
    }


def _m_simense(row: dict) -> dict | None:
    desc = _clean(row.get("description_text"))
    if not desc:
        return None
    return {
        "job_url": _clean(row.get("job_detail_url")),
        "title": _clean(row.get("job_title")),
        "company": _clean(row.get("company")) or "Siemens",
        "job_description": desc,
    }


def _m_bwi(row: dict) -> dict | None:
    desc = _join(row.get("Description_Text"), row.get("Intro"))
    if not desc:
        return None
    return {
        "job_url": _clean(row.get("Link") or row.get("Apply_URL")),
        "title": _clean(row.get("Detail_Title") or row.get("Title")),
        "company": "BWI GmbH",
        "job_description": desc,
    }


def _m_airbus(row: dict) -> dict | None:
    desc = _clean(row.get("Description_Text"))
    if not desc:
        return None
    return {
        "job_url": _clean(row.get("Link") or row.get("Apply_URL")),
        "title": _clean(row.get("Detail_Title") or row.get("Title")),
        "company": "Airbus",
        "job_description": desc,
    }


def _m_se(row: dict) -> dict | None:
    desc = _join(row.get("Description_Text"), row.get("Summary"))
    if not desc:
        return None
    return {
        "job_url": _clean(row.get("Link") or row.get("Apply_URL")),
        "title": _clean(row.get("Detail_Title") or row.get("Title")),
        "company": _clean(row.get("Company")) or "Siemens Energy",
        "job_description": desc,
    }


# JSON variant mappers reuse the CSV mappers (same key layout after json.load)
_MAPPERS = {
    "passthrough": _m_passthrough, "full_json": _m_full_json, "sap_csv": _m_sap,
    "simense_csv": _m_simense, "simense_json": _m_simense,
    "bwi_csv": _m_bwi, "bwi_json": _m_bwi,
    "airbus_csv": _m_airbus, "airbus_json": _m_airbus,
    "se_csv": _m_se, "se_json": _m_se,
}

# Engine input header (order matters only cosmetically; step 4 reads by name)
ENGINE_COLUMNS = ["job_url", "title", "company", "job_description"]


# ---------- source loading ----------
def _load_rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        data = __import__("json").loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):  # e.g. {"jobs": [...]}
            for value in data.values():
                if isinstance(value, list):
                    data = value
                    break
        if not isinstance(data, list):
            raise ValueError(f"unexpected JSON structure in {path}")
        return data
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
        return list(csv.DictReader(fh))


def _find_sources(company: str) -> list[tuple[Path, str]]:
    """All existing sources for a company, in priority order (union inputs)."""
    found = []
    for rel, loader in COMPANY_SOURCES.get(company, []):
        path = WORKSPACE / rel
        if path.exists() and path.stat().st_size > 0:
            found.append((path, loader))
    return found


# ---------- public API ----------
def list_companies() -> dict[str, str]:
    """company -> resolved source files (or '<missing>')."""
    result = {}
    for company in COMPANY_SOURCES:
        sources = _find_sources(company)
        result[company] = " + ".join(str(p.relative_to(WORKSPACE)) for p, _ in sources) if sources else "<missing>"
    return result


def prepare(company: str, force: bool = False) -> int:
    """Write the engine input CSV for one company. Returns row count.

    Raises FileNotFoundError when the company has no usable source file and
    ValueError when the source exists but yields zero mappable rows.
    """
    if company not in COMPANY_SOURCES:
        raise ValueError(f"unknown company '{company}' — known: {', '.join(COMPANY_SOURCES)}")
    sources = _find_sources(company)
    if not sources:
        raise FileNotFoundError(
            f"{company}: no source file found — run its fetcher first "
            f"(tried: {', '.join(rel for rel, _ in COMPANY_SOURCES[company])})")

    # Union of all sources: filtered CSV first (priority), then the full fetch
    # data so jobs the company's own filter eliminated still reach the engine.
    mapped: list[dict] = []
    seen: set[str] = set()
    per_source: list[str] = []
    for source, loader in sources:
        count = 0
        for row in _load_rows(source):
            m = _MAPPERS[loader](row)
            if m and m["job_url"] and m["job_url"] not in seen:
                seen.add(m["job_url"])
                mapped.append(m)
                count += 1
        per_source.append(f"{source.relative_to(WORKSPACE)}: {count} new")

    if not mapped:
        raise ValueError(f"{company}: sources {per_source} yielded 0 rows with a job_description")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    if OUT_CSV.exists() and force:
        backup = OUT_CSV.with_name("2_filted_jobs.prev.csv")
        shutil.move(str(OUT_CSV), str(backup))
    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=ENGINE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(mapped)

    print(f"[prepare] {company}: {len(mapped)} job(s) (union, nothing eliminated): " + " | ".join(per_source))
    return len(mapped)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or "--list" in argv:
        print("companies (source resolved):")
        for company, source in list_companies().items():
            print(f"  {company:15} {source}")
        return 0
    failures = 0
    for company in argv:
        if company.startswith("-"):
            continue
        try:
            prepare(company)
        except (FileNotFoundError, ValueError) as exc:
            failures += 1
            print(f"[prepare] {company}: FAILED — {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
