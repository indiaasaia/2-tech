#!/usr/bin/env python3
"""
Fresh-run orchestrator for the 2026-10-05..2026-10-09 job pipeline.

Phase 1 (fetch) only. Writes a self-contained raw fetch artifact under
program_files/output/fresh_run_2026-10-05/ so the existing
program_files/output/*.csv cache is left untouched.

Run:
  python program_files/_fresh_run_20261005.py
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from datetime import datetime, timezone, date
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Tuning for a focused Oct 5-09 window fetched on Oct 9.
# - StepStone: 7 existing keywords, 1 listing page each, headed Chrome
#   (headless hits transport errors here), with a card-level relative-date
#   pre-filter so we only pay for detail pages of fresh listings.
# - WSJ: 2 listing pages with full detail (JSON-LD datePosted is the
#   authoritative posting date).
# ---------------------------------------------------------------------------
os.environ["JOB_AUTOMATION_STEPSTONE_MAX_PAGES"] = "1"
os.environ["JOB_AUTOMATION_WSJ_MAX_PAGES"] = "2"
os.environ["JOB_AUTOMATION_STEPSTONE_DETAILS"] = "1"
os.environ["JOB_AUTOMATION_WSJ_DETAILS"] = "1"
os.environ["JOB_AUTOMATION_HEADLESS"] = "0"  # headed for StepStone reliability

import sub_program_files.stepstone_scraper as ss
import sub_program_files.workingstudent_scraper as ws
from app.phase1 import stepstone_fetcher
from app.core.date_filter import parse_posted_at

FRESH_DIR = PROJECT_ROOT / "program_files" / "output" / "fresh_run_2026-10-05"
RAW_CSV = FRESH_DIR / "step1_raw_fetch.csv"

# Buffer: fetch anything posted within the last 7 days (Oct 3+) so the
# precise Oct 5-9 calendar filter downstream has a clean buffer on both sides.
FETCH_AGE_DAYS = 7.0

WINDOW_START = date(2026, 10, 5)
WINDOW_END = date(2026, 10, 9)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _resolve_posting_local_date(row: dict, now: datetime) -> tuple[date | None, str, str]:
    """Return (local_date_or_None, evidence, method) for a fetched row.

    Method tags: 'iso-posted_time', 'iso-detail_online_date',
    'rel-posted_time', 'rel-detail_online_date', 'unparseable'.
    """
    def local_of(parsed):
        return parsed.astimezone().date() if parsed else None

    # 1. ISO posted_time (rare on StepStone, common on WSJ detail)
    pt = str(row.get("posted_time") or "").strip()
    parsed_pt = parse_posted_at(pt, now=now)
    if parsed_pt is not None and pt and not pt.lower().endswith("ago"):
        return local_of(parsed_pt), pt, "iso-posted_time"

    # 2. ISO detail_online_date (authoritative when present)
    od = str(row.get("detail_online_date") or "").strip()
    od_clean = od.replace("Published:", "").strip() if od.lower().startswith("published:") else od
    parsed_od = parse_posted_at(od_clean, now=now)
    if parsed_od is not None and od_clean and "ago" not in od_clean.lower():
        return local_of(parsed_od), od_clean, "iso-detail_online_date"
    if parsed_od is not None:
        # "Published: N days ago" style -> relative, resolve against NOW (detail
        # fetch happens minutes after scrape; using now is fine for a 5-day window)
        return local_of(parsed_od), od, "rel-detail_online_date"

    # 3. Relative posted_time on the card, resolved against the row's scrape time
    if pt and pt.lower().endswith("ago"):
        scrapetime = parse_posted_at(str(row.get("scraped_at_utc") or ""), now=now) or now
        parsed = parse_posted_at(pt, now=scrapetime)
        if parsed is not None:
            return local_of(parsed), f"{pt} (vs scrape {scrapetime.isoformat()})", "rel-posted_time"

    # 4. Relative detail_online_date resolved against now
    if od and "ago" in od.lower():
        parsed = parse_posted_at(od_clean, now=now)
        if parsed is not None:
            return local_of(parsed), od, "rel-detail_online_date"

    return None, (pt or od or "(no date)"), "unparseable"


def _dedupe_key(job_url: str) -> str:
    """Canonical URL form for cross-source dedup (normalize trailing slash,
    remove tracking query params that StepStone injects)."""
    if not job_url:
        return ""
    p = urlparse(job_url)
    # Drop StepStone inline/ kind suffixes; keep path + id-based query
    params = {k: v for k, v in parse_qs(p.query, keep_blank_values=True).items()
              if k.lower() not in ("searchorigin", "utm_source", "utm_medium", "utm_campaign")}
    canon = urlunparse((p.scheme, p.netloc, p.path.rstrip("/"), p.params,
                        urlencode(params, doseq=True), p.fragment)).rstrip("/")
    return canon.lower()


def fetch_stepstone_fresh(max_age_days: float) -> pd.DataFrame:
    """StepStone: 7 keywords x 1 page (headed), card-date pre-filter, then details."""
    keywords = ["werkstudent", "working student", "intern", "internship",
                "studentische Hilfskraft", "praktikum", "Praktikant"]
    max_pages = 1
    now = datetime.now(timezone.utc)

    # 1. Collect cards from page 1 of each keyword (headed Chrome).
    driver = stepstone_fetcher._driver(headless=False)
    rows: list[dict] = []
    seen: set[str] = set()
    try:
        for base_url in stepstone_fetcher.build_search_urls(keywords):
            for page in range(1, max_pages + 1):
                page_url = stepstone_fetcher.build_page_url(base_url, page)
                try:
                    driver.get(page_url)
                    time.sleep(2.0)
                except Exception as exc:
                    print(f"[FRESH] stepstone page load failed ({base_url[:60]}: p{page}): {exc}")
                    continue
                if stepstone_fetcher._transport_error(driver):
                    print(f"[FRESH] stepstone transport error on ({base_url[:60]}: p{page})")
                    continue
                cards = stepstone_fetcher._cards(driver)
                if not cards:
                    continue
                for card in cards:
                    url = card.get("job_url", "")
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    rows.append(card)
    finally:
        driver.quit()

    print(f"[FRESH] stepstone raw cards collected: {len(rows)}")

    # 2. Card-level relative-date pre-filter: keep listings whose card time
    #    resolves to within max_age_days+1 of now (a small buffer).
    kept: list[dict] = []
    dropped_age = 0
    unparseable = 0
    for row in rows:
        pt = str(row.get("posted_time") or "").strip()
        scrapetime = parse_posted_at(str(row.get("scraped_at_utc") or ""), now=now) or now
        parsed = parse_posted_at(pt, now=scrapetime)
        if parsed is None:
            unparseable += 1
            kept.append(row)  # keep unparseable for review
            continue
        age = (now - parsed).total_seconds() / 86400.0
        if age <= max_age_days + 1:
            kept.append(row)
        else:
            dropped_age += 1
    print(f"[FRESH] stepstone card pre-filter: kept {len(kept)} (age<={max_age_days+1}d), "
          f"dropped {dropped_age} (too old), unparseable {unparseable}")

    # 3. Fetch detail pages for the kept cards only.
    detail_driver = stepstone_fetcher._driver(headless=False)
    detail_start = datetime.now(timezone.utc)
    try:
        for i, row in enumerate(kept, 1):
            url = str(row.get("job_url") or "").strip()
            if not url:
                continue
            try:
                detail = stepstone_fetcher._details(detail_driver, url)
            except Exception as exc:
                detail = {"detail_error": f"{type(exc).__name__}: {exc}"}
            row.update(detail)
            row["detail_scraped_at_utc"] = now_iso()
            if i % 10 == 0 or i == len(kept):
                print(f"[FRESH] stepstone details {i}/{len(kept)}")
    finally:
        detail_driver.quit()

    frame = pd.DataFrame(kept, columns=list(stepstone_fetcher.config.COMMON_COLUMNS) + ["detail_scraped_at_utc"])
    return frame.reset_index(drop=True)


def fetch_wsj_fresh(max_age_days: float) -> pd.DataFrame:
    """WSJ: 2 listing pages, full detail (JSON-LD datePosted is authoritative)."""
    frame = ws.fetch_workingstudentjobs_jobs(
        pages=2, details=True, max_age_days=max_age_days)
    return frame


def main() -> int:
    print("=" * 78)
    print("FRESH RUN 2026-10-05 .. 2026-10-09  (fetch phase)")
    print(f"now (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')} | "
          f"local: {datetime.now(timezone.utc).astimezone().date()}")
    print(f"target window: {WINDOW_START} .. {WINDOW_END} inclusive")
    print(f"fetch age buffer: {FETCH_AGE_DAYS} days (captures Oct 3+ for a clean Oct 5-9 filter)")
    print("=" * 78)

    FRESH_DIR.mkdir(parents=True, exist_ok=True)

    stepstone_frame = pd.DataFrame()
    wsj_frame = pd.DataFrame()
    stepstone_error: str | None = None
    wsj_error: str | None = None

    # ---- StepStone ----
    print("\n### STEPSTONE FETCH (headed Chrome, card-date pre-filter + details) ###")
    try:
        stepstone_frame = fetch_stepstone_fresh(FETCH_AGE_DAYS)
        print(f"[FRESH] stepstone done: {len(stepstone_frame)} rows with details")
    except Exception as exc:
        stepstone_error = f"{type(exc).__name__}: {exc}"
        print(f"[FRESH] STEPSTONE FAILED: {stepstone_error}")
        traceback.print_exc()

    # ---- Workingstudentjobs.de ----
    print("\n### WORKINGSTUDENTJOBS.DE FETCH (requests, JSON-LD datePosted) ###")
    try:
        wsj_frame = fetch_wsj_fresh(FETCH_AGE_DAYS)
        print(f"[FRESH] wsj done: {len(wsj_frame)} rows with details")
    except Exception as exc:
        wsj_error = f"{type(exc).__name__}: {exc}"
        print(f"[FRESH] WSJ FAILED: {wsj_error}")
        traceback.print_exc()

    # ---- Combine + canonical URL dedup ----
    print("\n### COMBINE + DEDUP ###")
    frames = []
    if not stepstone_frame.empty:
        frames.append(stepstone_frame)
    if not wsj_frame.empty:
        frames.append(wsj_frame)
    if not frames:
        print("[FRESH] no rows fetched from either source")
        raw = pd.DataFrame()
    else:
        raw = pd.concat(frames, ignore_index=True, sort=False)
        raw["_dedup_canon"] = raw["job_url"].map(_dedupe_key)
        before = len(raw)
        raw = raw.drop_duplicates(subset="_dedup_canon", keep="first").reset_index(drop=True)
        raw = raw.drop(columns=["_dedup_canon"])
        print(f"[FRESH] combined {before} rows -> {len(raw)} after URL dedup")

    # ---- Save raw fetch artifact (does NOT touch existing cache) ----
    raw_columns = list(stepstone_fetcher.config.COMMON_COLUMNS) + ["detail_scraped_at_utc"]
    raw = raw.reindex(columns=[c for c in raw_columns if c in raw.columns])
    FRESH_DIR.mkdir(parents=True, exist_ok=True)
    raw.to_csv(RAW_CSV, index=False, encoding="utf-8")
    print(f"\n[FRESH] raw fetch saved -> {RAW_CSV} ({len(raw)} rows)")
    print(f"[FRESH]   stepstone rows: {len(stepstone_frame)} | wsj rows: {len(wsj_frame)}")
    if stepstone_error:
        print(f"[FRESH]   stepstone error: {stepstone_error}")
    if wsj_error:
        print(f"[FRESH]   wsj error: {wsj_error}")

    # ---- Quick posting-date audit of the raw fetch ----
    print("\n### RAW FETCH POSTING-DATE AUDIT ###")
    now = datetime.now(timezone.utc)
    audit = []
    for _, row in raw.iterrows():
        local, evidence, method = _resolve_posting_local_date(row, now)
        audit.append({
            "title": str(row.get("title") or "")[:60],
            "company": str(row.get("company") or "")[:40],
            "source": str(row.get("source") or ""),
            "posted_time": str(row.get("posted_time") or "")[:30],
            "detail_online_date": str(row.get("detail_online_date") or "")[:30],
            "scraped_at_utc": str(row.get("scraped_at_utc") or "")[:30],
            "detail_scraped_at_utc": str(row.get("detail_scraped_at_utc") or "")[:30],
            "resolved_local_date": str(local) if local else "None",
            "method": method,
            "in_window": (local is not None and WINDOW_START <= local <= WINDOW_END),
        })
    audit_frame = pd.DataFrame(audit)
    audit_frame.to_csv(FRESH_DIR / "step1_posting_date_audit.csv", index=False, encoding="utf-8")

    from collections import Counter
    print(f"  total rows: {len(audit_frame)}")
    print(f"  methods: {dict(Counter(audit_frame['method']))}")
    print(f"  in {WINDOW_START}..{WINDOW_END} window: {int(audit_frame['in_window'].sum())}")
    print(f"  unparseable: {int((audit_frame['method']=='unparseable').sum())}")
    print("\n  in-window listings:")
    for _, r in audit_frame[audit_frame['in_window']].iterrows():
        print(f"    - {r['source']:20} | {r['resolved_local_date']} | {r['title'][:55]} | {r['company'][:30]}")

    print("\n[FRESH] FETCH PHASE COMPLETE")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FRESH] FATAL: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise SystemExit(1) from exc
