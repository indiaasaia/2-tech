"""Standalone workingstudentjobs.de Phase 1 fetcher."""
from __future__ import annotations

import json
import re
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

from fetching import config
from fetching import activity
from fetching.date_filter import is_within_last_days


class _Parser(HTMLParser):
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


def _get(url: str) -> str | None:
    for attempt in range(config.WSJ_RETRIES):
        try:
            if cffi_requests is not None:
                response = cffi_requests.get(
                    url,
                    impersonate="chrome120",
                    headers={"Accept-Language": "en-US,en;q=0.9,de;q=0.8"},
                    timeout=config.WSJ_TIMEOUT_SECONDS,
                )
            else:
                response = requests.get(
                    url,
                    headers={"User-Agent": config.WSJ_USER_AGENT, "Accept-Language": "en-US,en;q=0.9,de;q=0.8"},
                    timeout=config.WSJ_TIMEOUT_SECONDS,
                )
            if response.ok or (response.text and ("JobPosting" in response.text or "<html" in response.text)):
                return response.text
            print(f"[WSJ] HTTP {response.status_code}: {url}")
        except Exception as exc:
            print(f"[WSJ] request attempt {attempt + 1} failed: {type(exc).__name__}")
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


def _json_objects(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _json_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_objects(child)


def _job_jsonld(parser: _Parser) -> dict[str, Any] | None:
    for raw in parser.jsonld:
        try:
            value = json.loads(raw.strip())
        except (TypeError, json.JSONDecodeError):
            continue
        for obj in _json_objects(value):
            types = obj.get("@type", [])
            types = types if isinstance(types, list) else [types]
            if "JobPosting" in types:
                return obj
    return None


def _clean(value: Any) -> str:
    if isinstance(value, str):
        value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
        value = re.sub(r"<[^>]+>", " ", unescape(value))
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, list):
        return "; ".join(x for x in (_clean(item) for item in value) if x)
    if isinstance(value, dict):
        return _clean(value.get("name") or value.get("value") or value.get("addressLocality") or "")
    return str(value or "").strip()


def _location(value: Any) -> str:
    if not isinstance(value, dict):
        return _clean(value)
    address = value.get("address") or value
    if not isinstance(address, dict):
        return _clean(address)
    return ", ".join(
        _clean(address.get(key)) for key in ("streetAddress", "postalCode", "addressLocality", "addressRegion", "addressCountry")
        if _clean(address.get(key))
    )


def _slug_title(url: str) -> str:
    slug = urlparse(url).path.rstrip("/").split("/", 2)[-1]
    slug = re.sub(r"-[0-9a-f]{8}$", "", slug, flags=re.I)
    return slug.replace("-", " ").title()


