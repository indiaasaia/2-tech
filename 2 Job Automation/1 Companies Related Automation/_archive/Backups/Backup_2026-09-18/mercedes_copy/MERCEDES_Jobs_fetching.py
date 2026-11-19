"""
MERCEDES_Jobs_fetching.py

Fetches all Mercedes-Benz Werkstudent jobs in Germany and saves the same
way as the Bosch/BMW fetchers:

1. mercedes_job_fetcher()              - pages through the official jobs API
                                         (the endpoint behind jobs.mercedes-benz.com)
                                         -> MERCEDES_results.csv (title + link)
2. enrich_mercedes_jobs_with_details() - fetches each job's full data and saves:
                                           - MERCEDES_jobs_detailed.csv (flat columns)
                                           - MERCEDES_jobs_full.json    (everything)

Filters (exactly the ones from the provided URL):
  TargetGroup.Code=2, CareerLevel.Code=25, description contains
  "werkstudent", PositionLocation.Country=[329] (Germany).

The site is a Nuxt SPA whose search is a beesite API: a POST to
https://jobs.api.mercedes-benz.com/search with
  {"LanguageCode", "SearchParameters": {FirstItem, CountItem, Sort},
   "SearchCriteria": [{CriterionName, CriterionValue}]}
Query-string filters are ignored - only this POST applies them.

Usage from other code:
    from MERCEDES_Jobs_fetching import mercedes_job_fetcher, enrich_mercedes_jobs_with_details
    jobs = mercedes_job_fetcher()                    # -> MERCEDES_results.csv
    enrich_mercedes_jobs_with_details(jobs)          # -> detailed csv + json
"""

import csv
import html
import json
import re
import sys
import time
from datetime import datetime, timezone

import requests

SEARCH_URL = "https://jobs.api.mercedes-benz.com/search"
SEARCH_CRITERIA = [
    {"CriterionName": "TargetGroup.Code", "CriterionValue": ["2"]},
    {"CriterionName": "CareerLevel.Code", "CriterionValue": ["25"]},
    {"CriterionName": "PositionFormattedDescription.Content",
     "CriterionValue": ['"werkstudent"']},
    {"CriterionName": "PositionLocation.Country", "CriterionValue": ["329"]},
]
SORT = [{"Criterion": "PositionStartDateInitial", "Direction": "DESC"}]

PAGE_SIZE = 100         # jobs per search call
MAX_PAGES = 30          # safety cap
REQUEST_TIMEOUT = 40
PAGE_DELAY = 0.3

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

DETAIL_COLUMNS = [
    "title", "link", "source", "job_id", "ref_number", "company", "division",
    "position_type", "employment_type", "contract_type", "working_hours",
    "experience_level", "industry", "function", "language",
    "city", "region", "country", "address", "postal_code", "latitude", "longitude",
    "remote", "posting_date", "application_end", "released_date", "active",
    "recruiter", "start_info", "description_text", "custom_fields",
]

SCHEDULE_MAP = {"vollzeit": "Full-time", "teilzeit": "Part-time",
                "vollzeit (teilzeitgeeignet)": "Full-time/Part-time"}
CAREER_MAP = {
    "werkstudenten": "Working student", "praktikanten": "Intern",
    "praktikum": "Intern", "absolventen": "Graduate",
    "doktoranden": "PhD", "diplomanden": "Thesis", "masteranden": "Thesis",
    "studenten": "Working student",
}
LANGUAGE_MAP = {"1": "German", "2": "English"}


