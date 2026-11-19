"""Dedicated workingstudentjobs.de fetcher.

Scrapes job listings and full details strictly from workingstudentjobs.de.
Extracts title, company, location, datePosted, requirements, tasks, and description.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    cffi_requests = None

try:
    from . import config
except ImportError:
    import config

config.ensure_utf8_stdout()


class _HTMLDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.jsonld: list[str] = []
        self.text: list[str] = []
        self._script = False
        self._json_script = False
        self._script_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {k.lower(): v or "" for k, v in attrs}
        low = tag.lower()
        if low == "a" and attrs_map.get("href"):
            self.links.append(attrs_map["href"])
        if low == "script":
            self._script = True
            self._json_script = attrs_map.get("type", "").lower() == "application/ld+json"
            self._script_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script":
            if self._json_script:
                self.jsonld.append("".join(self._script_text))
            self._script = False
            self._json_script = False
            self._script_text = []

    def handle_data(self, data: str) -> None:
        if self._script:
            self._script_text.append(data)
        else:
            cleaned = re.sub(r"\s+", " ", unescape(data)).strip()
            if cleaned:
                self.text.append(cleaned)


def _http_get(url: str) -> str | None:
    """Execute HTTP GET with retries and browser impersonation."""
    for attempt in range(config.WSJ_RETRIES):
        try:
            if cffi_requests is not None:
                resp = cffi_requests.get(
                    url,
                    impersonate="chrome120",
                    headers={"Accept-Language": "en-US,en;q=0.9,de;q=0.8"},
                    timeout=config.WSJ_TIMEOUT_SECONDS,
                )
            else:
                resp = requests.get(
                    url,
                    headers={"User-Agent": config.WSJ_USER_AGENT, "Accept-Language": "en-US,en;q=0.9,de;q=0.8"},
                    timeout=config.WSJ_TIMEOUT_SECONDS,
                )
            if resp.ok or (resp.text and ("JobPosting" in resp.text or "<html" in resp.text)):
                return resp.text
            print(f"[WSJ-FETCHER] HTTP {resp.status_code}: {url}")
        except Exception as exc:
            print(f"[WSJ-FETCHER] Request attempt {attempt + 1} failed for {url}: {exc}")
        if attempt + 1 < config.WSJ_RETRIES:
            time.sleep(config.WSJ_DELAY_SECONDS * (attempt + 1))
    return None


def _is_job_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc.lower() not in {"www.workingstudentjobs.de", "workingstudentjobs.de"}:
        return False
    path = parsed.path.rstrip("/")
    if not path.startswith("/jobs/"):
        return False
    slug = path.removeprefix("/jobs/")
    return "/" not in slug and bool(re.search(r"-[0-9a-f]{8}$", slug, re.I))


def _walk_json_objects(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_objects(child)


def _extract_job_posting(parser: _HTMLDataParser) -> dict[str, Any] | None:
    for raw in parser.jsonld:
        try:
            val = json.loads(raw.strip())
        except (TypeError, json.JSONDecodeError):
            continue
        for obj in _walk_json_objects(val):
            types = obj.get("@type", [])
            types = types if isinstance(types, list) else [types]
            if "JobPosting" in types:
                return obj
    return None


def _clean_text(value: Any) -> str:
    if isinstance(value, str):
        value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
        value = re.sub(r"<[^>]+>", " ", unescape(value))
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, list):
        return "; ".join(x for x in (_clean_text(item) for item in value) if x)
    if isinstance(value, dict):
        return _clean_text(value.get("name") or value.get("value") or value.get("addressLocality") or "")
    return str(value or "").strip()


def _format_location(value: Any) -> str:
    if not isinstance(value, dict):
        return _clean_text(value)
    address = value.get("address") or value
    if not isinstance(address, dict):
        return _clean_text(address)
    parts = [
        _clean_text(address.get(k))
        for k in ("streetAddress", "postalCode", "addressLocality", "addressRegion", "addressCountry")
        if _clean_text(address.get(k))
    ]
    return ", ".join(parts)


def _title_from_slug(url: str) -> str:
    slug = urlparse(url).path.rstrip("/").split("/", 2)[-1]
    slug = re.sub(r"-[0-9a-f]{8}$", "", slug, flags=re.I)
    return slug.replace("-", " ").title()


def _blank_row(url: str) -> dict[str, str]:
    row = {col: "" for col in config.COMMON_COLUMNS}
    row.update({
        "source": "workingstudentjobs.de",
        "source_job_id": url.rsplit("-", 1)[-1],
        "job_url": url,
        "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    return row


def parse_job_detail(url: str, html_text: str) -> dict[str, str]:
    """Parse a single workingstudentjobs.de job detail page."""
    row = _blank_row(url)
    parser = _HTMLDataParser()
    parser.feed(html_text)
    job_ld = _extract_job_posting(parser)

    if job_ld:
        org = job_ld.get("hiringOrganization") or {}
        location = _format_location(job_ld.get("jobLocation"))
        description = _clean_text(job_ld.get("description"))
        requirements = _clean_text(job_ld.get("qualifications") or job_ld.get("experienceRequirements"))
        responsibilities = _clean_text(job_ld.get("responsibilities"))
        benefits = _clean_text(job_ld.get("jobBenefits") or job_ld.get("benefits"))
        company_name = _clean_text(org.get("name") if isinstance(org, dict) else org)
        company_url = _clean_text(org.get("url") if isinstance(org, dict) else "")

        row.update({
            "title": _clean_text(job_ld.get("title") or job_ld.get("headline")) or _title_from_slug(url),
            "company": company_name,
            "detail_company_name": company_name,
            "company_url": company_url,
            "location": location,
            "detail_location": location,
            "posted_time": _clean_text(job_ld.get("datePosted")),
            "detail_online_date": _clean_text(job_ld.get("datePosted")),
            "detail_contract_type": _clean_text(job_ld.get("employmentType")),
            "job_description": description,
            "requirements": requirements,
            "applicant_profile": requirements,
            "your_tasks": responsibilities,
            "what_they_offer": benefits,
            "we_offer": benefits,
            "predicted_salary": _clean_text(job_ld.get("baseSalary")),
            "details_fetched": "true" if description else "false",
        })
        if not description:
            row["detail_error"] = "JobPosting JSON-LD had empty description"
    else:
        visible = "\n".join(parser.text)
        row.update({
            "title": _title_from_slug(url),
            "job_description": visible[:10000],
            "your_tasks": visible[:10000],
            "details_fetched": "true" if visible else "false",
        })
        if not visible:
            row["detail_error"] = "No JSON-LD or text content extracted"

    if not row["title"]:
        row["title"] = _title_from_slug(url)
    if not row["company"]:
        row["company"] = row.get("detail_company_name", "")
    return row


def fetch_jobs(max_pages: int = config.DEFAULT_MAX_PAGES, fetch_details: bool = True) -> pd.DataFrame:
    """Scrape job postings and full details from workingstudentjobs.de."""
    config.ensure_dirs()
    print(f"\n[WSJ-FETCHER] Starting scrape from workingstudentjobs.de (max {max_pages} pages)...")

    rows: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    empty_streak = 0

    for page in range(1, max_pages + 1):
        listing_url = config.WSJ_SEARCH_TEMPLATE.format(page=page)
        print(f"[WSJ-FETCHER] Fetching page {page}: {listing_url}")
        html_content = _http_get(listing_url)
        if not html_content:
            empty_streak += 1
            print(f"[WSJ-FETCHER] Page {page} returned no content (empty streak: {empty_streak})")
        else:
            parser = _HTMLDataParser()
            parser.feed(html_content)
            page_links: list[str] = []
            for href in parser.links:
                abs_url = urljoin(config.WSJ_BASE_URL, href)
                if _is_job_url(abs_url) and abs_url not in seen_urls:
                    seen_urls.add(abs_url)
                    page_links.append(abs_url)

            if page_links:
                empty_streak = 0
                for u in page_links:
                    rows.append(_blank_row(u))
                print(f"[WSJ-FETCHER] Page {page}: discovered {len(page_links)} new jobs ({len(rows)} cumulative)")
            else:
                empty_streak += 1
                print(f"[WSJ-FETCHER] Page {page}: 0 new jobs found")

        if empty_streak >= 2:
            print("[WSJ-FETCHER] 2 consecutive empty pages encountered; stopping pagination.")
            break

        if page < max_pages:
            time.sleep(config.WSJ_DELAY_SECONDS)

    print(f"[WSJ-FETCHER] Discovered total of {len(rows)} job links.")

    # Fetch full job details
    if fetch_details and rows:
        print(f"[WSJ-FETCHER] Scraping detailed descriptions for {len(rows)} jobs...")
        for idx, row in enumerate(rows, 1):
            url = row["job_url"]
            detail_html = _http_get(url)
            if detail_html:
                row.update(parse_job_detail(url, detail_html))
            else:
                row["detail_error"] = "HTTP detail fetch failed"
            if idx % 10 == 0 or idx == len(rows):
                print(f"[WSJ-FETCHER] Detail extraction progress: {idx}/{len(rows)}")
            if idx < len(rows):
                time.sleep(config.WSJ_DELAY_SECONDS)

    frame = pd.DataFrame(rows, columns=config.COMMON_COLUMNS)
    frame.to_csv(config.FETCHED_CSV, index=False, encoding="utf-8-sig")
    print(f"[WSJ-FETCHER] Successfully saved {len(frame)} fetched jobs to {config.FETCHED_CSV}")
    return frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch workingstudentjobs.de postings")
    parser.add_argument("--pages", type=int, default=config.DEFAULT_MAX_PAGES, help="Max listing pages")
    parser.add_argument("--no-details", action="store_true", help="Skip detail page scraping")
    args = parser.parse_args(argv)

    df = fetch_jobs(max_pages=args.pages, fetch_details=not args.no_details)
    print(f"[WSJ-FETCHER] Finished. Total jobs: {len(df)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