def _empty_row(url: str) -> dict[str, str]:
    return {
        column: "" for column in config.COMMON_COLUMNS
    } | {
        "source": "workingstudentjobs.de",
        "source_job_id": url.rsplit("-", 1)[-1],
        "job_url": url,
        "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _parse_detail(url: str, html: str) -> dict[str, str]:
    row = _empty_row(url)
    parser = _Parser()
    parser.feed(html)
    job = _job_jsonld(parser)
    if job:
        organization = job.get("hiringOrganization") or {}
        location = _location(job.get("jobLocation"))
        description = _clean(job.get("description"))
        requirements = _clean(job.get("qualifications") or job.get("experienceRequirements"))
        responsibilities = _clean(job.get("responsibilities"))
        benefits = _clean(job.get("jobBenefits") or job.get("benefits"))
        row.update({
            "title": _clean(job.get("title") or job.get("headline")) or _slug_title(url),
            "company": _clean(organization.get("name") if isinstance(organization, dict) else organization),
            "detail_company_name": _clean(organization.get("name") if isinstance(organization, dict) else organization),
            "company_url": _clean(organization.get("url") if isinstance(organization, dict) else ""),
            "location": location,
            "detail_location": location,
            "posted_time": _clean(job.get("datePosted")),
            "detail_online_date": _clean(job.get("datePosted")),
            "detail_contract_type": _clean(job.get("employmentType")),
            "job_description": description,
            "requirements": requirements,
            "applicant_profile": requirements,
            "your_tasks": responsibilities,
            "what_they_offer": benefits,
            "we_offer": benefits,
            "predicted_salary": _clean(job.get("baseSalary")),
            "details_fetched": "true" if description else "false",
        })
        if not description:
            row["detail_error"] = "JobPosting JSON-LD had no description"
    else:
        visible = "\n".join(parser.text)
        row.update({"title": _slug_title(url), "job_description": visible[:10000], "your_tasks": visible[:10000], "details_fetched": "true" if visible else "false"})
        if not visible:
            row["detail_error"] = "no JSON-LD or visible text found"
    if not row["title"]:
        row["title"] = _slug_title(url)
    if not row["company"]:
        row["company"] = row["detail_company_name"]
    return row


def fetch(max_pages: int | None = None, fetch_details: bool | None = None, max_posting_age_days: float | None = None) -> pd.DataFrame:
    max_pages = config.WSJ_MAX_PAGES if max_pages is None else max(1, max_pages)
    fetch_details = config.WSJ_FETCH_DETAILS if fetch_details is None else fetch_details
    max_posting_age_days = config.MAX_POSTING_AGE_DAYS if max_posting_age_days is None else float(max_posting_age_days)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    empty_streak = 0
    activity.log_event("phase1", "fetch_start", f"workingstudentjobs.de: up to {max_pages} pages, details={fetch_details}", source="workingstudentjobs.de")
    for page in range(1, max_pages + 1):
        listing_url = config.WSJ_SEARCH_TEMPLATE.format(page=page)
        html = _get(listing_url)
        if not html:
            empty_streak += 1
        else:
            parser = _Parser()
            parser.feed(html)
            links = []
            for href in parser.links:
                absolute = urljoin(config.WSJ_BASE_URL, href)
                if _is_job_url(absolute) and absolute not in seen:
                    seen.add(absolute)
                    links.append(absolute)
            if links:
                empty_streak = 0
                rows.extend(_empty_row(url) for url in links)
                activity.log_event("phase1", "page", f"workingstudentjobs.de page {page}: {len(links)} new jobs, {len(rows)} total", source="workingstudentjobs.de", page=page, links=len(links), total=len(rows))
                print(f"[WSJ] page {page}: {len(links)} new jobs")
            else:
                empty_streak += 1
        if empty_streak >= config.WSJ_EMPTY_PAGE_STOP_STREAK:
            break
        if page < max_pages:
            time.sleep(config.WSJ_DELAY_SECONDS)

    if fetch_details:
        for index, row in enumerate(rows, 1):
            html = _get(row["job_url"])
            if html:
                row.update(_parse_detail(row["job_url"], html))
            else:
                row["detail_error"] = "detail request failed after retries"
            if not row["title"]:
                row["title"] = _slug_title(row["job_url"])
            if index % 10 == 0 or index == len(rows):
                activity.log_event("phase1", "details", f"workingstudentjobs.de details {index}/{len(rows)}", source="workingstudentjobs.de", progress=f"{index}/{len(rows)}")
                print(f"[WSJ] details {index}/{len(rows)}")
            if index < len(rows):
                time.sleep(config.WSJ_DELAY_SECONDS)

    frame = pd.DataFrame(rows, columns=config.COMMON_COLUMNS)
    if not frame.empty:
        frame = frame[frame["posted_time"].map(is_within_last_days, days=max_posting_age_days).fillna(False)].reset_index(drop=True)
    activity.log_event("phase1", "filter", f"workingstudentjobs.de: {len(frame)} jobs kept after {max_posting_age_days:g}-day filter (from {len(rows)})", source="workingstudentjobs.de", kept=len(frame), total=len(rows))
    config.WORKINGSTUDENT_CSV.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(config.WORKINGSTUDENT_CSV, index=False, encoding="utf-8")
    return frame
