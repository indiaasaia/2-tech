"""
SAP Jobs Fetcher
----------------
Fetches all "werkstudent" jobs from jobs.sap.com with FULL details from each
job's own page and saves everything to sap_results.csv.

List pages:  https://jobs.sap.com/search/?q=werkstudent&startrow={0,25,50,75,...}
Detail page: each job's link (title, location, department, date, description, ...)

Use from anywhere (module name starts with a digit -> import via importlib):
    import importlib
    fetcher = importlib.import_module("1_sap_job_fetcher")
    jobs = fetcher.sap_job_fetcher()   # -> list of dicts, also written to CSV

Or run directly:
    python 1_sap_job_fetcher.py

Only the Python standard library is used.
"""

import csv
import html
import json
import re
import time
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path

BASE_URL = "https://careers.sap.com/search/?q=werkstudent&startrow={number}"
OUTPUT_CSV = Path(__file__).resolve().parent / "sap_results.csv"  # next to this script, CWD-independent
STEP = 25     # startrow steps: 0, 25, 50, ... (careers.sap.com paginates 25 per page)
DELAY = 1     # seconds between requests
TIMEOUT = 30  # request timeout in seconds

CSV_COLUMNS = [
    "Job Title", "Link", "Location", "Department", "Posted Date", "Job ID",
    "Requisition ID", "Category", "Employment Type", "Travel", "Description",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# --- List page: desktop job link (duplicate mobile markup is skipped) ---
JOB_PATTERN = re.compile(
    r'<span class="jobTitle hidden-phone">\s*'
    r'<a href="([^"]+)" class="jobTitle-link">(.*?)</a>',
    re.S,
)

# --- List page, 2026 layout: Next.js SPA, job anchors /en/jobs/<id>/<slug>/ ---
JOB_PATTERN_V2 = re.compile(r'href="(/en/jobs/\d+/[^"]+/)"[^>]*>([^<]+)<')

# --- Detail page: JSON-LD block (2026 layout; replaces the old
# data-careersite-propertyid markup that no longer renders) ---
LD_JSON_PATTERN = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.S)

# --- Detail page: property fields (meta content or tag text) ---
DETAIL_FIELDS = ["department", "facility", "date", "customfield3", "shifttype", "travel"]


def _get(url: str) -> str:
    """Download a URL. Raises RuntimeError with a clear message on any failure."""
    try:
        request = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status} for {url}")
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP error {e.code} for {url}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error for {url}: {e.reason}") from e
    except TimeoutError:
        raise RuntimeError(f"Timeout after {TIMEOUT}s for {url}") from None


def _clean(text: str) -> str:
    """Normalize extracted text: unescape entities, strip zero-width chars."""
    text = html.unescape(text)
    return text.replace("\u200b", " ").replace("\xa0", " ").strip()


def _html_to_text(html_chunk: str) -> str:
    """Convert an HTML chunk to plain readable text."""
    text = re.sub(r"<br\s*/?>", "\n", html_chunk)
    text = re.sub(r"</(p|div|li|ul|h\d)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"<[^>]*$", "", text)  # drop dangling cut-off tag at the end
    text = _clean(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))  # trim every line
    return re.sub(r"\n{2,}", "\n", text).strip()


def parse_list_page(page_html: str, base_url: str = BASE_URL) -> list[tuple[str, str]]:
    """Extract (title, link) pairs from one search results page.
    Tries the 2026 anchor layout first, then the legacy jobTitle markup."""
    jobs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for href, title in JOB_PATTERN_V2.findall(page_html):
        link = urllib.parse.urljoin(base_url, _clean(href))
        if link not in seen:
            seen.add(link)
            jobs.append((_clean(title), link))
    if jobs:
        return jobs
    for href, title in JOB_PATTERN.findall(page_html):
        title = _clean(title)
        link = urllib.parse.urljoin(base_url, _clean(href))
        if title:
            jobs.append((title, link))
    return jobs


