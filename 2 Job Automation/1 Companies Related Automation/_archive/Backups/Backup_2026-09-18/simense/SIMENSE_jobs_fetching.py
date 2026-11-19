"""
SIMENSE_jobs_fetching.py

Fetches all Siemens Germany jobs matching the provided search filters and
saves the same way as the Mercedes/Bosch/BMW fetchers:

1. siemens_job_fetcher()              - pages through the official search
                                        (jobs.siemens.com / Avature platform)
                                        -> SIMENSE_results.csv (title + link)
2. enrich_siemens_jobs_with_details() - fetches each job's detail page and saves:
                                          - SIMENSE_jobs_detailed.csv (flat columns)
                                          - SIMENSE_jobs_full.json    (everything)

Search URL (filters preserved exactly as provided):
  https://jobs.siemens.com/de_DE/externaljobs/SearchJobs/
    ?42386=%5B812132%5D&42386_format=17546
    &42390=%5B102154%2C102155%2C102156%5D&42390_format=17550
    &listFilterMode=1&folderRecordsPerPage=6

Pagination: folderOffset = (page_number - 1) * 6
  page 1 -> 0, page 2 -> 6, page 3 -> 12, ...

Usage from other code:
    from SIMENSE_jobs_fetching import siemens_job_fetcher, enrich_siemens_jobs_with_details
    jobs = siemens_job_fetcher()                    # -> SIMENSE_results.csv
    enrich_siemens_jobs_with_details(jobs)          # -> detailed csv + json
"""

import csv
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

BASE_URL = (
    "https://jobs.siemens.com/de_DE/externaljobs/SearchJobs/"
    "?42386=%5B812132%5D&42386_format=17546"
    "&42390=%5B102154%2C102155%2C102156%5D&42390_format=17550"
    "&listFilterMode=1&folderRecordsPerPage=6"
)

FOLDER_RECORDS_PER_PAGE = 6          # must match folderRecordsPerPage above
MAX_PAGES = 100                      # safety cap (151 jobs = 26 pages)
REQUEST_TIMEOUT = 30                 # seconds per HTTP request
RETRIES_PER_REQUEST = 3              # attempts per request before giving up
RETRY_BACKOFF = 2.0                  # seconds; doubles after each attempt
PAGE_DELAY = 1.5                     # seconds between search pages
DETAIL_DELAY = 0.8                   # seconds between detail requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
    "Connection": "keep-alive",
}

DETAIL_COLUMNS = [
    "job_title", "job_id", "location", "country", "state_or_region",
    "field_of_work", "job_detail_url", "source_page",
    "published_since", "organization", "company", "experience_level",
    "employment_type", "work_model", "contract_type", "locations",
    "apply_url", "description_text", "fetch_error",
]

# Detail-page field labels (German + English) -> normalized keys
DETAIL_FIELD_LABEL_MAP = {
    "job id": "job_id",
    "ver\u00f6ffentlicht seit": "published_since",
    "published since": "published_since",
    "organization": "organization",
    "unternehmen": "company",
    "company": "company",
    "t\u00e4tigkeitsbereich": "field_of_work_detail",
    "field of work": "field_of_work_detail",
    "erfahrungsniveau": "experience_level",
    "experience level": "experience_level",
    "besch\u00e4ftigungsart": "employment_type",
    "employment type": "employment_type",
    "arbeitsmodell": "work_model",
    "work model": "work_model",
    "vertragsart": "contract_type",
    "contract type": "contract_type",
    "standort(e)": "locations",
    "standorte": "locations",
    "location(s)": "locations",
    "beliebiger standort bei siemens in": "locations",
}

_TOTAL_RE = re.compile(r"(\d[\d.]*)\s*(?:\+)?\s*(?:Ergebnisse|results)", re.IGNORECASE)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("siemens_jobs")


class PageStructureError(RuntimeError):
    """Raised when the page HTML no longer matches the expected structure."""


# ------------------------------------------------------------------ transport
def _create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def _fetch_html(session: requests.Session, url: str) -> str:
    """GET url with timeout, retries and exponential backoff."""
    last_error: Optional[Exception] = None
    for attempt in range(1, RETRIES_PER_REQUEST + 1):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            last_error = exc
            wait = RETRY_BACKOFF * (2 ** (attempt - 1))
            log.warning("attempt %d/%d failed for %s (%s) - retrying in %.1fs",
                        attempt, RETRIES_PER_REQUEST, url, exc, wait)
            if attempt < RETRIES_PER_REQUEST:
                time.sleep(wait)
    raise RuntimeError(f"Failed to fetch {url} after {RETRIES_PER_REQUEST} attempts: {last_error}")


def _clean(text: Optional[str]) -> str:
    return " ".join(text.split()) if text else ""


def _label_key(text: str) -> str:
    return _clean(text).lower().rstrip(":")


