"""
1_MERCEDES_Jobs_fetching.py
---------------------------
Fetches all Mercedes-Benz student jobs across both:
1. Workday (Mercedes-Benz Tech Innovation - MBTI): 100% autonomous guest application portal
2. Taleo (Mercedes-Benz Group AG): Career portal positions

Outputs:
- MERCEDES_results.csv (title + link + portal)
- MERCEDES_jobs_detailed.csv (full enriched schema)
- MERCEDES_jobs_full.json (complete JSON payload)
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
RESULTS_CSV = ROOT / "MERCEDES_results.csv"
DETAILED_CSV = ROOT / "MERCEDES_jobs_detailed.csv"
FULL_JSON = ROOT / "MERCEDES_jobs_full.json"

WORKDAY_BASE = "https://mercedesbenztechinnovation.wd3.myworkdayjobs.com"
WORKDAY_LIST_API = f"{WORKDAY_BASE}/wday/cxs/mercedesbenztechinnovation/MBTI_JOBPORTAL/jobs"
WORKDAY_DETAIL_API = f"{WORKDAY_BASE}/wday/cxs/mercedesbenztechinnovation/MBTI_JOBPORTAL"

TALEO_SEARCH_URL = "https://jobs.api.mercedes-benz.com/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

CSV_COLUMNS = [
    "title", "link", "source", "portal", "job_id", "ref_number", "company", "division",
    "position_type", "employment_type", "contract_type", "working_hours",
    "experience_level", "industry", "function", "language", "city", "region",
    "country", "address", "postal_code", "latitude", "longitude", "remote",
    "posting_date", "application_end", "released_date", "active", "recruiter",
    "start_info", "description_text", "custom_fields",
]


def fetch_workday_jobs() -> list[dict]:
    """Fetch all MBTI Workday student/intern positions."""
    print("[workday] Querying Mercedes-Benz Tech Innovation Workday API...")
    payload = {
        "appliedFacets": {},
        "limit": 20,
        "offset": 0,
        "searchText": "",
    }
    jobs = []
    try:
        resp = requests.post(WORKDAY_LIST_API, json=payload, timeout=30)
        if resp.status_code != 200:
            print(f"[workday] API returned status {resp.status_code}")
            return []
        data = resp.json()
        postings = data.get("jobPostings", [])
        print(f"[workday] Found {len(postings)} positions on MBTI Workday.")
        
        for p in postings:
            title = p.get("title", "")
            ext_path = p.get("externalPath", "")
            job_url = f"{WORKDAY_BASE}/en-US/MBTI_JOBPORTAL{ext_path}"
            
            # Fetch full details
            detail_url = f"{WORKDAY_DETAIL_API}{ext_path}"
            d_resp = requests.get(detail_url, timeout=30)
            desc_text = ""
            city = ""
            start_date = ""
            posted_on = ""
            if d_resp.status_code == 200:
                d_info = d_resp.json().get("jobPostingInfo", {})
                desc_html = d_info.get("jobDescription", "")
                desc_text = html.unescape(re.sub(r"<[^>]+>", " ", desc_html)).strip()
                desc_text = re.sub(r"\s+", " ", desc_text)
                city = d_info.get("location", "")
                start_date = d_info.get("startDate", "")
                posted_on = d_info.get("postedOn", "")

            req_id_m = re.search(r"_(R\d+)", ext_path)
            ref_num = req_id_m.group(1) if req_id_m else ext_path.split("-")[-1]

            row = {
                "title": title,
                "link": job_url,
                "source": "mercedes_workday_api",
                "portal": "workday",
                "job_id": ref_num,
                "ref_number": ref_num,
                "company": "Mercedes-Benz Tech Innovation GmbH",
                "division": "Tech Innovation",
                "position_type": "Working Student / Intern",
                "employment_type": "Part-time / Full-time",
                "contract_type": "Befristet",
                "working_hours": "",
                "experience_level": "Student",
                "industry": "Automotive Software / Tech",
                "function": "Software Engineering / AI",
                "language": "English / German",
                "city": city,
                "region": "Baden-Württemberg",
                "country": "Germany",
                "address": "",
                "postal_code": "",
                "latitude": "",
                "longitude": "",
                "remote": "",
                "posting_date": posted_on,
                "application_end": "",
                "released_date": posted_on,
                "active": "true",
                "recruiter": "",
                "start_info": start_date,
                "description_text": desc_text,
                "custom_fields": json.dumps({"apply_url": job_url, "portal": "workday"}),
            }
            jobs.append(row)
            print(f"  + Workday: {title} ({ref_num})")
    except Exception as exc:
        print(f"[workday] Error querying Workday API: {exc}")
    return jobs


def fetch_taleo_jobs(limit: int = 50) -> list[dict]:
    """Fetch Taleo positions from jobs.api.mercedes-benz.com."""
    print(f"[taleo] Querying Mercedes-Benz Group Taleo API (limit {limit})...")
    criteria = [
        {"CriterionName": "TargetGroup.Code", "CriterionValue": ["2"]},
        {"CriterionName": "CareerLevel.Code", "CriterionValue": ["25"]},
        {"CriterionName": "PositionFormattedDescription.Content", "CriterionValue": ['"werkstudent"']},
        {"CriterionName": "PositionLocation.Country", "CriterionValue": ["329"]},
    ]
    sort = [{"Criterion": "PositionStartDateInitial", "Direction": "DESC"}]
    payload = {
        "LanguageCode": "DE",
        "SearchParameters": {"FirstItem": 1, "CountItem": limit, "Sort": sort},
        "SearchCriteria": criteria,
    }
    jobs = []
    try:
        resp = requests.post(TALEO_SEARCH_URL, json=payload, headers=HEADERS, timeout=40)
        if resp.status_code != 200:
            print(f"[taleo] API returned {resp.status_code}")
            return []
        data = resp.json()
        search_result = data.get("SearchResult", {})
        items = search_result.get("SearchResultItems", [])
        print(f"[taleo] Retrieved {len(items)} Taleo positions.")
        for item in items:
            title = item.get("PositionTitle", "")
            job_id = str(item.get("PositionId", ""))
            ref_num = item.get("PositionFormattedDescription", {}).get("JobNumber", job_id)
            desc_html = item.get("PositionFormattedDescription", {}).get("Content", "")
            desc_text = html.unescape(re.sub(r"<[^>]+>", " ", desc_html)).strip()
            desc_text = re.sub(r"\s+", " ", desc_text)
            city = item.get("PositionLocation", {}).get("City", "")
            apply_url = f"https://tas-DAIMLER.taleo.net/careersection/ex/jobapply.ftl?job={ref_num}&lang=de"
            job_link = f"https://jobs.mercedes-benz.com/{job_id}-{ref_num}"
            
            row = {
                "title": title,
                "link": job_link,
                "source": "mercedes_taleo_api",
                "portal": "taleo",
                "job_id": job_id,
                "ref_number": ref_num,
                "company": "Mercedes-Benz AG",
                "division": "",
                "position_type": "Working student",
                "employment_type": "Part-time",
                "contract_type": "Befristet",
                "working_hours": "",
                "experience_level": "Student",
                "industry": "Automotive",
                "function": "",
                "language": "German / English",
                "city": city,
                "region": "",
                "country": "Germany",
                "address": "",
                "postal_code": "",
                "latitude": "",
                "longitude": "",
                "remote": "",
                "posting_date": "",
                "application_end": "",
                "released_date": "",
                "active": "true",
                "recruiter": "",
                "start_info": "",
                "description_text": desc_text,
                "custom_fields": json.dumps({"apply_url": apply_url, "portal": "taleo"}),
            }
            jobs.append(row)
    except Exception as exc:
        print(f"[taleo] Error querying Taleo API: {exc}")
    return jobs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-taleo", type=int, default=50, help="Max Taleo jobs to fetch")
    args = parser.parse_args()

    # 1. Fetch Workday jobs (100% autonomous)
    workday_jobs = fetch_workday_jobs()
    # 2. Fetch Taleo jobs
    taleo_jobs = fetch_taleo_jobs(limit=args.limit_taleo)
    
    all_jobs = workday_jobs + taleo_jobs
    print(f"\n[summary] Total Mercedes jobs fetched: {len(all_jobs)} (Workday: {len(workday_jobs)}, Taleo: {len(taleo_jobs)})")
    
    # Save results CSV
    with open(RESULTS_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["title", "link", "portal", "job_id"])
        for j in all_jobs:
            writer.writerow([j["title"], j["link"], j["portal"], j["job_id"]])
    print(f"Saved -> {RESULTS_CSV}")

    # Save detailed CSV
    with open(DETAILED_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(all_jobs)
    print(f"Saved -> {DETAILED_CSV}")

    # Save full JSON
    FULL_JSON.write_text(json.dumps(all_jobs, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved -> {FULL_JSON}")


if __name__ == "__main__":
    main()