def parse_detail_page(page_html: str) -> dict:
    """Extract all fields from one job detail page.

    2026 layout: the page is a Next.js SPA whose <head> carries a JSON-LD
    JobPosting block (title, description, employmentType, datePosted,
    jobLocation, identifier). Falls back to the legacy property-tag markup.
    """
    ld = LD_JSON_PATTERN.search(page_html)
    if ld:
        try:
            posting = json.loads(ld.group(1))
        except json.JSONDecodeError:
            posting = None
        if posting:
            ident = posting.get("identifier") or {}
            loc = posting.get("jobLocation") or {}
            if isinstance(loc, list):
                loc = loc[0] if loc else {}
            addr = (loc.get("address") or {}) if isinstance(loc, dict) else {}
            return {
                "location": _clean(addr.get("name") or loc.get("name", "") if isinstance(loc, dict) else ""),
                "department": "",
                "date": _clean(str(posting.get("datePosted", ""))),
                "facility": _clean(ident.get("value", "") if isinstance(ident, dict) else ""),
                "customfield3": "",
                "shifttype": _clean(str(posting.get("employmentType", ""))),
                "travel": "",
                "description": _html_to_text(posting.get("description", "")),
            }

    data = {}

    # Simple fields: <tag data-careersite-propertyid="x">value</tag>
    for field in DETAIL_FIELDS:
        m = re.search(
            r'data-careersite-propertyid="%s"[^>]*>(.*?)</' % field, page_html, re.S)
        data[field] = _clean(re.sub(r"<[^>]+>", " ", m.group(1))) if m else ""

    # Location: <p id="job-location"> <span class="jobGeoLocation">City, DE, ZIP
    m = re.search(r'id="job-location".*?<span class="jobGeoLocation">(.*?)<', page_html, re.S)
    data["location"] = _clean(m.group(1)) if m else ""

    # Description: everything between the description property tag and the
    # page footer block ("Requisition ID:" labels) that follows the body text
    start = page_html.find('data-careersite-propertyid="description"')
    if start != -1:
        start = page_html.find(">", start) + 1  # skip past the opening tag
    end = page_html.find("joblayouttoken-label", start)
    if end == -1:
        end = page_html.find('data-careersite-propertyid="facility"')
    if start != -1 and end != -1 and end > start:
        description = _html_to_text(page_html[start:end])
        # Drop the page footer line: ' Requisition ID: ... | Additional Locations: ... #LI-Hybrid'
        # (always present exactly once, as the last line of the body text)
        lines = description.split("\n")
        if lines and lines[-1].strip().startswith("Requisition ID:"):
            lines = lines[:-1]
        data["description"] = "\n".join(lines).strip()
    else:
        data["description"] = ""

    return data


def _extract_job_id(link: str) -> str:
    """Extract numeric Job ID from modern (/en/jobs/<id>/<slug>/) or legacy (/job/<slug>/<id>/) URLs."""
    url = link.rstrip("/")
    m = re.search(r"/jobs/(\d{6,})(?:/|$)", url, re.I)
    if m:
        return m.group(1)
    m = re.search(r"/(\d{6,})/?$", url)
    if m:
        return m.group(1)
    m = re.search(r"/(\d{6,})/", url)
    if m:
        return m.group(1)
    return url.split("/")[-1]


def _detail_record(title: str, link: str, detail: dict) -> dict:
    """Combine list + detail data into one CSV-ready record."""
    return {
        "Job Title": title,
        "Link": link,
        "Location": detail.get("location", ""),
        "Department": detail.get("department", ""),
        "Posted Date": detail.get("date", ""),
        "Job ID": _extract_job_id(link),
        "Requisition ID": detail.get("facility", ""),  # e.g. 459025
        "Category": detail.get("customfield3", ""),
        "Employment Type": detail.get("shifttype", ""),
        "Travel": detail.get("travel", ""),
        "Description": detail.get("description", ""),
    }


def _save_csv(jobs: list[dict]) -> None:
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(jobs)


def sap_job_fetcher() -> list[dict]:
    """Fetch ALL SAP 'werkstudent' jobs with full details, save to sap_results.csv.

    Returns:
        List of dicts with keys: Job Title, Link, Location, Department,
        Posted Date, Job ID, Category, Employment Type, Travel, Description.

    Raises:
        RuntimeError: if the site can't be reached, times out,
                      or returns no jobs (layout may have changed).
    """
    # 1) Collect all (title, link) from the paginated search list
    listings: list[tuple[str, str]] = []
    seen: set[str] = set()
    startrow = 0

    while True:
        page = _get(BASE_URL.format(number=startrow))
        new = [(t, l) for t, l in parse_list_page(page) if l not in seen]

        if startrow == 0 and not new:
            raise RuntimeError("No jobs found - site layout may have changed.")
        if not new:  # past the last page -> done
            break

        seen.update(l for _, l in new)
        listings.extend(new)
        print(f"startrow={startrow}: {len(new)} jobs (list total {len(listings)})")

        startrow += STEP
        time.sleep(DELAY)

    # 2) Visit each job page for full details
    records: list[dict] = []
    for i, (title, link) in enumerate(listings, 1):
        try:
            detail = parse_detail_page(_get(link))
            records.append(_detail_record(title, link, detail))
            print(f"[{i}/{len(listings)}] {title[:60]}")
        except RuntimeError as e:
            # One bad page must not kill the whole run
            print(f"[{i}/{len(listings)}] FAILED: {e}")
            records.append(_detail_record(title, link, {}))
        time.sleep(DELAY)

    _save_csv(records)
    return records


if __name__ == "__main__":
    try:
        import sys as _sys
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    try:
        result = sap_job_fetcher()
        print(f"\nDone! {len(result)} jobs with full details saved to {OUTPUT_CSV}")
    except RuntimeError as e:
        print(f"ERROR: {e}")
