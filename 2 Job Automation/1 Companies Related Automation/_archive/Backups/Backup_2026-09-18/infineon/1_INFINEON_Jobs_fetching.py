"""
1_INFINEON_Jobs_fetching.py
---------------------------
Fetches all Infineon "Werkstudent" jobs from the Eightfold-powered career
portal (jobs.infineon.com) end to end.

1. infineon_job_fetcher()      - pages the search API
                                 /api/pcsx/search?domain=infineon.com&query=werkstudent
                                 with start=0,10,20,30,... until a page returns
                                 no positions  ->  INFINEON_results.csv
2. enrich_jobs_with_details()  - opens every job page
                                 https://jobs.infineon.com/careers/job/<id>
                                 and extracts the embedded JSON-LD JobPosting
                                 (full description, dates, location, language)
                                  ->  INFINEON_jobs_detailed.csv (flat columns)
                                  ->  INFINEON_jobs_full.json    (everything incl. raw HTML)

The search API needs no cookies / CSRF token - plain GET works.
Job detail pages are server-rendered and contain a <script type="application/ld+json">
block of @type JobPosting with the complete description.

Usage:
    python 1_INFINEON_Jobs_fetching.py                 # full run (search + details)
    python 1_INFINEON_Jobs_fetching.py --no-details    # search list only
    python 1_INFINEON_Jobs_fetching.py --limit 5       # enrich only first 5 jobs

From other code:
    from importlib import import_module  # module name starts with a digit
    f = import_module("1_INFINEON_Jobs_fetching")
    jobs = f.infineon_job_fetcher()
    f.enrich_jobs_with_details(jobs)
"""

from __future__ import annotations

import argparse
import csv
import html as html_mod
import json
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any

import requests

SEARCH_URL = "https://jobs.infineon.com/api/pcsx/search"
DETAILS_API_URL = "https://jobs.infineon.com/api/pcsx/position_details"
JOB_PAGE_URL = "https://jobs.infineon.com/careers/job/{job_id}"

PAGE_SIZE = 10          # API returns 10 positions per page (start=0,10,20,...)
MAX_START = 10_000      # hard safety cap
REQUEST_RETRIES = 4     # transient-failure retries with linear backoff
REQUEST_TIMEOUT = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.8",
    "Referer": "https://jobs.infineon.com/careers?query=werkstudent&sort_by=relevance",
}

# flat CSV columns, in order
DETAIL_COLUMNS = [
    "title", "link", "job_id", "display_job_id", "company",
    "locations", "standardized_locations", "department", "work_location_option",
    "posted_date", "creation_date", "date_posted", "valid_through",
    "employment_type", "duration_of_employment", "join_as", "job_family",
    "in_language", "remote",
    "description_text", "apply_url",
]


# ------------------------------------------------------------------ transport
def _get_json(url: str, params: dict | None = None, referer: str | None = None) -> Any:
    """GET with retries + linear backoff; raises RuntimeError on final failure."""
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    last_exc: Exception | None = None
    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            if attempt < REQUEST_RETRIES:
                wait = 2 * attempt
                print(f"    [retry {attempt}/{REQUEST_RETRIES}] {exc} -> waiting {wait}s")
                time.sleep(wait)
    raise RuntimeError(f"GET {url} failed after {REQUEST_RETRIES} attempts: {last_exc}") from last_exc


def _get_text(url: str) -> str:
    """GET an HTML page with retries; raises RuntimeError on final failure."""
    last_exc: Exception | None = None
    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < REQUEST_RETRIES:
                wait = 2 * attempt
                print(f"    [retry {attempt}/{REQUEST_RETRIES}] {exc} -> waiting {wait}s")
                time.sleep(wait)
    raise RuntimeError(f"GET {url} failed after {REQUEST_RETRIES} attempts: {last_exc}") from last_exc


# ------------------------------------------------------------------ helpers
def _ts_to_iso(ts: Any) -> str:
    """Epoch seconds -> 'YYYY-MM-DD HH:MM:SS' (UTC). Empty on bad input."""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return ""


def _html_to_text(raw: str) -> str:
    """Minimal dependency-free HTML -> readable text for the flat CSV."""
    if not raw:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    text = re.sub(r"(?i)<\s*br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</\s*(p|div|li|h[1-6]|tr)\s*>", "\n", text)
    text = re.sub(r"(?i)<\s*li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n", text)
    return text.strip()


def _extract_jobposting(page_html: str) -> dict | None:
    """Pull the JSON-LD @type=JobPosting dict out of a job page, if present."""
    for match in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_html,
        re.S,
    ):
        try:
            data = json.loads(match.group(1).strip())
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return None


