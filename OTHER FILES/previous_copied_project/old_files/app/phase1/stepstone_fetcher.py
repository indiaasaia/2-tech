"""Standalone Stepstone Phase 1 fetcher."""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from app.core import config
from app.core import activity
from app.core.date_filter import is_within_last_days

LIST_COLUMNS = config.COMMON_COLUMNS[:10]
DETAIL_COLUMNS = config.COMMON_COLUMNS[10:]
ERROR_MARKERS = ("err_http2_protocol_error", "this site can't be reached", "this site can’t be reached")


def build_search_urls(keywords: list[str] | None = None) -> list[str]:
    terms = keywords if keywords is not None else config.STEPSTONE_SEARCH_KEYWORDS
    return [config.STEPSTONE_SEARCH_BASE.format(keyword=quote(str(t).strip().replace(" ", "-"), safe="")) for t in terms]


def build_page_url(base_url: str, page: int) -> str:
    parsed = urlparse(base_url)
    query = parse_qs(parsed.query)
    query["page"] = [str(page)]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query, doseq=True), parsed.fragment))


def _driver(headless: bool) -> webdriver.Chrome:
    options = Options()
    options.add_argument("--window-size=1600,1200")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    if headless:
        options.add_argument("--headless=new")
    return webdriver.Chrome(options=options)


def _text(parent: Any, selector: str) -> str:
    try:
        elements = parent.find_elements(By.CSS_SELECTOR, selector)
        return elements[0].text.strip() if elements else ""
    except WebDriverException:
        return ""


def _attr(parent: Any, selector: str, name: str) -> str:
    try:
        elements = parent.find_elements(By.CSS_SELECTOR, selector)
        value = elements[0].get_attribute(name) if elements else ""
        return str(value or "").strip()
    except WebDriverException:
        return ""


def _transport_error(driver: webdriver.Chrome) -> bool:
    try:
        body = driver.find_element(By.TAG_NAME, "body").text.lower()
    except WebDriverException:
        return False
    return any(marker in body for marker in ERROR_MARKERS)


def _total_jobs(driver: webdriver.Chrome) -> int | None:
    try:
        span = WebDriverWait(driver, config.STEPSTONE_WAIT_SECONDS).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'span[data-at="search-jobs-count"]'))
        )
        value = span.text.strip().replace(".", "").replace(",", "")
        return int(value) if value.isdigit() else None
    except (TimeoutException, ValueError, WebDriverException):
        return None


def _cards(driver: webdriver.Chrome) -> list[dict[str, str]]:
    try:
        WebDriverWait(driver, config.STEPSTONE_WAIT_SECONDS).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "article[data-testid='job-item']"))
        )
    except (TimeoutException, WebDriverException):
        return []
    rows = []
    timestamp = datetime.now(timezone.utc).isoformat()
    for card in driver.find_elements(By.CSS_SELECTOR, "article[data-testid='job-item']"):
        rows.append({
            "source": "stepstone",
            "source_job_id": str(card.get_attribute("id") or ""),
            "title": _text(card, 'a[data-testid="job-item-title"]'),
            "company": _text(card, '[data-at="job-item-company-name"]'),
            "location": _text(card, '[data-at="job-item-location"]'),
            "posted_time": _text(card, "time"),
            "job_url": _attr(card, 'a[data-testid="job-item-title"]', "href"),
            "company_url": _attr(card, 'a[data-at="company-logo"]', "href"),
            "snippet": _text(card, '[data-at="jobcard-content"]'),
            "scraped_at_utc": timestamp,
        })
    return rows


