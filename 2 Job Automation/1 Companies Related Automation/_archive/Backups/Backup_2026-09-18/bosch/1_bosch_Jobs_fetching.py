"""
1_bosch_Jobs_fetching.py

1. sap_job_fetcher()          - fetches all Bosch student jobs (title + link)
                                page by page -> BOSCH_results.csv
2. enrich_jobs_with_details() - opens every job link, extracts maximum
                                information per job and saves:
                                  - BOSCH_jobs_detailed.csv (flat columns)
                                  - BOSCH_jobs_full.json    (everything incl. raw sections)

Two kinds of job links exist (both fully handled):
  a) jobs.smartrecruiters.com/BoschGroup/<id>   -> data via the public
     SmartRecruiters posting API that powers the page
  b) jobs.bsh-group.de/<id>-<slug>              -> data via server-rendered
     HTML sections (data-multiposting-field) + Bosch list-API metadata

Usage from other code:
    from 1_bosch_Jobs_fetching import sap_job_fetcher, enrich_jobs_with_details
    jobs = sap_job_fetcher()                  # list page -> BOSCH_results.csv
    enrich_jobs_with_details(jobs)            # detail fetch -> csv + json
"""

import csv
import html
import json
import re
import sys
import time
from datetime import datetime, timezone

import requests

BASE_URL = (
    "https://jobs.bosch.de/api/filter/query"
    "?indexName=bosch_en&page={page}&q="
    "&filter=%257B%2522data.entryLevel%2522%253A%255B%2522data.entryLevel%253AStudent%2522%255D%257D"
)
DETAIL_URL = "https://api.smartrecruiters.com/v1/companies/BoschGroup/postings/{job_id}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "text/html,application/json",
}

# flat CSV columns, in order
DETAIL_COLUMNS = [
    "title", "link", "source", "job_id", "ref_number", "company", "division",
    "position_type", "employment_type", "contract_type", "working_hours",
    "experience_level", "industry", "function", "language",
    "city", "region", "country", "address", "postal_code", "latitude", "longitude", "remote",
    "posting_date", "application_end", "released_date", "active",
    "recruiter", "start_info", "description_text", "custom_fields",
]


# ---------------------------------------------------------------- list fetch
def sap_job_fetcher(output_csv: str = "BOSCH_results.csv") -> list[dict]:
    """Fetch all Bosch student jobs page by page and write title + link CSV.

    Returns one dict per job: {"title", "link"} plus all list-API metadata
    (company, city, division, contract, posting date, recruiter, ...).
    Raises RuntimeError on failure; CSV only written after full success.
    """
    jobs: list[dict] = []
    seen: set[str] = set()

    try:
        for page in range(1, 101):  # 100-page safety cap
            resp = requests.get(BASE_URL.format(page=page), headers=HEADERS, timeout=30)
            resp.raise_for_status()
            page_jobs = resp.json().get("jobs", [])
            if not page_jobs:  # empty page = end of results
                break
            for job in page_jobs:
                data = job.get("data", {})
                title = (data.get("title") or "").strip()
                link = (data.get("applicationUrl") or "").strip()
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                jobs.append({
                    "title": title,
                    "link": link,
                    "source": data.get("source", ""),
                    "job_number": data.get("jobNumber", ""),
                    "company": data.get("company", ""),
                    "business_unit": data.get("businessUnit", ""),
                    "position_type": data.get("positionType", ""),
                    "contract": data.get("contract", ""),
                    "remote": data.get("remote", ""),
                    "language": data.get("language", ""),
                    "job_field": ", ".join(data.get("jobField") or []),
                    "employment_type": ", ".join(data.get("employmentType") or []),
                    "city": data.get("city", ""),
                    "zip_code": data.get("zipCode", ""),
                    "state": data.get("state", ""),
                    "posting_date": data.get("postingDate", ""),
                    "application_end": data.get("applicationEnd", ""),
                    "latitude": str((job.get("_geoloc") or [{}])[0].get("lat", "") or ""),
                    "longitude": str((job.get("_geoloc") or [{}])[0].get("lng", "") or ""),
                    "recruiter_name": (data.get("recruiterData") or {}).get("name", ""),
                    "recruiter_email": (data.get("recruiterData") or {}).get("email", ""),
                })
    except requests.RequestException as exc:
        raise RuntimeError(f"Bosch API request failed: {exc}") from exc
    except ValueError as exc:  # invalid JSON
        raise RuntimeError(f"Bosch API returned invalid JSON: {exc}") from exc

    try:
        with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["title", "link"])
            writer.writeheader()
            writer.writerows({"title": j["title"], "link": j["link"]} for j in jobs)
    except OSError as exc:
        raise RuntimeError(f"Could not write {output_csv}: {exc}") from exc

    return jobs


