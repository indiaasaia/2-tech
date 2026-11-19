"""
BWI Jobs Fetcher
----------------
Fetches all open jobs from bwi.de via the site's own job_loader AJAX endpoint
(TYPO3 ext "bwi_joblist"), then opens every job's own page and extracts the
full details (description, requirements, contact, etc.) into CSV + JSON.

How the site works (reverse-engineered from Jobsearch.js):
  * The filter form POSTs to /karriere/stellenangebote/job_loader?...cHash=...
    with tx_bwi_joblist[page]=N (15 teasers per page; page counter 1-based).
  * Empty response body  ->  no more pages (_jobSearchMaxPageReached).
  * The loader URL/cHash comes embedded in the listing page HTML; we re-read
    it each run so we always use a fresh cHash.

Use:
    python 1_BWI_jobs_fetching.py            # fetch everything
    importlib.import_module("1_BWI_jobs_fetching").BWI_jobs_fetching()

Only the Python standard library is used.
"""

from __future__ import annotations

import csv
import html as html_mod
import json
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Windows consoles default to cp1252 and crash on U+202F etc. — force UTF-8 output
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

LISTING_URL = "https://www.bwi.de/karriere/stellenangebote"
BASE = "https://www.bwi.de"
PAGE_SIZE = 15
DELAY = 1          # polite delay between requests, seconds
TIMEOUT = 30

OUTDIR = Path(__file__).resolve().parent
CSV_PATH = OUTDIR / "BWI_results.csv"
JSON_PATH = OUTDIR / "BWI_jobs_full.json"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}


def _fetch_with_retry(send, tries: int = 4):
    """Run a request callable with retry/backoff; the site occasionally resets
    connections (WinError 10054). Retries with exponential backoff fix it."""
    last_exc: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            return send()
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            last_exc = exc
            wait = min(2 ** attempt + random.random(), 15)
            print(f"[RETRY {attempt}/{tries}] {type(exc).__name__}: {exc} — waiting {wait:.1f}s")
            time.sleep(wait)
    raise last_exc  # type: ignore[misc]


def _get(url: str, **kw) -> str:
    req = urllib.request.Request(url, headers={**HEADERS, **kw.pop("headers", {})})
    return _fetch_with_retry(lambda: _read(urllib.request.urlopen(req, timeout=TIMEOUT)))


def _read(resp) -> str:
    with resp:
        return resp.read().decode("utf-8", errors="replace")


def _post(url: str, data: dict) -> str:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"})
    return _fetch_with_retry(lambda: _read(urllib.request.urlopen(req, timeout=TIMEOUT)))


def _clean(text: str) -> str:
    text = html_mod.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------- list pages
def _loader_url_and_hidden_fields(listing_html: str) -> tuple[str, dict]:
    """Extract the job_loader action URL + required TYPO3 hidden fields from the filter form."""
    fstart = listing_html.find('name="filterForm"')
    if fstart == -1:
        raise RuntimeError("filterForm not found on listing page")
    fstart = listing_html.rfind("<form", 0, fstart)
    fend = listing_html.find("</form>", fstart)
    form = listing_html[fstart:fend]

    action = re.search(r'action="([^"]+)"', form).group(1)
    action = html_mod.unescape(action)
    if action.startswith("/"):
        action = BASE + action

    hidden: dict[str, str] = {}
    for m in re.finditer(r'<input[^>]*type="hidden"[^>]*>', form):
        tag = m.group(0)
        name = re.search(r'name="([^"]+)"', tag)
        value = re.search(r'value="([^"]*)"', tag)
        if name:
            hidden[name.group(1)] = html_mod.unescape(value.group(1)) if value else ""
    return action, hidden


def fetch_all_job_links() -> list[dict]:
    """Page through the job_loader until it returns an empty body."""
    listing_html = _get(LISTING_URL)
    action, hidden = _loader_url_and_hidden_fields(listing_html)
    print(f"[LOADER] {action}")

    # total count for progress display
    m = re.search(r'<div class="resultCount" data-value="(\d+)"', listing_html)
    total = int(m.group(1)) if m else None
    print(f"[INFO] advertised total jobs: {total}")

    jobs: dict[str, dict] = {}
    page = 1
    while True:
        data = dict(hidden)
        data["tx_bwi_joblist[page]"] = str(page)
        body = _post(action, data)
        teasers = re.findall(
            r'<a class="jobTeaserLink" href="([^"]+)".*?jobTeaserTitle[^>]*>\s*(.*?)\s*</div>.*?jobTeaserLocation[^>]*>\s*(.*?)\s*</div>',
            body, re.S)
        if not teasers:
            break  # max page reached
        new = 0
        for href, title, loc in teasers:
            url = BASE + href if href.startswith("/") else href
            if url in jobs:
                continue
            jobs[url] = {
                "Title": _clean(title),
                "Link": url,
                "Location": _clean(loc),
            }
            new += 1
        print(f"[PAGE {page}] {len(teasers)} teasers ({new} new) — total {len(jobs)}")
        if new == 0:
            break
        page += 1
        time.sleep(DELAY + random.uniform(0, 1))

    print(f"[DONE] collected {len(jobs)} unique job links (advertised: {total})")
    return list(jobs.values())


