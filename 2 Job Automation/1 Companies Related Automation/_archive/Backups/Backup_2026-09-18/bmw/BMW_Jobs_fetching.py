"""
BMW_Jobs_fetching.py

Fetches all BMW Group working-student jobs from bmwgroup.jobs and saves
the same way as the Bosch fetcher:

1. bmw_job_fetcher()              - pages through the BMW job-finder endpoint
                                    -> BMW_results.csv (title + link)
2. enrich_bmw_jobs_with_details() - opens every job detail page, extracts
                                    maximum information and saves:
                                      - BMW_jobs_detailed.csv (flat columns)
                                      - BMW_jobs_full.json    (everything incl. raw sections)

Endpoint used (exactly the one provided):
  .../jobfinder30_copy_cop.jobfinder_table.content.html
      ?textSearch=Werkstudent | Working Student
      &filterSearch=location_DE,jobType_INTERNSHIP
      &rowIndex=<offset>&blockCount=<page size>

NOTE: bmwgroup.jobs sits behind an Akamai CDN that black-holes plain
python-requests/curl TLS fingerprints. Transport therefore uses
curl_cffi with Chrome impersonation (pip install curl_cffi).

Usage from other code:
    from BMW_Jobs_fetching import bmw_job_fetcher, enrich_bmw_jobs_with_details
    jobs = bmw_job_fetcher()                       # -> BMW_results.csv
    enrich_bmw_jobs_with_details(jobs)             # -> detailed csv + json
"""

import csv
import json
import re
import sys
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from curl_cffi import requests as creq

LIST_URL = ("https://www.bmwgroup.jobs/de/de/studierende/werkstudententaetigkeit"
            "/_jcr_content/main/layoutcontainer_359813111/jobfinder30_copy_cop"
            ".jobfinder_table.content.html")
LIST_PARAMS = {
    "textSearch": "Werkstudent | Working Student",
    "filterSearch": "location_DE,jobType_INTERNSHIP",
}
DETAIL_URL = "https://www.bmwgroup.jobs/de/de/jobfinder/job-description.{job_id}.html"

PAGE_SIZE = 50          # jobs per list call (endpoint supports >=100)
MAX_PAGES = 20          # safety cap
REQUEST_TIMEOUT = 90    # BMW is slow; generous timeout
PAGE_DELAY = 0.5        # polite delay between calls

DETAIL_COLUMNS = [
    "title", "link", "source", "job_id", "ref_number", "company", "division",
    "position_type", "employment_type", "contract_type", "working_hours",
    "experience_level", "industry", "function", "language",
    "city", "region", "country", "address", "postal_code", "latitude", "longitude",
    "remote", "posting_date", "application_end", "released_date", "active",
    "recruiter", "start_info", "description_text", "custom_fields",
]


# ------------------------------------------------------------------ transport
def _http_get(url: str, params: dict | None = None) -> str:
    """GET via curl_cffi (Chrome TLS impersonation); returns response text."""
    resp = creq.get(url, params=params, impersonate="chrome",
                    timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def _fetch_with_retries(fn, retries: int = 2):
    """Run fn() with retries; re-raises the last error when all attempts fail."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception:
            if attempt == retries:
                raise
            time.sleep(2)


# ---------------------------------------------------------------- list fetch
def _parse_list_html(html: str) -> tuple[int, list[dict]]:
    """Parse one jobfinder page -> (total_count, jobs).

    Each job row carries data-job-id / data-job-title / data-job-location /
    data-job-legal-entity / data-job-field / data-posting-date / data-job-type
    and a link to /de/de/jobfinder/job-description.<id>.html.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find(class_="grp-jobfinder__table")
    total = int(table["data-counter"]) if table and table.has_attr("data-counter") else 0

    jobs = []
    for row in soup.find_all(class_="grp-jobfinder__wrapper"):
        anchor = row.find("a", href=True)
        ref = row.find(class_="grp-jobfinder-cell-refno")
        if not anchor or not ref:
            continue
        link = anchor["href"]
        if link.startswith("/"):
            link = "https://www.bmwgroup.jobs" + link
        jobs.append({
            "job_id": (ref.get("data-job-id") or row.get("data-job-id") or "").strip(),
            "title": (ref.get("data-job-title") or "").strip(),
            "link": link,
            "company": (ref.get("data-job-legal-entity") or "").strip(),
            "function": (ref.get("data-job-field") or "").strip(),
            "city": (ref.get("data-job-location") or "").strip(),
            "posting_date": (ref.get("data-posting-date") or "").strip(),
            "position_type": (ref.get("data-job-type") or "").strip(),
        })
    return total, jobs


def bmw_job_fetcher(output_csv: str = "BMW_results.csv") -> list[dict]:
    """Fetch all BMW working-student jobs, page by page, and write title+link CSV.

    Returns one dict per job: {"title", "link"} plus list metadata
    (job_id, company, function, city, posting_date, position_type).
    Raises RuntimeError on failure; CSV only written after full success.
    """
    jobs: list[dict] = []
    seen: set[str] = set()
    total = None

    try:
        for page in range(MAX_PAGES):
            params = {**LIST_PARAMS,
                      "rowIndex": page * PAGE_SIZE,
                      "blockCount": PAGE_SIZE}
            html = _fetch_with_retries(lambda: _http_get(LIST_URL, params))
            page_total, page_jobs = _parse_list_html(html)
            if total is None:
                total = page_total
                print(f"BMW reports {total} open positions; fetching in "
                      f"blocks of {PAGE_SIZE} ...")
            if not page_jobs:
                break
            for job in page_jobs:
                if job["link"] in seen or not job["title"]:
                    continue
                seen.add(job["link"])
                jobs.append(job)
            if total and len(jobs) >= total:
                break
            time.sleep(PAGE_DELAY)
    except Exception as exc:
        raise RuntimeError(f"BMW job-finder request failed: {exc}") from exc

    if total and len(jobs) < total:
        print(f"Warning: fetched {len(jobs)} of {total} reported positions.")

    try:
        with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["title", "link"])
            writer.writeheader()
            writer.writerows({"title": j["title"], "link": j["link"]} for j in jobs)
    except OSError as exc:
        raise RuntimeError(f"Could not write {output_csv}: {exc}") from exc

    return jobs