# ------------------------------------------------------------- basic helpers
def _get(obj: dict, *keys, default=""):
    """Safely walk nested dict keys, e.g. _get(job, 'location', 'city')."""
    for key in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(key, default)
    return obj if obj is not None else default


def _clean_html(raw: str) -> str:
    """Decode entities first, strip tags (keeping list bullets), squash space."""
    text = raw or ""
    for _ in range(10):  # BSH stores entities encoded up to 5x deep
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    text = re.sub(r"(?i)</li\s*>", " \u2022", text)   # keep list structure
    text = re.sub(r"(?i)<br\s*/?>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ").replace(chr(0xFFFD), "")
    return re.sub(r"\s+", " ", text).strip()


# ------------------------------------------------------- normalization layer
POSITION_MAP = {
    "internship": "Intern", "student_employment": "Working student",
    "thesis": "Thesis", "premaster": "PreMaster",
}
CONTRACT_MAP = {
    "fixed-term": "Limited", "unlimited": "Unlimited",
    "unlimited or fixed-term": "Limited/Unlimited", "limited": "Limited",
}
REGION_MAP = {
    "bw": "Baden-Württemberg", "by": "Bavaria", "he": "Hessen",
    "nds": "Lower Saxony", "ni": "Lower Saxony", "be": "Berlin",
    "nrw": "North Rhine-Westphalia", "sn": "Saxony",
    "st": "Saxony-Anhalt", "th": "Thuringia",
    "mv": "Mecklenburg-Western Pomerania", "sh": "Schleswig-Holstein",
    "sl": "Saarland", "rp": "Rhineland-Palatinate", "hh": "Hamburg",
    "bb": "Brandenburg", "mittelfranken": "Bavaria",
    "baden-württemberg": "Baden-Württemberg", "bavaria": "Bavaria",
    "berlin": "Berlin", "saxony": "Saxony", "hessen": "Hessen",
    "lower saxony": "Lower Saxony", "north rhine-westphalia": "North Rhine-Westphalia",
    "saxony-anhalt": "Saxony-Anhalt", "thuringia": "Thuringia",
    "mecklenburg-western pomerania": "Mecklenburg-Western Pomerania",
    "schleswig-holstein": "Schleswig-Holstein", "saarland": "Saarland",
    "rhineland-palatinate": "Rhineland-Palatinate", "hamburg": "Hamburg",
    "brandenburg": "Brandenburg",
    "niedersachsen": "Lower Saxony", "sachsen": "Saxony",
    "nw": "North Rhine-Westphalia", "sa": "Saxony-Anhalt",
}
LANGUAGE_MAP = {"de": "German", "en": "English"}


def _iso_date(value: str) -> str:
    """Reduce any date string to a plain YYYY-MM-DD date."""
    match = re.match(r"(\d{4}-\d{2}-\d{2})", str(value or ""))
    return match.group(1) if match else ""


def _normalize_record(record: dict) -> dict:
    """Unify vocabulary, dates and small gaps so both sources align 1:1."""
    record["position_type"] = POSITION_MAP.get(
        record.get("position_type", "").strip().lower(),
        record.get("position_type", "").strip())
    record["contract_type"] = CONTRACT_MAP.get(
        record.get("contract_type", "").strip().lower(),
        record.get("contract_type", "").strip())
    record["region"] = REGION_MAP.get(
        record.get("region", "").strip().lower(),
        record.get("region", "").strip())
    record["language"] = LANGUAGE_MAP.get(
        record.get("language", "").strip().lower(),
        record.get("language", "").strip())
    record["experience_level"] = ("Student" if record.get("experience_level", "") == "Not Applicable"
                                  else record.get("experience_level", ""))
    # 'Intern' is not an employment type - fall back to the real working hours
    if record.get("employment_type", "") == "Intern":
        record["employment_type"] = record.get("working_hours", "")
    if not record.get("working_hours") and record.get("employment_type") in (
            "Full-time", "Part-time"):
        record["working_hours"] = record["employment_type"]
    for col in ("posting_date", "application_end", "released_date"):
        record[col] = _iso_date(record.get(col, ""))
    return record


def _new_record(base: dict) -> dict:
    """Start a unified record filled from Bosch list-API metadata."""
    return {
        "title": base.get("title", ""),
        "link": base.get("link", ""),
        "source": base.get("source", ""),
        "job_id": base.get("job_number", ""),
        "ref_number": base.get("job_number", ""),
        "company": base.get("company", ""),
        "division": base.get("business_unit", ""),
        "position_type": base.get("position_type", ""),
        "employment_type": base.get("employment_type", ""),
        "contract_type": base.get("contract", ""),
        "working_hours": "",
        "experience_level": "Student",
        "industry": "",
        "function": base.get("job_field", ""),
        "language": base.get("language", ""),
        "city": base.get("city", ""),
        "region": base.get("state", ""),
        "country": "Germany",
        "address": "",
        "postal_code": base.get("zip_code", ""),
        "latitude": str(base.get("latitude", "") or ""),
        "longitude": str(base.get("longitude", "") or ""),
        "remote": base.get("remote", ""),
        "posting_date": base.get("posting_date", ""),
        "application_end": base.get("application_end", ""),
        "released_date": base.get("posting_date", ""),
        "active": "true",
        "recruiter": (base.get("recruiter_name", "")
                      + (f" ({base['recruiter_email']})" if base.get("recruiter_email") else "")),
        "start_info": "",
        "description_text": "",
        "custom_fields": "",
        "sections_raw": {},
    }