def _detail_text(driver: webdriver.Chrome, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            value = driver.find_element(By.CSS_SELECTOR, selector).text.strip()
            if value:
                return value
        except WebDriverException:
            continue
    return ""


def _details(driver: webdriver.Chrome, url: str) -> dict[str, str]:
    result = {column: "" for column in DETAIL_COLUMNS}
    result["details_fetched"] = "false"
    try:
        driver.get(url)
        WebDriverWait(driver, config.STEPSTONE_WAIT_SECONDS).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
    except (TimeoutException, WebDriverException) as exc:
        result["detail_error"] = f"load error: {type(exc).__name__}"
        return result

    description = _detail_text(driver, [
        ".at-section-text-description-content", '[data-at="section-text-description"]',
        '[data-testid="job-ad-content"]', '[data-at="job-ad-content"]',
    ])
    profile = _detail_text(driver, [
        ".at-section-text-profile", '[data-at="section-text-profile"]',
    ])
    offer = _detail_text(driver, [
        ".at-section-text-benefits", '[data-at="section-text-benefits"]',
    ])
    result.update({
        "detail_company_name": _detail_text(driver, ['[data-at="metadata-company-name"]']),
        "detail_location": _detail_text(driver, ['[data-at="metadata-location"]']),
        "detail_contract_type": _detail_text(driver, ['[data-at="metadata-contract-type"]']),
        "detail_work_type": _detail_text(driver, ['[data-at="metadata-work-type"]']),
        "detail_online_date": _detail_text(driver, ['[data-at="metadata-online-date"]']),
        "job_description": description,
        "applicant_profile": profile,
        "what_they_offer": offer,
        "about_us": _detail_text(driver, ['div[data-at="section-text-introduction"]']),
        "your_tasks": description or _detail_text(driver, ['div[data-at="section-text-description"]']),
        "requirements": profile or _detail_text(driver, ['div[data-at="section-text-profile"]']),
        "we_offer": offer,
        "predicted_salary": _detail_text(driver, ['.at-predicted-salary-range']),
        "details_fetched": "true" if description or profile or offer else "false",
    })
    if result["details_fetched"] == "false":
        result["detail_error"] = "no detail text found"
    return result


def fetch(max_pages: int | None = None, fetch_details: bool | None = None, headless: bool | None = None, max_posting_age_days: float | None = None) -> pd.DataFrame:
    max_pages = config.STEPSTONE_MAX_PAGES if max_pages is None else max(1, max_pages)
    fetch_details = config.STEPSTONE_FETCH_DETAILS if fetch_details is None else fetch_details
    headless = config.STEPSTONE_HEADLESS if headless is None else headless
    max_posting_age_days = config.MAX_POSTING_AGE_DAYS if max_posting_age_days is None else float(max_posting_age_days)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    transport_error = False
    activity.log_event("phase1", "fetch_start", f"stepstone: {len(build_search_urls())} keyword searches, up to {max_pages} pages each, details={fetch_details}", source="stepstone")
    driver = _driver(headless)
    try:
        for base_url in build_search_urls():
            empty_streak = 0
            try:
                driver.get(build_page_url(base_url, 1))
            except WebDriverException as exc:
                print(f"[STEPSTONE] initial page failed: {type(exc).__name__}")
                transport_error = True
                continue
            total = _total_jobs(driver)
            pages = min(max_pages, max(1, math.ceil(total / 25))) if total is not None else max_pages
            for page in range(1, pages + 1):
                try:
                    driver.get(build_page_url(base_url, page))
                    time.sleep(config.STEPSTONE_PAGE_DELAY_SECONDS)
                except WebDriverException:
                    empty_streak += 1
                    if empty_streak >= config.STEPSTONE_EMPTY_PAGE_STOP_STREAK:
                        break
                    continue
                if _transport_error(driver):
                    transport_error = True
                    empty_streak += 1
                    if empty_streak >= config.STEPSTONE_EMPTY_PAGE_STOP_STREAK:
                        break
                    continue
                page_rows = _cards(driver)
                if not page_rows:
                    empty_streak += 1
                    if empty_streak >= config.STEPSTONE_EMPTY_PAGE_STOP_STREAK:
                        break
                    continue
                empty_streak = 0
                for row in page_rows:
                    url = row["job_url"]
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    rows.append(row)
                activity.log_event("phase1", "page", f"stepstone page {page}: {len(page_rows)} cards, {len(rows)} unique so far", source="stepstone", page=page, cards=len(page_rows), unique=len(rows))
                print(f"[STEPSTONE] page {page}: {len(page_rows)} cards")
    finally:
        driver.quit()

    if not rows and transport_error and headless:
        activity.log_event("phase1", "retry", "stepstone retrying headed after headless transport failure", status="warn", source="stepstone")
        print("[STEPSTONE] retrying headed after headless transport failure")
        return fetch(max_pages=max_pages, fetch_details=fetch_details, headless=False, max_posting_age_days=max_posting_age_days)

    if fetch_details and rows:
        detail_driver = _driver(headless)
        try:
            for index, row in enumerate(rows, 1):
                row.update(_details(detail_driver, row["job_url"]))
                if index % 10 == 0 or index == len(rows):
                    activity.log_event("phase1", "details", f"stepstone details {index}/{len(rows)}", source="stepstone", progress=f"{index}/{len(rows)}")
                    print(f"[STEPSTONE] details {index}/{len(rows)}")
        finally:
            detail_driver.quit()
    frame = pd.DataFrame(rows, columns=config.COMMON_COLUMNS)
    if not frame.empty:
        posted_values = frame["posted_time"]
        frame = frame[posted_values.map(is_within_last_days, days=max_posting_age_days).fillna(False)].reset_index(drop=True)
    activity.log_event("phase1", "filter", f"stepstone: {len(frame)} jobs kept after 4-day filter (from {len(rows)})", source="stepstone", kept=len(frame), total=len(rows))
    config.STEPSTONE_CSV.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(config.STEPSTONE_CSV, index=False, encoding="utf-8")
    return frame
