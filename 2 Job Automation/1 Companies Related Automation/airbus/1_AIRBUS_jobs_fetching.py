"""
Airbus Jobs Fetcher (Workday CXS API)
-------------------------------------
Fetches all Airbus early-career jobs (internships / working students /
trainees / apprenticeships in Germany) from the Workday career site
ag.wd3.myworkdayjobs.com, then opens every job's CXS detail endpoint and
extracts the full posting (description HTML, dates, location, apply URL)
into CSV + JSON.

How the site works (reverse-engineered):
  * List:  POST /wday/cxs/ag/Airbus/jobs
           body: {appliedFacets:{workerSubType:[...], locationCountry:[...]},
                  limit:20, offset:N, searchText:""}
           -> {"total":169, "jobPostings":[{title, externalPath, ...}]}
           Paginate offset += limit until jobPostings is empty
           (or len(jobs) >= total).
  * Detail: GET /wday/cxs/ag/Airbus{externalPath}
           -> {"jobPostingInfo": {title, location, jobDescription(html),
              postedOn, startDate, timeType, externalUrl, ...}}
           (plain GET needs no cookies/CSRF — the browser uses POST only
           because the SPA talks to itself; the API accepts GET.)

Use:
    python 1_AIRBUS_jobs_fetching.py
    importlib.import_module("1_AIRBUS_jobs_fetching").AIRBUS_jobs_fetching()

Requires: requests   (pip install requests)
"""

from __future__ import annotations

import csv
import html as html_mod
import json
import random
import re
import sys
import time

import requests

# Windows consoles default to cp1252 and crash on special characters
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

TENANT, SITE = "ag", "Airbus"
BASE = f"https://{TENANT}.wd3.myworkdayjobs.com"
LIST_URL = f"{BASE}/wday/cxs/{TENANT}/{SITE}/jobs"
DETAIL_URL = f"{BASE}/wday/cxs/{TENANT}/{SITE}"
CAREER_URL = f"{BASE}/{SITE}"

# facets from the career-site URL the user browsed:
#   ?workerSubType=<intern/student>&workerSubType=<trainee/apprentice>&locationCountry=<germany>
WORKER_SUBTYPES = [
    "f5811cef9cb50193723ed01d470a6e15",   # internship / working student
    "f5811cef9cb501e1db34d41d470a6f15",   # trainee / apprenticeship
]
LOCATION_COUNTRIES = ["dcc5b7608d8644b3a93716604e78e995"]  # Germany

LIMIT = 20
DELAY = 1          # polite delay between requests, seconds
TIMEOUT = 30

OUTDIR = None  # set at import: folder of this script
from pathlib import Path
OUTDIR = Path(__file__).resolve().parent
CSV_PATH = OUTDIR / "AIRBUS_results.csv"
JSON_PATH = OUTDIR / "AIRBUS_jobs_full.json"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"),
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": BASE,
    "Referer": CAREER_URL,
    "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
}