# ------------------------------------------------------------ detail helpers
def _clean_html(raw: str) -> str:
    """Decode entities, strip tags (keeping list bullets), squash whitespace."""
    text = re.sub(r"(?i)</li\s*>", " \u2022", raw or "")
    text = re.sub(r"(?i)<br\s*/?>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ").replace(chr(0xFFFD), "")
    text = text.replace("&amp;", "&")  # bs4 already unescapes; safety net
    return re.sub(r"\s+", " ", text).strip()


def _iso_date(value: str) -> str:
    """20260911 or 2026-09-11... -> YYYY-MM-DD."""
    value = str(value or "").strip()
    match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", value)
    if match:
        return "-".join(match.groups())
    match = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    return match.group(1) if match else ""


EMPLOYMENT_MAP = {"vollzeit": "Full-time", "teilzeit": "Part-time",
                  "vollzeit- oder teilzeitgeeignet": "Full-time/Part-time"}

# trailing boilerplate that can follow the Startdatum/Dauer/Arbeitszeit values
_BOILERPLATE = re.compile(
    r"(Hilfreiche Tipps|M\u00f6chtest du|Wir bei der BMW|Mehr dazu|"
    r"Bewirb dich|Chancengleichheit|Und vieles mehr)")


def _trim_kv(text: str, cap: int = 120) -> str:
    """Keep only the actual value of a key-value ad line (Startdatum etc.)."""
    text = _BOILERPLATE.split(text)[0].strip(" .|")
    if " \u2022 " in text:  # only the first bullet belongs to the value
        text = text.split(" \u2022 ")[0].strip()
    return text[:cap].strip()


def _split_description_sections(desc_html: str) -> dict[str, str]:
    """Split the ad HTML on <strong> markers -> {section label: plain text}.

    BMW ads use inline <strong> headers such as 'Was erwartet dich?',
    'Was bringst du mit?', 'Was bieten wir dir?', 'Startdatum:', ...
    """
    parts = re.split(r"<strong[^>]*>(.*?)</strong>", desc_html, flags=re.S)
    sections: dict[str, str] = {}
    intro = _clean_html(parts[0])
    if intro:
        sections["intro"] = intro
    for label, body in zip(parts[1::2], parts[2::2]):
        label = _clean_html(label).rstrip(":")
        text = _clean_html(body)
        if not text:
            continue
        if ("/" in label or label.startswith("http")) and sections:
            # bolded link text inside a section (e.g. 'jobs/waswirbieten'):
            # not a real section heading - merge into the previous one
            prev = next(reversed(sections))
            sections[prev] = f"{sections[prev]} {text}".strip()
            continue
        if label and text:
            sections[label] = text
    return sections


def _new_record(base: dict) -> dict:
    """Unified record seeded from list metadata (same schema as Bosch fetcher)."""
    return {
        "title": base.get("title", ""),
        "link": base.get("link", ""),
        "source": "bmw_jobfinder",
        "job_id": base.get("job_id", ""),
        "ref_number": base.get("job_id", ""),
        "company": base.get("company", ""),
        "division": "",
        "position_type": base.get("position_type", ""),
        "employment_type": "",
        "contract_type": "",
        "working_hours": "",
        "experience_level": "Student",
        "industry": "",
        "function": base.get("function", ""),
        "language": "",
        "city": base.get("city", ""),
        "region": "",
        "country": "Germany",
        "address": "",
        "postal_code": "",
        "latitude": "",
        "longitude": "",
        "remote": "",
        "posting_date": _iso_date(base.get("posting_date", "")),
        "application_end": "",
        "released_date": _iso_date(base.get("posting_date", "")),
        "active": "true",
        "recruiter": "",
        "start_info": "",
        "description_text": "",
        "custom_fields": "",
        "sections_raw": {},
    }


