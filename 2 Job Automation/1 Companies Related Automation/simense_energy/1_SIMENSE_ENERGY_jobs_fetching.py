"""
Siemens Energy Jobs Fetcher (Avature portal)
--------------------------------------------
Fetches all Werkstudent/early-career jobs from the Siemens Energy career
portal (jobs.siemens-energy.com, Avature platform), then opens every job's
FolderDetail page and extracts the full details into CSV + JSON.

How the site works (reverse-engineered):
  * List:  GET /en_US/jobs/Jobs/?<filters>&listFilterMode=1
           &folderRecordsPerPage=20&folderOffset={0,20,40,...}
           Server-rendered HTML, 20 teasers per page. Each teaser links to
           /en_US/jobs/FolderDetail/<slug>/<id>. Page shows "N of 32 results".
           An empty page (no FolderDetail links) ends pagination.
  * Detail: GET /en_US/jobs/FolderDetail/<slug>/<id>
           Avature renders meta fields as field__label/field__value pairs
           (Job ID, Remote vs. Office, Company, Organization, Business Unit,
           Full/Part time, Experience Level) plus the description body,
           og:title, and an Apply link (Login?folderId=<id>).

Use:
    python 1_SIMENSE_ENERGY_jobs_fetching.py
    importlib.import_module("1_SIMENSE_ENERGY_jobs_fetching").SIMENSE_ENERGY_jobs_fetching()

Only the Python standard library is NOT enough here: the portal serves a
self-signed certificate in its chain, which urllib rejects but `requests`
(with certifi) accepts. So this fetcher uses `requests`.
"""

from __future__ import annotations

import csv
import html as html_mod
import json
import random
import re
import sys
import time
from pathlib import Path

import requests

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://jobs.siemens-energy.com"
# filters from the user's URL: 29454=964485 (career level), 29457=102154 (country/region)
LIST_URL = (BASE + "/en_US/jobs/Jobs/?29454=964485&29454_format=11381"
            "&29457=102154&29457_format=11384&listFilterMode=1"
            "&folderRecordsPerPage=20&folderOffset={offset}")
PER_PAGE = 20
DELAY = 1          # polite delay between requests, seconds
TIMEOUT = 30

OUTDIR = Path(__file__).resolve().parent
CSV_PATH = OUTDIR / "SIMENSE_ENERGY_results.csv"
JSON_PATH = OUTDIR / "SIMENSE_ENERGY_jobs_full.json"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
}


def _get(url: str) -> requests.Response:
    return requests.get(url, headers=HEADERS, timeout=TIMEOUT)


def _fetch_with_retry(url: str, tries: int = 4) -> str:
    last_exc: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            r = _get(url)
            r.raise_for_status()
            return r.text
        except (requests.RequestException, ConnectionError, TimeoutError) as exc:
            last_exc = exc
            wait = min(2 ** attempt + random.random(), 15)
            print(f"[RETRY {attempt}/{tries}] {type(exc).__name__}: {str(exc)[:90]} — waiting {wait:.1f}s")
            time.sleep(wait)
    raise last_exc  # type: ignore[misc]