# ------------------------------------------------------------------ 1. search
def infineon_job_fetcher(output_csv: str = "INFINEON_results.csv") -> list[dict]:
    """Page the Eightfold search API start=0,10,20,... until an empty page.

    Returns one dict per job (title, link, job_id + all list metadata).
    Writes title+link CSV only after the full search succeeds.
    """
    jobs: list[dict] = []
    seen_ids: set[int] = set()

    for start in range(0, MAX_START + 1, PAGE_SIZE):
        payload = {
            "domain": "infineon.com",
            "query": "werkstudent",
            "location": "",
            "start": start,
            "sort_by": "relevance",
        }
        body = _get_json(SEARCH_URL, params=payload,
                         referer=f"https://jobs.infineon.com/careers?query=werkstudent&start={start}&sort_by=relevance")
        positions = ((body or {}).get("data") or {}).get("positions") or []
        if not positions:  # empty page = end of results (spec: stop here)
            print(f"[search] start={start}: 0 positions -> end of results")
            break
        new_count = 0
        for pos in positions:
            job_id = pos.get("id")
            if job_id is None or job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            jobs.append({
                "job_id": job_id,
                "title": (pos.get("name") or "").strip(),
                "link": JOB_PAGE_URL.format(job_id=job_id),
                "display_job_id": pos.get("displayJobId", ""),
                "ats_job_id": pos.get("atsJobId", ""),
                "locations": ", ".join(pos.get("locations") or []),
                "standardized_locations": ", ".join(pos.get("standardizedLocations") or []),
                "department": pos.get("department", ""),
                "posted_ts": pos.get("postedTs"),
                "posted_date": _ts_to_iso(pos.get("postedTs")),
                "creation_date": _ts_to_iso(pos.get("creationTs")),
                "is_hot": pos.get("isHot", 0),
                "work_location_option": pos.get("workLocationOption", ""),
            })
            new_count += 1
        print(f"[search] start={start}: {len(positions)} positions ({new_count} new) | total {len(jobs)}")
        time.sleep(0.4)  # polite pacing

    if not jobs:
        raise RuntimeError("Infineon search returned 0 jobs - aborting before writing CSVs")

    with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["title", "link"])
        writer.writeheader()
        writer.writerows({"title": j["title"], "link": j["link"]} for j in jobs)
    print(f"[search] saved {len(jobs)} jobs -> {output_csv}")
    return jobs


# ------------------------------------------------------------------ 2. details
def _fetch_position_details(job_id, hl: str = "en") -> dict:
    """Official Eightfold details API: /api/pcsx/position_details.

    Returns the inner `data` dict; raises RuntimeError on failure.
    """
    params = {"position_id": job_id, "domain": "infineon.com", "hl": hl}
    referer = f"https://jobs.infineon.com/careers?query=werkstudent&pid={job_id}&sort_by=relevance"
    body = _get_json(DETAILS_API_URL, params=params, referer=referer)
    data = (body or {}).get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"position_details returned unexpected body for {job_id}")
    return data


def _details_to_row(job: dict, d: dict, hl: str) -> dict:
    """Merge search-list metadata + official details API payload into one row."""
    def _join_list(v):
        return ", ".join(map(str, v)) if isinstance(v, list) else (v or "")

    return {
        **job,
        "apply_url": f"https://jobs.infineon.com/careers/apply?pid={job['job_id']}",
        "title": (d.get("name") or job["title"]).strip(),
        "display_job_id": d.get("displayJobId", job.get("display_job_id", "")),
        "locations": _join_list(d.get("locations")) or job.get("locations", ""),
        "standardized_locations": _join_list(d.get("standardizedLocations"))
                                  or job.get("standardized_locations", ""),
        "department": d.get("location", job.get("department", ""))
                      if isinstance(d.get("location"), str) and not d.get("location").strip("").isdigit()
                      else job.get("department", ""),
        "api_location": d.get("location", ""),
        "work_location_option": d.get("workLocationOption", job.get("work_location_option", "")),
        "location_flexibility": d.get("locationFlexibility", ""),
        "posted_date": _ts_to_iso(d.get("postedTs")) or job.get("posted_date", ""),
        "employment_type": _join_list(d.get("position.atsData.EmploymentType")),
        "duration_of_employment": _join_list(d.get("efcustomTextDurationOfEmployment")),
        "join_as": _join_list(d.get("efcustomTextJoinAs")),
        "job_family": _join_list(d.get("efcustomTextJobFamily")),
        "is_hot": d.get("isHot", job.get("is_hot", 0)),
        "stars": d.get("stars", ""),
        "jd_highlight": d.get("jdHighlight") or "",
        "public_url": d.get("publicUrl", ""),
        "position_user_actions": d.get("positionUserActions") or "",
        "details_language": hl,
        "description_html": d.get("jobDescription") or "",
        "description_text": _html_to_text(d.get("jobDescription") or ""),
        "description_source": "position_details_api",
    }