# ------------------------------------------------------------------ transport
def _search(first_item: int, count_item: int, extra_criteria: list | None = None) -> dict:
    """One beesite search POST; returns the raw SearchResult dict."""
    body = {
        "LanguageCode": "DE",
        "SearchParameters": {
            "FirstItem": first_item,
            "CountItem": count_item,
            "Sort": SORT,
        },
        "SearchCriteria": extra_criteria if extra_criteria is not None else SEARCH_CRITERIA,
    }
    resp = requests.post(SEARCH_URL, data=json.dumps(body), headers=HEADERS,
                         timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["SearchResult"]


def _fetch_with_retries(fn, retries: int = 2):
    """Run fn() with retries; re-raises the last error when all attempts fail."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except (requests.RequestException, ValueError):
            if attempt == retries:
                raise
            time.sleep(1)


# ------------------------------------------------------------- basic helpers
def _clean_html(raw: str) -> str:
    """Decode entities, strip tags (keeping list bullets), squash whitespace."""
    text = re.sub(r"(?i)</li\s*>", " \u2022", raw or "")
    text = re.sub(r"(?i)<br\s*/?>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ").replace(chr(0xFFFD), "")
    return re.sub(r"\s+", " ", text).strip()


def _new_record(base: dict) -> dict:
    """Unified record seeded from link/title (same schema as Bosch/BMW)."""
    return {
        "title": base.get("title", ""),
        "link": base.get("link", ""),
        "source": "mercedes_api_search",
        "job_id": base.get("job_id", ""),
        "ref_number": base.get("ref_number", ""),
        "company": base.get("company", ""),
        "division": "",
        "position_type": "",
        "employment_type": "",
        "contract_type": "",
        "working_hours": "",
        "experience_level": "Student",
        "industry": "",
        "function": "",
        "language": "",
        "city": "",
        "region": "",
        "country": "Germany",
        "address": "",
        "postal_code": "",
        "latitude": "",
        "longitude": "",
        "remote": "",
        "posting_date": "",
        "application_end": "",
        "released_date": "",
        "active": "true",
        "recruiter": "",
        "start_info": "",
        "description_text": "",
        "custom_fields": "",
        "sections_raw": {},
    }


def _structure_item(item: dict, base: dict) -> dict:
    """Flatten one MatchedObjectDescriptor into the unified record."""
    record = _new_record(base)

    locations = item.get("PositionLocation") or [{}]
    loc = locations[0]
    contacts = item.get("Contact") or [{}]
    contact = contacts[0]
    schedule = (item.get("PositionSchedule") or [{}])[0].get("Name", "")
    career = (item.get("CareerLevel") or [{}])[0].get("Name", "")
    category = (item.get("JobCategory") or [{}])[0].get("Name", "")
    language_code = str((item.get("PublicationLanguage") or {}).get("Code", ""))
    benefits = [re.sub(r"\s+", " ", b.get("Name", "")).strip()
                for b in (item.get("PositionBenefits") or []) if b.get("Name")]
    offering = ", ".join(o.get("Name", "") for o in (item.get("PositionOfferingType") or []))

    # description sections (Tasks / Qualifications / ...)
    sections = {key: _clean_html(val)
                for key, val in (item.get("PositionFormattedDescription") or [{}])[0].items()
                if val}
    description = "\n\n".join(f"[{key}] {text}" for key, text in sections.items())

    schedule_en = SCHEDULE_MAP.get(schedule.strip().lower(), schedule)
    career_en = CAREER_MAP.get(career.strip().lower(), career)

    record.update({
        "title": (item.get("PositionTitle") or record["title"]).strip(),
        "link": item.get("PositionURI") or record["link"],
        "job_id": str(item.get("ID", "")),
        "ref_number": item.get("PositionID", "") or str(item.get("ID", "")),
        "company": item.get("ParentOrganizationName", "") or record["company"],
        "division": item.get("DepartmentName", ""),
        "position_type": career_en,
        "employment_type": schedule_en,
        "contract_type": offering,
        "working_hours": schedule_en,
        "experience_level": career_en or "Student",
        "industry": "Automotive",
        "function": category,
        "language": LANGUAGE_MAP.get(language_code, ""),
        "city": loc.get("CityName", ""),
        "region": "" if loc.get("CountrySubDivisionName") in ("", "Deutschland")
                  else loc.get("CountrySubDivisionName", ""),
        "country": "Germany",  # filter guarantees PositionLocation.Country=329 (Germany)
        "address": loc.get("StreetName", ""),
        "postal_code": str(loc.get("PostalCode", "") or ""),
        "latitude": str(loc.get("Latitude", "") or ""),
        "longitude": str(loc.get("Longitude", "") or ""),
        "posting_date": item.get("PublicationStartDate", ""),
        "application_end": item.get("PublicationEndDate", ""),
        "released_date": item.get("PublicationStartDate", ""),
        "recruiter": (contact.get("Name", "").strip()
                      + (f" ({contact['Email']})" if contact.get("Email") else "")),
        "start_info": f"Start: {item.get('PositionStartDate', '')}"
                      if item.get("PositionStartDate") else "",
        "description_text": description,
        "sections_raw": sections,
        "custom_fields": json.dumps(
            {k: v for k, v in {
                "position_id": item.get("PositionID", ""),
                "organization": item.get("OrganizationName", ""),
                "remuneration": item.get("RemunerationDescription", ""),
                "benefits": benefits,
                "video": item.get("VideoUrl", ""),
                "apply_url": (item.get("ApplyURI") or [""])[0],
                "locations": [
                    {"city": l.get("CityName", ""), "postal_code": str(l.get("PostalCode", "") or "")}
                    for l in locations[1:]
                ],
            }.items() if v},
            ensure_ascii=False),
    })
    return record


# ---------------------------------------------------------------- list fetch
def mercedes_job_fetcher(output_csv: str = "MERCEDES_results.csv") -> list[dict]:
    """Fetch all Mercedes Werkstudent jobs (Germany) and write title + link CSV.

    Returns one dict per job: {"title", "link"} plus job_id/ref_number.
    Raises RuntimeError on failure; CSV only written after full success.
    """
    jobs: list[dict] = []
    seen: set[str] = set()
    total = None

    try:
        for page in range(MAX_PAGES):
            result = _fetch_with_retries(
                lambda: _search(page * PAGE_SIZE, PAGE_SIZE))
            total = result.get("SearchResultCountAll", total)
            items = result.get("SearchResultItems", [])
            if total and page == 0:
                print(f"Mercedes reports {total} matching jobs; fetching in "
                      f"blocks of {PAGE_SIZE} ...")
            if not items:
                break
            for it in items:
                m = it.get("MatchedObjectDescriptor", {})
                link = (m.get("PositionURI") or "").strip()
                title = (m.get("PositionTitle") or "").strip()
                if not link or link in seen or not title:
                    continue
                seen.add(link)
                jobs.append({
                    "title": title,
                    "link": link,
                    "job_id": str(m.get("ID", "")),
                    "ref_number": m.get("PositionID", ""),
                })
            if total and len(jobs) >= total:
                break
            time.sleep(PAGE_DELAY)
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"Mercedes search API request failed: {exc}") from exc

    if total and len(jobs) < total:
        print(f"Warning: fetched {len(jobs)} of {total} reported jobs.")

    try:
        with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["title", "link"])
            writer.writeheader()
            writer.writerows({"title": j["title"], "link": j["link"]} for j in jobs)
    except OSError as exc:
        raise RuntimeError(f"Could not write {output_csv}: {exc}") from exc

    return jobs


# ---------------------------------------------------------------- details API
def fetch_job_details(link: str, base: dict | None = None, retries: int = 2) -> dict:
    """Fetch and structure all available data for one Mercedes job link.

    Uses the same search API with an ID criterion (one POST per job).
    Never raises for a single bad job: returns a record with an 'error'
    note when the details failed.
    """
    base = base or {"title": "", "link": link}
    try:
        match = re.search(r"-(\d{6,})-[A-Z]{2}[A-Z0-9]+$", link or "") \
            or re.search(r"-(\d{6,})(?:-[A-Z0-9]+)?$", link or "")
        job_id = (base.get("job_id") or (match.group(1) if match else "")).strip()
        if not job_id:
            return {**_new_record(base), "error": "no Mercedes job id in link"}
        result = _fetch_with_retries(
            lambda: _search(0, 1, [{"CriterionName": "ID", "CriterionValue": [job_id]}]))
        items = result.get("SearchResultItems", [])
        if not items:
            return {**_new_record(base), "error": f"job {job_id} not found in API"}
        return _structure_item(items[0]["MatchedObjectDescriptor"], base)
    except (requests.RequestException, ValueError) as exc:
        return {**_new_record(base), "error": str(exc)}


# ------------------------------------------------------------ enrich and save
def enrich_mercedes_jobs_with_details(jobs: list[dict],
                                      output_csv: str = "MERCEDES_jobs_detailed.csv",
                                      output_json: str = "MERCEDES_jobs_full.json",
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

    try:
        with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=DETAIL_COLUMNS)
            writer.writeheader()
            for rec in records:
                writer.writerow({col: rec.get(col, "") for col in DETAIL_COLUMNS})
    except OSError as exc:
        raise RuntimeError(f"Could not write {output_csv}: {exc}") from exc

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
        jobs = mercedes_job_fetcher()
        print(f"Fetched {len(jobs)} job listings. Now fetching every job's full data ...")
        records, failed = enrich_mercedes_jobs_with_details(jobs)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
    print(f"Done: {len(records)} jobs fully detailed -> MERCEDES_jobs_detailed.csv / MERCEDES_jobs_full.json")
    if failed:
        print(f"Warning: {len(failed)} jobs could not be fetched:")
        for rec in failed:
            print(f"  - {rec.get('title', '')}: {rec['error'][:80]}")