def _clean(text: str) -> str:
    text = html_mod.unescape(text or "")
    text = re.sub(r"(?i)<(br|/p|/li|/div|/h[1-6]|/tr)[^>]*>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "\n- ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ------------------------------------------------------------------ list
def fetch_all_job_links() -> list[dict]:
    jobs: dict[str, dict] = {}
    offset = 0
    while True:
        url = LIST_URL.format(offset=offset)
        body = _fetch_with_retry(url)
        links = re.findall(
            r'href="(' + re.escape(BASE) + r'/en_US/jobs/FolderDetail/[^"]+)"', body)
        uniq = list(dict.fromkeys(links))
        if not uniq:
            break  # blank page -> end of pagination
        new = 0
        for link in uniq:
            if link in jobs:
                continue
            slug, rec_id = link.rsplit("/", 1)
            jobs[link] = {
                "Title": _clean(slug.rsplit("/", 1)[-1].replace("-", " ")),
                "Link": link,
                "Job_ID": rec_id,
            }
            new += 1
        print(f"[OFFSET {offset}] {len(uniq)} teasers ({new} new) — total {len(jobs)}")
        if new == 0:
            break
        offset += PER_PAGE
        time.sleep(DELAY + random.uniform(0, 0.5))

    print(f"[DONE] collected {len(jobs)} unique job links")
    return list(jobs.values())


# --------------------------------------------------------------- detail
def _extract_detail(page_html: str, url: str) -> dict:
    fields: dict[str, str] = {}

    # title (og:title is the cleanest on Avature pages)
    m = re.search(r'property="og:title" content="([^"]+)"', page_html)
    fields["Detail_Title"] = html_mod.unescape(m.group(1)) if m else ""

    # meta label/value pairs
    meta: dict[str, str] = {}
    for m in re.finditer(
            r'field__label[^>]*>\s*(.*?)\s*</\w+>(.*?)field__value[^>]*>(.*?)</div>',
            page_html, re.S):
        label = _clean(m.group(1))
        value = _clean(m.group(3))
        if label:
            meta[label] = value
    for label in ["Job ID", "Remote vs. Office", "Company", "Organization",
                  "Business Unit", "Full / Part time", "Experience Level"]:
        fields[label.replace(" ", "_").replace("/", "_").replace(".", "_")] = meta.get(label, "")

    # posted date from JSON-LD
    m = re.search(r'"@type":"JobPosting","title":"[^"]*","datePosted":"([^"]+)"', page_html)
    fields["Date_Posted"] = m.group(1) if m else ""

    # description: the article content field values (longest one wins)
    best = ""
    for m in re.finditer(r'article__content__view__field__value[^>]*>(.*?)</div>\s*(?=<div class="article__content__view__field|$)',
                         page_html, re.S):
        txt = m.group(1)
        if len(txt) > len(best):
            best = txt
    if not best:
        # fallback: capture the whole article content region
        i = page_html.find("article__content")
        j = page_html.find('id="relatedJobs"', i)
        best = page_html[i:j if j > 0 else i + 200000]
    fields["Description_HTML"] = best
    fields["Description_Text"] = _clean(best)

    # apply link
    m = re.search(r'href="([^"]*)"[^>]*>\s*Apply\s*<', page_html, re.I)
    fields["Apply_URL"] = html_mod.unescape(m.group(1)) if m else ""

    # og:description often carries location + employment type summary
    m = re.search(r'property="og:description" content="([^"]+)"', page_html)
    fields["Summary"] = _clean(html_mod.unescape(m.group(1))) if m else ""

    return fields


def fetch_job_details(links: list[dict]) -> list[dict]:
    out = []
    for i, job in enumerate(links, 1):
        if job.get("Description_Text") or job.get("fetch_error"):
            out.append(job)  # already fetched in a previous run (resumable)
            continue
        try:
            page_html = _fetch_with_retry(job["Link"])
            job.update(_extract_detail(page_html, job["Link"]))
            job["fetch_error"] = ""
        except Exception as exc:  # noqa: BLE001
            job["fetch_error"] = f"{type(exc).__name__}: {exc}"
            print(f"[WARN] {job['Link']} -> {job['fetch_error'][:90]}")
        out.append(job)
        save(out)  # incremental save -> run can be resumed anytime
        print(f"[DETAIL {i}/{len(links)}] {job.get('Title', '')[:70]}")
        time.sleep(DELAY + random.uniform(0, 0.5))
    return out


# --------------------------------------------------------------- output
CSV_COLUMNS = ["Job_ID", "Title", "Detail_Title", "Link", "Company",
               "Organization", "Business_Unit", "Remote_vs__Office",
               "Full___Part_time", "Experience_Level", "Date_Posted",
               "Apply_URL", "Summary", "Description_Text", "fetch_error"]


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


def SIMENSE_ENERGY_jobs_fetching() -> list[dict]:
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
    SIMENSE_ENERGY_jobs_fetching()