def _ld_to_row(job: dict, page_html: str) -> dict:
    """Fallback: JSON-LD JobPosting from the server-rendered job page."""
    posting = _extract_jobposting(page_html) or {}
    description_html = posting.get("description") or ""
    org = posting.get("hiringOrganization") or {}
    job_loc = posting.get("jobLocation") or []
    if not isinstance(job_loc, list):
        job_loc = [job_loc]
    location_names: list[str] = []
    for jl in job_loc:  # items may be dicts (PostalAddress) or plain strings
        if isinstance(jl, str):
            location_names.append(jl)
        elif isinstance(jl, dict):
            addr = jl.get("address") or {}
            if isinstance(addr, dict):
                parts = []
                for k in ("addressLocality", "addressRegion", "addressCountry"):
                    val = addr.get(k)
                    if isinstance(val, dict):  # e.g. {"@type": "Country", "name": "DE"}
                        val = val.get("name") or val.get("@id") or ""
                    if isinstance(val, str) and val.strip():
                        parts.append(val.strip())
                location_names.append(", ".join(parts))
            elif isinstance(addr, str):
                location_names.append(addr)
    locations_ld = ", ".join(loc for loc in location_names if loc).strip(", ")
    return {
        **job,
        "company": (org.get("name") or "Infineon").strip(),
        "date_posted": (posting.get("datePosted") or "").strip()[:10],
        "valid_through": (posting.get("validThrough") or "").strip()[:10],
        "employment_type": ", ".join(posting.get("employmentType") or [])
                           if isinstance(posting.get("employmentType"), list)
                           else (posting.get("employmentType") or ""),
        "in_language": (posting.get("inLanguage") or
                        (posting.get("inLanguage") or {}).get("@type") or ""),
        "ld_locations": locations_ld,
        "description_html": description_html,
        "description_text": _html_to_text(description_html),
        "description_source": "page_jsonld",
        "apply_url": f"https://jobs.infineon.com/careers/apply?pid={job['job_id']}",
    }


def enrich_jobs_with_details(jobs: list[dict],
                             detailed_csv: str = "INFINEON_jobs_detailed.csv",
                             full_json: str = "INFINEON_jobs_full.json",
                             hl: str = "en") -> list[dict]:
    """Fetch every job's data from the official position_details API and save
    ALL information (raw API payload + parsed fields + description).

    Falls back to the server-rendered page's JSON-LD JobPosting when the API
    fails, so a partial run still produces usable data. Writes the flat
    detailed CSV and the full JSON; returns the enriched list.
    """
    enriched: list[dict] = []
    failures = 0
    api_ok = 0
    ld_fallbacks = 0

    for i, job in enumerate(jobs, 1):
        job_id = job["job_id"]
        print(f"[detail {i}/{len(jobs)}] {job['title'][:70]}")
        try:
            details = _fetch_position_details(job_id, hl=hl)
            row = _details_to_row(job, details, hl)
            row["position_details_raw"] = details  # keep every API field
            api_ok += 1
        except RuntimeError as exc:
            print(f"    [api-fallback] {exc}")
            try:
                page_html = _get_text(job["link"])
                row = _ld_to_row(job, page_html)
                ld_fallbacks += 1
            except RuntimeError as exc2:
                failures += 1
                print(f"    FAILED: {exc2}")
                row = {**job, "description_text": "", "description_html": "",
                       "description_source": "none", "fetch_error": str(exc2)}
        enriched.append(row)
        time.sleep(0.3)  # polite pacing

    # flat CSV
    with open(detailed_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=DETAIL_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in enriched:
            writer.writerow({col: row.get(col, "") for col in DETAIL_COLUMNS})

    # full JSON (everything, incl. raw HTML)
    with open(full_json, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=1)

    print(f"[detail] enriched {len(enriched) - failures}/{len(enriched)} jobs "
          f"({failures} failures) | official API: {api_ok}, "
          f"JSON-LD fallback: {ld_fallbacks} -> {detailed_csv} + {full_json}")
    return enriched


# ------------------------------------------------------------------ CLI
def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Infineon Werkstudent jobs (Eightfold API).")
    parser.add_argument("--no-details", action="store_true",
                        help="only run the search list fetch, skip per-job enrichment")
    parser.add_argument("--limit", type=int, default=0,
                        help="enrich only the first N jobs (0 = all)")
    parser.add_argument("--hl", default="en", choices=["en", "de"],
                        help="description language for the details API (default: en)")
    args = parser.parse_args()

    jobs = infineon_job_fetcher()
    if not args.no_details:
        enrich_jobs_with_details(jobs[: args.limit] if args.limit > 0 else jobs, hl=args.hl)
    return 0


if __name__ == "__main__":
    sys.exit(main())