# ---------------------------------------------------- type a) SmartRecruiters
def _structure_smartrecruiters(raw: dict, base: dict) -> dict:
    """Flatten one SmartRecruiters API posting into the unified record."""
    location = raw.get("location", {}) or {}
    fields = {c.get("fieldLabel"): c.get("valueLabel", "") for c in raw.get("customField", [])}

    sections = _get(raw, "jobAd", "sections", default={}) or {}
    description_text = "\n\n".join(
        f"[{sec.get('title', key)}] {_clean_html(sec.get('text', ''))}".strip()
        for key, sec in sections.items() if sec.get("text")
    )

    record = _new_record(base)
    record.update({
        "job_id": _get(raw, "id"),
        "ref_number": _get(raw, "refNumber"),
        "company": fields.get("Legal Entity") or fields.get("Legal Entity(acronym)") or record["company"],
        "division": fields.get("Division full name") or record["division"],
        "position_type": fields.get("Position type") or record["position_type"],
        "employment_type": _get(raw, "typeOfEmployment", "label") or record["employment_type"],
        "contract_type": fields.get("Contract type") or record["contract_type"],
        "working_hours": fields.get("Working hours", ""),
        "experience_level": _get(raw, "experienceLevel", "label"),
        "industry": _get(raw, "industry", "label"),
        "function": _get(raw, "function", "label") or record["function"],
        "language": _get(raw, "language", "label") or record["language"],
        "city": _get(location, "city") or record["city"],
        "region": _get(location, "region") or record["region"],
        "country": fields.get("Working Country") or fields.get("Country/Region") or record["country"],
        "address": _get(location, "address"),
        "postal_code": _get(location, "postalCode") or record["postal_code"],
        "latitude": _get(location, "latitude") or record["latitude"],
        "longitude": _get(location, "longitude") or record["longitude"],
        "remote": ("Remote/Hybrid" if _get(location, "remote") or _get(location, "hybrid")
                   else record["remote"]),
        "posting_date": _get(raw, "releasedDate") or record["posting_date"],
        "released_date": _get(raw, "releasedDate") or record["released_date"],
        "custom_fields": json.dumps(fields, ensure_ascii=False),
        "sections_raw": sections,
        "description_text": description_text or record["description_text"],
    })
    return record


# ----------------------------------------------------------- type b) BSH/HTML
def _bsh_job_url(link: str) -> str:
    """Convert an application link to the plain job page (job.html)."""
    url = re.sub(r"^https?://jobs\.bsh-group\.de/jobs/", "https://jobs.bsh-group.de/", link)
    url = re.sub(r"/job_application/new.*$", "/job.html", url)
    if not url.endswith("/job.html"):
        url = re.sub(r"/?$", "/job.html", url)
    return url


def _fetch_bsh_details(link: str, base: dict) -> dict:
    """Parse a BSH job page (server-rendered sections) into the unified record."""
    resp = requests.get(_bsh_job_url(link), headers=HEADERS, timeout=30)
    resp.raise_for_status()
    page = resp.text

    record = _new_record(base)
    sections: dict[str, dict] = {}

    # h1 title and the summary span: 'BSH Hausgeraete GmbH | Job-ID: 76047514 | Teilzeit | ab Februar 2027'
    h1 = re.search(r"<h1>(.*?)</h1>", page, re.S)
    if h1:
        record["title"] = _clean_html(h1.group(1))
    span = re.search(r"<span>([^<]*\|[^<]*)</span>", page)
    if span:
        parts = [p.strip() for p in html.unescape(span.group(1)).split("|") if p.strip()]
        for part in parts:
            if "Job-ID" in part:
                record["job_id"] = part.split(":")[-1].strip()
                record["ref_number"] = record["job_id"]
            elif "zeit" in part.lower():
                record["working_hours"] = part
            elif part.lower().startswith("ab "):
                record["start_info"] = part
        if parts:
            record["company"] = parts[0] if "Job-ID" not in parts[0] else record["company"]

    # fallback: BSH posting number from the URL when the page shows no Job-ID
    if not record["job_id"]:
        match = re.search(r"bsh-group\.de/(?:jobs/)?(\d+)", link)
        if match:
            record["job_id"] = record["ref_number"] = match.group(1)

    # content sections tagged with data-multiposting-field
    for key, body in re.findall(r'data-multiposting-field="([a-z_]+)"[^>]*>(.*?)</div>', page, re.S):
        inner_title = re.search(r"<h[23][^>]*>(.*?)</h[23]>", body, re.S)
        text = _clean_html(re.sub(r"<h[23][^>]*>.*?</h[23]>", " ", body, flags=re.S))
        if not text:
            continue
        label = _clean_html(inner_title.group(1)) if inner_title else key
        sections[key] = {"title": label, "text": text}

    description = "\n\n".join(
        f"[{sec['title']}] {sec['text']}" for sec in sections.values()
    )
    record.update({
        "sections_raw": sections,
        "description_text": description,
        "custom_fields": json.dumps({"company_description": sections.get("company_description", {}).get("text", "")},
                                    ensure_ascii=False),
    })
    return record