# ---------------------------------------------------------------- search page
def _parse_total_results(soup: BeautifulSoup) -> Optional[int]:
    """Read the legend '1 - 6 von 152 Ergebnisse' -> 152 ('999+' -> 999)."""
    legend = soup.select_one("div.list-controls__text__legend")
    if not legend:
        return None
    match = _TOTAL_RE.search(legend.get_text(" ", strip=True))
    if not match:
        return None
    return int(match.group(1).replace(".", "").replace(",", ""))


def parse_jobs(html: str) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Parse one search-results page -> (jobs, total_results).

    Raises PageStructureError if the results container exists but listings
    cannot be extracted (Siemens changed the markup) - fails clearly instead
    of silently returning an empty list.
    """
    soup = BeautifulSoup(html, "html.parser")
    total_results = _parse_total_results(soup)

    articles = soup.select("article.article--result")
    if not articles:
        if soup.select_one("div.section__content__results") is not None:
            return [], total_results           # genuine empty page
        raise PageStructureError(
            "No <article class='article--result'> and no results container "
            "found - Siemens HTML structure may have changed."
        )

    jobs: List[Dict[str, Any]] = []
    for article in articles:
        title_anchor = article.select_one("h3.article__header__text__title a[href]")
        detail_url = title_anchor.get("href", "").strip() if title_anchor else ""
        learn_more = article.select_one("a.button--primary[href]")
        if learn_more and not detail_url:
            detail_url = learn_more.get("href", "").strip()

        if not title_anchor or not detail_url:
            raise PageStructureError(
                "Job title anchor / detail URL not found inside an "
                "article--result - Siemens HTML structure may have changed."
            )

        def _sel(selector: str) -> str:
            el = article.select_one(selector)
            return _clean(el.get_text()) if el else ""

        job_id_raw = _sel(".list-item-jobId")
        jobs.append({
            "job_title": _clean(title_anchor.get_text()),
            "job_id": job_id_raw.split(":", 1)[-1].strip() or job_id_raw,
            "location": _sel(".list-item-jobCity")
                        or _sel(".list-item-location"),  # 'Mehrere Standorte'
            "country": _sel(".list-item-jobCountry"),
            "state_or_region": _sel(".list-item-jobState"),
            "field_of_work": _sel(".list-item-family"),
            "job_detail_url": detail_url,      # actual 'Learn more' href
        })
    return jobs, total_results


# ---------------------------------------------------------------- list fetch
def siemens_job_fetcher(output_csv: str = "SIMENSE_results.csv",
                        start_page: int = 1,
                        end_page: int = MAX_PAGES) -> List[Dict[str, Any]]:
    """Fetch all Siemens jobs for pages [start_page, end_page].

    Pagination is programmatic: folderOffset = (page_number - 1) * 6.
    Stops early when a page returns 0 jobs, repeats known IDs, or the
    reported total is reached. Jobs are deduplicated by job_id.

    Returns one dict per job (title, id, location, field_of_work, link, page).
    Raises RuntimeError when the search itself keeps failing.
    """
    if end_page < start_page:
        raise ValueError(f"end_page ({end_page}) must be >= start_page ({start_page})")

    jobs_by_id: Dict[str, Dict[str, Any]] = {}
    pages_processed = 0
    total_results: Optional[int] = None
    session = _create_session()

    try:
        for page_number in range(start_page, end_page + 1):
            offset = (page_number - 1) * FOLDER_RECORDS_PER_PAGE
            url = f"{BASE_URL}&folderOffset={offset}"
            log.info("Fetching page %d (folderOffset=%d)", page_number, offset)
            page_jobs, page_total = parse_jobs(_fetch_html(session, url))
            pages_processed += 1
            if page_total is not None:
                total_results = page_total

            new_ids = 0
            for job in page_jobs:
                if job["job_id"] not in jobs_by_id:
                    job["source_page"] = page_number
                    jobs_by_id[job["job_id"]] = job
                    new_ids += 1

            log.info("Page %d: %d jobs (%d new), running total %d, site reports %s",
                     page_number, len(page_jobs), new_ids,
                     len(jobs_by_id), total_results)

            if not page_jobs:
                log.info("Page %d returned 0 jobs - end of results.", page_number)
                break
            if new_ids == 0 and page_number > start_page:
                log.info("No new job IDs on page %d - end of results.", page_number)
                break
            if total_results is not None and len(jobs_by_id) >= total_results:
                log.info("Reached reported total of %s results.", total_results)
                break
            if page_number < end_page:
                time.sleep(PAGE_DELAY)
    finally:
        session.close()

    jobs = list(jobs_by_id.values())
    if total_results and len(jobs) < total_results:
        print(f"Warning: fetched {len(jobs)} of {total_results} reported jobs.")

    try:
        with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["job_title", "job_detail_url"])
            writer.writeheader()
            writer.writerows({"job_title": j["job_title"],
                              "job_detail_url": j["job_detail_url"]} for j in jobs)
    except OSError as exc:
        raise RuntimeError(f"Could not write {output_csv}: {exc}") from exc

    return jobs


# ---------------------------------------------------------------- details API
def parse_job_detail(html: str) -> Dict[str, Any]:
    """Parse a job detail page into a flat dict of extra fields.

    article.article--details #1 holds labeled key/value fields; #2 holds the
    full job description. Raises PageStructureError when containers are
    missing (e.g. posting removed or markup changed).
    """
    soup = BeautifulSoup(html, "html.parser")
    detail_articles = soup.select("article.article--details")
    if not detail_articles:
        raise PageStructureError(
            "No article.article--details found - detail page structure may "
            "have changed (or the job posting was removed)."
        )

    fields: Dict[str, Any] = {}
    for article in detail_articles:
        for block in article.select("div.article__content__view__field"):
            label_el = block.select_one(".article__content__view__field__label")
            value_el = block.select_one(".article__content__view__field__value")
            if not value_el:
                continue
            if label_el:
                key = DETAIL_FIELD_LABEL_MAP.get(_label_key(label_el.get_text()))
                if key is None:
                    continue  # unknown label - ignore
            else:
                key = "description"          # label-less block = description
            value = " ".join(value_el.stripped_strings)
            if key == "locations":
                locs = [_clean(li.get_text()) for li in value_el.select("li")]
                value = locs if locs else [_clean(value_el.get_text())]
            if value:
                fields[key] = value

    title_el = soup.select_one("h3.section__header__text__title")
    if title_el:
        fields["page_title"] = _clean(title_el.get_text())

    apply_anchor = soup.select_one("article.article--actions a[href]")
    if apply_anchor:
        fields["apply_url"] = apply_anchor.get("href", "").strip()

    if "description" not in fields:
        raise PageStructureError(
            "Job description block not found on detail page - structure may "
            "have changed."
        )
    return fields


def fetch_job_details(link: str, base: Optional[dict] = None) -> dict:
    """Fetch and structure all available data for one Siemens job link.

    Never raises for a single bad job: returns the listing fields plus a
    'fetch_error' note when the detail fetch failed.
    """
    base = base or {"job_title": "", "job_detail_url": link, "job_id": ""}
    record: Dict[str, Any] = {col: "" for col in DETAIL_COLUMNS}
    record.update({k: v for k, v in base.items() if k in record})
    record["country"] = record.get("country") or "Germany"
    try:
        extra = parse_job_detail(_fetch_html(_create_session(), link))
    except (RuntimeError, PageStructureError) as exc:
        record["fetch_error"] = str(exc)
        return record

    for key, value in extra.items():
        flat = value if isinstance(value, str) else "; ".join(value)
        if key == "job_id":
            record["job_id"] = record["job_id"] or str(value)
        elif key == "description":
            record["description_text"] = flat
        elif key in record:
            record[key] = flat
        elif key == "field_of_work_detail":
            record["field_of_work"] = record["field_of_work"] or flat
        # 'page_title' intentionally dropped (duplicate of job_title)
    return record


# ------------------------------------------------------------ enrich and save
def enrich_siemens_jobs_with_details(jobs: List[Dict[str, Any]],
                                     output_csv: str = "SIMENSE_jobs_detailed.csv",
                                     output_json: str = "SIMENSE_jobs_full.json",
                                     delay: float = DETAIL_DELAY
                                     ) -> Tuple[List[dict], List[dict]]:
    """Fetch details for every job and save structured CSV + full JSON.

    Returns (records, failed). Raises RuntimeError only if nothing at all
    could be fetched. Files are written only after the run completes.
    """
    records: List[dict] = []
    failed: List[dict] = []
    session = _create_session()

    try:
        for i, job in enumerate(jobs, 1):
            link = job.get("job_detail_url", "")
            record: Dict[str, Any] = {col: "" for col in DETAIL_COLUMNS}
            record.update({k: v for k, v in job.items() if k in record})
            record["country"] = record.get("country") or "Germany"
            try:
                extra = parse_job_detail(_fetch_html(session, link))
                for key, value in extra.items():
                    flat = value if isinstance(value, str) else "; ".join(value)
                    if key == "job_id":
                        record["job_id"] = record["job_id"] or str(value)
                    elif key == "description":
                        record["description_text"] = flat
                    elif key in record:
                        record[key] = flat
                    elif key == "field_of_work_detail":
                        record["field_of_work"] = record["field_of_work"] or flat
                records.append(record)
            except (RuntimeError, PageStructureError) as exc:
                record["fetch_error"] = str(exc)
                failed.append(record)
                log.error("Detail fetch failed for job %s: %s", job.get("job_id"), exc)
            if i % 25 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)} jobs fetched ({len(failed)} failed so far)")
            if i < len(jobs):
                time.sleep(delay)
    finally:
        session.close()

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
        jobs = siemens_job_fetcher()
        print(f"Fetched {len(jobs)} job listings. Now fetching every job's full data ...")
        records, failed = enrich_siemens_jobs_with_details(jobs)
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
    print(f"Done: {len(records)} jobs fully detailed -> "
          f"SIMENSE_jobs_detailed.csv / SIMENSE_jobs_full.json")
    if failed:
        print(f"Warning: {len(failed)} jobs could not be fetched:")
        for rec in failed:
            print(f"  - {rec.get('job_title', '')}: {rec['fetch_error'][:80]}")