def _clean(html_text: str) -> str:
    """Convert the job description HTML to readable plain text."""
    text = html_text or ""
    # preserve list/paragraph structure as newlines
    text = re.sub(r"(?i)<(br|/p|/li|/div|/h[1-6]|/tr)[^>]*>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "\n- ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ------------------------------------------------------------------ list
def fetch_all_job_links() -> list[dict]:
    """POST /jobs with offset 0,20,40... until an empty page comes back."""
    session = requests.Session()
    session.headers.update(HEADERS)

    jobs: dict[str, dict] = {}
    offset = 0
    total = None
    while True:
        payload = {
            "appliedFacets": {
                "workerSubType": WORKER_SUBTYPES,
                "locationCountry": LOCATION_COUNTRIES,
            },
            "limit": LIMIT,
            "offset": offset,
            "searchText": "",
        }
        r = _with_retry(lambda: session.post(LIST_URL, json=payload, timeout=TIMEOUT))
        data = r.json()
        total = data.get("total") or total
        postings = data.get("jobPostings", [])
        if not postings:
            break  # blank items -> end of pagination
        new = 0
        for p in postings:
            path = p.get("externalPath", "")
            url = f"{CAREER_URL}{path}"
            if url in jobs:
                continue
            jobs[url] = {
                "Title": p.get("title", ""),
                "Link": url,
                "externalPath": path,
                "Job_ID": (p.get("bulletFields") or [""])[0],
                "Location": p.get("locationsText", ""),
                "PostedOn": p.get("postedOn", ""),
            }
            new += 1
        print(f"[OFFSET {offset}] +{len(postings)} ({new} new) — total {len(jobs)}"
              + (f" / {total}" if total else ""))
        if new == 0:
            break
        offset += LIMIT
        time.sleep(DELAY + random.uniform(0, 0.5))

    print(f"[DONE] collected {len(jobs)} unique job links (advertised total: {total})")
    return list(jobs.values())


# --------------------------------------------------------------- detail
def _with_retry(send, tries: int = 4):
    """Retry wrapper: the site (Cloudflare/Workday) occasionally resets connections."""
    last_exc: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            return send()
        except (requests.RequestException, ConnectionError, TimeoutError) as exc:
            last_exc = exc
            wait = min(2 ** attempt + random.random(), 15)
            print(f"[RETRY {attempt}/{tries}] {type(exc).__name__}: {str(exc)[:90]} — waiting {wait:.1f}s")
            time.sleep(wait)
    raise last_exc  # type: ignore[misc]


def fetch_job_details(links: list[dict]) -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)
    out = []
    for i, job in enumerate(links, 1):
        if job.get("Description_Text") or job.get("fetch_error"):
            out.append(job)  # already fetched in a previous run (resumable)
            continue
        try:
            r = _with_retry(lambda: session.get(DETAIL_URL + job["externalPath"], timeout=TIMEOUT))
            info = r.json().get("jobPostingInfo", {})
            job.update({
                "Detail_Title": info.get("title", ""),
                "Location_Detail": info.get("location", ""),
                "Time_Type": info.get("timeType", ""),
                "Start_Date": info.get("startDate", ""),
                "Posted_On": info.get("postedOn", ""),
                "Apply_URL": info.get("externalUrl", ""),
                "Description_HTML": info.get("jobDescription", ""),
                "Description_Text": _clean(info.get("jobDescription", "")),
                "fetch_error": "",
            })
        except Exception as exc:  # noqa: BLE001
            job["fetch_error"] = f"{type(exc).__name__}: {exc}"
            print(f"[WARN] {job['Link']} -> {job['fetch_error'][:90]}")
        out.append(job)
        save(out)  # incremental save -> run can be resumed anytime
        print(f"[DETAIL {i}/{len(links)}] {job.get('Title', '')[:70]}")
        time.sleep(DELAY + random.uniform(0, 0.5))
    return out


# --------------------------------------------------------------- output
CSV_COLUMNS = ["Title", "Job_ID", "Link", "Location", "PostedOn",
               "Detail_Title", "Location_Detail", "Time_Type", "Start_Date",
               "Apply_URL", "Description_Text", "fetch_error"]


def save(jobs: list[dict]) -> None:
    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(jobs)
    JSON_PATH.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_existing() -> dict[str, dict]:
    if JSON_PATH.exists():
        try:
            jobs = json.loads(JSON_PATH.read_text(encoding="utf-8"))
            return {j["Link"]: j for j in jobs if j.get("Link")}
        except Exception:
            pass
    return {}


def AIRBUS_jobs_fetching() -> list[dict]:
    existing = _load_existing()
    links = fetch_all_job_links()
    if not links:
        print("[ABORT] no jobs found")
        return []
    for j in links:  # merge details from a previous partial run
        prev = existing.get(j["Link"])
        if prev and (prev.get("Description_Text") or prev.get("fetch_error")):
            j.update(prev)
    todo = sum(1 for j in links if not (j.get("Description_Text") or j.get("fetch_error")))
    print(f"[RESUME] {len(links) - todo}/{len(links)} already have details, {todo} to fetch")
    jobs = fetch_job_details(links)
    save(jobs)
    print(f"[SAVED] {CSV_PATH.name} + {JSON_PATH.name} ({len(jobs)} jobs)")
    return jobs


if __name__ == "__main__":
    AIRBUS_jobs_fetching()