# ---------------------------------------------------------------- details API
def _fetch_with_retries(fn, retries: int):
    """Run fn() with retries; re-raises the last error when all attempts fail."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except (requests.RequestException, ValueError):
            if attempt == retries:
                raise
            time.sleep(1)


def _fetch_smartrecruiters_details(job_id: str) -> dict:
    """Call the SmartRecruiters posting API once and return parsed JSON."""
    resp = requests.get(DETAIL_URL.format(job_id=job_id), headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_job_details(link: str, base: dict | None = None, retries: int = 2) -> dict:
    """Fetch and structure all available data for one job link.

    Handles both SmartRecruiters and BSH links. Never raises for a single
    bad job: returns a record with an 'error' note when details failed.
    """
    base = base or {"title": "", "link": link}
    link = link or base.get("link", "")

    try:
        if "/BoschGroup/" in link:
            match = re.search(r"/BoschGroup/(\d+)", link)
            if not match:
                return {**_new_record(base), "error": "no SmartRecruiters job id in link"}
            raw = _fetch_with_retries(lambda: _fetch_smartrecruiters_details(match.group(1)),
                                      retries)
            return _normalize_record(_structure_smartrecruiters(raw, base))
        if "bsh-group.de" in link:
            return _fetch_with_retries(lambda: _normalize_record(
                _fetch_bsh_details(link, base)), retries)
        return {**_new_record(base), "error": "unknown link type"}
    except (requests.RequestException, ValueError) as exc:
        return {**_new_record(base), "error": str(exc)}


# ------------------------------------------------------------ enrich and save
def enrich_jobs_with_details(jobs: list[dict],
                             output_csv: str = "BOSCH_jobs_detailed.csv",
                             output_json: str = "BOSCH_jobs_full.json",
                             delay: float = 0.15) -> tuple[list[dict], list[dict]]:
    """Fetch details for every job and save structured CSV + full JSON.

    Returns (records, failed). Raises RuntimeError only if nothing at
    all could be fetched. Files are written only after the run completes.
    """
    records: list[dict] = []
    failed: list[dict] = []

    for i, job in enumerate(jobs, 1):
        record = fetch_job_details(job.get("link", ""), job)
        (failed if "error" in record else records).append(record)
        if i % 25 == 0 or i == len(jobs):
            print(f"  {i}/{len(jobs)} jobs fetched ({len(failed)} failed so far)")
        time.sleep(delay)

    if not records:
        raise RuntimeError(f"No job details could be fetched ({len(failed)} failures).")

    # flat CSV
    try:
        with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=DETAIL_COLUMNS)
            writer.writeheader()
            for rec in records:
                writer.writerow({col: rec.get(col, "") for col in DETAIL_COLUMNS})
    except OSError as exc:
        raise RuntimeError(f"Could not write {output_csv}: {exc}") from exc

    # full JSON (includes raw sections and the failed list)
    try:
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump({"fetched_at": datetime.now(timezone.utc).isoformat(),
                       "total": len(records), "failed": len(failed),
                       "jobs": records}, f, ensure_ascii=False, indent=1)
    except OSError as exc:
        raise RuntimeError(f"Could not write {output_json}: {exc}") from exc

    return records, failed


# ------------------------------------------------------------------- entry
if __name__ == "__main__":
    try:
        jobs = sap_job_fetcher()
        print(f"Fetched {len(jobs)} job listings. Now opening every job link ...")
        records, failed = enrich_jobs_with_details(jobs)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
    print(f"Done: {len(records)} jobs fully detailed -> BOSCH_jobs_detailed.csv / BOSCH_jobs_full.json")
    if failed:
        print(f"Warning: {len(failed)} jobs could not be fetched:")
        for rec in failed:
            print(f"  - {rec.get('title', '')}: {rec['error'][:80]}")