# ------------------------------------------------------------- detail pages
def _extract_detail(page_html: str) -> dict:
    fields: dict[str, str] = {}

    # title (h1)
    m = re.search(r"<h1[^>]*>(.*?)</h1>", page_html, re.S)
    fields["Detail_Title"] = _clean(m.group(1)) if m else ""

    # intro paragraph
    m = re.search(r"class=\"jobDetailIntro\"[^>]*>(.*?)</", page_html, re.S)
    fields["Intro"] = _clean(m.group(1)) if m else ""

    # the main job description region: grab everything between the intro
    # and the footer, as structured text
    m = re.search(r"<main[^>]*>(.*?)</main>", page_html, re.S) or \
        re.search(r"class=\"content\"[^>]*>(.*)", page_html, re.S)
    region = m.group(1) if m else page_html
    fields["Description_Text"] = _clean(region)

    # entry date / reference
    for label, pat in [
        ("Entry_Date", r"(Eintrittsdatum|Entry date|Einstiegsdatum)\s*[:</][^<]*<[^>]*>([^<]+)"),
        ("Reference", r"(Referenznummer|Reference|Job[\s-]?ID)\s*[:</][^<]*<[^>]*>([^<]+)"),
    ]:
        m = re.search(pat, page_html, re.I)
        fields[label] = _clean(m.group(2)) if m else ""

    # apply link
    m = re.search(r'href="(https?://[^"]*(?:bewerb|apply|karriere\.bwi-it)[^"]*)"', page_html, re.I)
    fields["Apply_URL"] = m.group(1) if m else ""

    # structured-data JSON (schema.org JobPosting) if present
    fields["JobPosting_JSON"] = ""
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', page_html, re.S):
        txt = _clean(m.group(1))
        if "JobPosting" in txt:
            fields["JobPosting_JSON"] = txt
            break

    return fields


def fetch_job_details(links: list[dict]) -> list[dict]:
    out = []
    for i, job in enumerate(links, 1):
        if job.get("Description_Text") or job.get("fetch_error"):
            out.append(job)  # already fetched in a previous run (resumable)
            continue
        try:
            page_html = _get(job["Link"])
            det = _extract_detail(page_html)
            job.update(det)
            job["fetch_error"] = ""
        except Exception as exc:  # noqa: BLE001
            job["fetch_error"] = f"{type(exc).__name__}: {exc}"
            print(f"[WARN] {job['Link']} -> {job['fetch_error']}")
        out.append(job)
        save(out)  # incremental save so the run can be resumed anytime
        print(f"[DETAIL {i}/{len(links)}] {job['Title'][:70]}")
        time.sleep(DELAY + random.uniform(0, 1))
    return out


# ------------------------------------------------------------------- output
CSV_COLUMNS = ["Title", "Link", "Location", "Detail_Title", "Intro",
               "Entry_Date", "Reference", "Apply_URL", "Description_Text",
               "JobPosting_JSON", "fetch_error"]


def save(jobs: list[dict]) -> None:
    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(jobs)
    JSON_PATH.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SAVED] {CSV_PATH.name} + {JSON_PATH.name} ({len(jobs)} jobs)")


def _load_existing() -> dict[str, dict]:
    """Load a previous partial run so fetching resumes where it stopped."""
    if JSON_PATH.exists():
        try:
            jobs = json.loads(JSON_PATH.read_text(encoding="utf-8"))
            return {j["Link"]: j for j in jobs if j.get("Link")}
        except Exception:
            pass
    return {}


def BWI_jobs_fetching() -> list[dict]:
    existing = _load_existing()
    links = fetch_all_job_links()
    if not links:
        print("[ABORT] no jobs found")
        return []
    # merge: keep details already fetched in earlier runs
    for j in links:
        prev = existing.get(j["Link"])
        if prev and (prev.get("Description_Text") or prev.get("fetch_error")):
            j.update(prev)
    todo = sum(1 for j in links if not (j.get("Description_Text") or j.get("fetch_error")))
    print(f"[RESUME] {len(links) - todo}/{len(links)} already have details, {todo} to fetch")
    jobs = fetch_job_details(links)
    save(jobs)
    return jobs


if __name__ == "__main__":
    BWI_jobs_fetching()