def _structure_detail(html: str, base: dict) -> dict:
    """Parse one job-description page (schema.org JobPosting) into a record."""
    soup = BeautifulSoup(html, "html.parser")

    container = soup.find(class_="jobdescription")
    if container is None:
        # BMW serves HTTP 200 with a 'not available any more' page for dead ids
        raise ValueError("job page has no posting data (position not available)")
    record = _new_record(base)

    itemprops = {}
    for el in container.find_all(attrs={"itemprop": True}):
        itemprops.setdefault(el["itemprop"], el)

    # title (h1) and organisation
    h1 = container.find(class_="cmp-title__text")
    if h1:
        record["title"] = h1.get_text(" ", strip=True)
    org = itemprops.get("hiringOrganization")
    if org:
        name = org.find(attrs={"itemprop": "name"})
        if name:
            record["company"] = name.get_text(" ", strip=True) or record["company"]

    # schema.org metadata
    record["job_id"] = (itemprops["identifier"].get_text(strip=True)
                        if "identifier" in itemprops else record["job_id"])
    record["ref_number"] = record["job_id"]
    record["industry"] = (itemprops["industry"].get_text(" ", strip=True)
                          if "industry" in itemprops else "")
    # the page has several employmentType itemprops; the readable one is
    # the last (others may render a java object dump) - prefer a known value
    emp_values = [el.get_text(" ", strip=True)
                  for el in container.find_all(attrs={"itemprop": "employmentType"})]
    emp = next((v for v in emp_values if EMPLOYMENT_MAP.get(v.strip().lower())),
               emp_values[-1] if emp_values else "")
    record["employment_type"] = EMPLOYMENT_MAP.get(emp.lower(), emp)
    loc = itemprops.get("addressLocality")
    if loc:
        record["city"] = loc.get_text(" ", strip=True) or record["city"]
    if "datePosted" in itemprops and not record["posting_date"]:
        record["posting_date"] = record["released_date"] = _iso_date(
            itemprops["datePosted"].get_text(strip=True))

    # description sections
    desc_el = itemprops.get("description")
    sections = _split_description_sections(str(desc_el.decode_contents())) if desc_el else {}
    record["sections_raw"] = sections
    record["description_text"] = "\n\n".join(
        f"[{label}] {text}" for label, text in sections.items())

    # start/duration/working-time line and working hours
    bits = []
    for key in ("Startdatum", "Dauer", "Arbeitszeit"):
        if key in sections:
            sections[key] = _trim_kv(sections[key])
            bits.append(f"{key}: {sections[key]}")
    record["start_info"] = " | ".join(bits)
    if "Arbeitszeit" in sections:
        record["working_hours"] = EMPLOYMENT_MAP.get(
            sections["Arbeitszeit"].lower(), sections["Arbeitszeit"])
    if not record["working_hours"] and record["employment_type"]:
        record["working_hours"] = record["employment_type"]
    if not record["employment_type"]:
        record["employment_type"] = record["working_hours"]

    record["custom_fields"] = json.dumps(
        {k: v for k, v in {
            "position_type": record["position_type"],
            "industry": record["industry"],
            "employment_type": record["employment_type"],
        }.items() if v}, ensure_ascii=False)
    return record


def fetch_job_details(link: str, base: dict | None = None, retries: int = 2) -> dict:
    """Fetch and structure all available data for one BMW job link.

    Never raises for a single bad job: returns a record with an 'error'
    note when the details failed.
    """
    base = base or {"title": "", "link": link}
    try:
        match = re.search(r"job-description\.(\d+)\.html", link or "")
        if not match:
            return {**_new_record(base), "error": "no BMW job id in link"}
        html = _fetch_with_retries(
            lambda: _http_get(DETAIL_URL.format(job_id=match.group(1))), retries)
        return _structure_detail(html, base)
    except Exception as exc:
        return {**_new_record(base), "error": str(exc)}


# ------------------------------------------------------------ enrich and save
def enrich_bmw_jobs_with_details(jobs: list[dict],
                                 output_csv: str = "BMW_jobs_detailed.csv",
                                 output_json: str = "BMW_jobs_full.json",
                                 delay: float = 0.5) -> tuple[list[dict], list[dict]]:
    """Fetch details for every job and save structured CSV + full JSON.

    Returns (records, failed). Raises RuntimeError only if nothing at
    all could be fetched. Files are written only after the run completes.
    """
    records: list[dict] = []
    failed: list[dict] = []

    for i, job in enumerate(jobs, 1):
        record = fetch_job_details(job.get("link", ""), job)
        (failed if "error" in record else records).append(record)
        if i % 10 == 0 or i == len(jobs):
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
        jobs = bmw_job_fetcher()
        print(f"Fetched {len(jobs)} job listings. Now opening every job page ...")
        records, failed = enrich_bmw_jobs_with_details(jobs)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
    print(f"Done: {len(records)} jobs fully detailed -> BMW_jobs_detailed.csv / BMW_jobs_full.json")
    if failed:
        print(f"Warning: {len(failed)} jobs could not be fetched:")
        for rec in failed:
            print(f"  - {rec.get('title', '')}: {rec['error'][:80]}")
