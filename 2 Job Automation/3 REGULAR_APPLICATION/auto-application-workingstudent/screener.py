"""LLM-assisted screening for working student & internship postings.

Classifies:
  1. role_type: keep working_student, internship, student_assistant, thesis; drop senior/full-time
  2. german_requirement: keep if none, nice_to_have, or required level <= candidate level (A2)
  3. country: keep Germany / remote Germany
  4. is_tech_related & tech_domain: keep tech/data/software/operations roles; drop pure non-tech

Features persistent disk caching to avoid redundant LLM calls.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from . import config
except ImportError:
    import config

config.ensure_utf8_stdout()

# Engine LLM client
from engine.generation.llm import LLMError, call_llm, extract_json, load_first_key

ROLE_TYPES = (
    "working_student", "internship", "student_assistant", "thesis",
    "apprenticeship", "entry_level", "experienced", "senior", "freelance", "other"
)
KEEP_ROLES = {"working_student", "internship", "student_assistant"}
CEFR_RANK = {"none": 0, "A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6, "native": 6}
UNSPECIFIED_REQUIRED_LEVEL = "B2"
EXCERPT_CHARS = 3500
SCREEN_VERSION = 2
TECH_DOMAINS = ("software", "data_ai", "hardware_iot", "automation_robotics", "it_systems", "tech_business", "non_tech")

_NON_TECH_TITLE_RE = re.compile(
    r"(?i)\b("
    r"physio\w*|therap\w*|ergotherap\w*|logopäd\w*|masseur\w*|massage\w*|heilpraktik\w*|osteopath\w*|"
    r"arzt|ärzt\w*|mediziner\w*|pflege\w*|krankenschwester|krankenpfleg\w*|altenpfleg\w*|hebamme|zahnarzt\w*|zahnmedizin\w*|kieferorth\w*|apotheker\w*|pta\b|pka\b|"
    r"erzieher\w*|pädagog\w*|sozialarbeit\w*|kita\w*|kindergarten\w*|kindergärtner\w*|grundschul\w*|"
    r"kellner\w*|koch|köchin|küchen\w*|servicekraft|gastronomie\w*|barkeeper|barista|bäcker\w*|konditor\w*|fleischer\w*|metzger\w*|"
    r"friseur\w*|kosmetik\w*|nageldesign\w*|reinigungs\w*|putzkraft|hausmeister\w*|lagerarbeiter\w*|staplerfahrer\w*|"
    r"maler|lackierer|tischler|schreiner|zimmerer|dachdecker|klempner|schlosser|"
    r"jurist\w*|rechtsanwalt\w*|anwalt\w*|notar\w*|notarfach\w*"
    r")\b"
)


def get_candidate_german_level() -> str:
    """Read candidate's German CEFR level from candidate_kb.json."""
    if not config.KB_PATH.exists():
        return "A2"
    try:
        kb = json.loads(config.KB_PATH.read_text(encoding="utf-8"))
        for entry in (kb.get("profile") or {}).get("languages_spoken") or []:
            if str(entry.get("lang") or "").lower() in ("german", "deutsch"):
                match = re.search(r"\b([ABC][12])\b", str(entry.get("level") or ""))
                if match:
                    return match.group(1)
    except Exception:
        pass
    return "A2"


def _build_excerpt(job: dict[str, Any]) -> str:
    parts = []
    for col in ("requirements", "applicant_profile", "your_tasks", "job_description", "what_they_offer", "snippet"):
        text = " ".join(str(job.get(col) or "").split())
        if text and text.lower() != "nan" and text not in parts:
            parts.append(f"[{col}] {text}")
    return "\n".join(parts)[:EXCERPT_CHARS]


_SYSTEM_PROMPT = """You are a job screening assistant for an IT candidate seeking Working Student and Internship positions in Germany.
Classify the job posting strictly into JSON:
{
  "role_type": "working_student" | "internship" | "student_assistant" | "thesis" | "apprenticeship" | "entry_level" | "experienced" | "senior" | "freelance" | "other",
  "role_evidence": "quote explaining role type",
  "german_requirement": "none" | "nice_to_have" | "required",
  "german_level": "none" | "unspecified" | "A1" | "A2" | "B1" | "B2" | "C1" | "C2" | "native",
  "german_evidence": "quote regarding German requirements",
  "ad_language": "de" | "en" | "mixed",
  "country": "Germany" | "Austria" | "Switzerland" | "other",
  "is_tech_related": true | false,
  "tech_domain": "software" | "data_ai" | "hardware_iot" | "automation_robotics" | "it_systems" | "tech_business" | "non_tech",
  "domain_evidence": "quote showing technical nature or non-tech role"
}
"""


def _classify_with_llm(job: dict[str, Any], token: str) -> dict[str, Any]:
    full_prompt = (
        f"{_SYSTEM_PROMPT}\n\n"
        f"Title: {job.get('title')}\n"
        f"Company: {job.get('company')}\n"
        f"Location: {job.get('location')}\n\n"
        f"Job Ad Excerpt:\n{_build_excerpt(job)}\n\n"
        f"Return ONLY the JSON object, nothing else."
    )
    raw = call_llm(full_prompt, token=token, temperature=0.0, max_tokens=2000)
    extracted = extract_json(raw)
    if not isinstance(extracted, dict):
        raise ValueError("LLM returned non-JSON")
    return extracted


def _fallback_rule_screen(job: dict[str, Any]) -> dict[str, Any]:
    """Deterministic fallback screening if LLM is unavailable."""
    title = str(job.get("title") or "").lower()
    text = (str(job.get("job_description") or "") + " " + str(job.get("requirements") or "")).lower()

    # Role type
    if any(k in title for k in ("werkstudent", "working student", "studentische")):
        role = "working_student"
    elif any(k in title for k in ("praktik", "intern", "stage")):
        role = "internship"
    elif any(k in title for k in ("bachelorarbeit", "masterarbeit", "thesis")):
        role = "thesis"
    else:
        role = "working_student" if "student" in text else "other"

    # Non-tech check
    is_non_tech = bool(_NON_TECH_TITLE_RE.search(title))
    tech_domain = "non_tech" if is_non_tech else "software"
    is_tech = not is_non_tech

    # German check
    if any(k in text for k in ("deutsch verhandlungssicher", "c1 deutsch", "b2 deutsch", "sehr gute deutschkenntnisse")):
        de_req = "required"
        de_lvl = "B2"
    elif any(k in text for k in ("deutschkenntnisse von vorteil", "german is a plus")):
        de_req = "nice_to_have"
        de_lvl = "unspecified"
    else:
        de_req = "none"
        de_lvl = "none"

    return {
        "role_type": role,
        "role_evidence": "Rule fallback based on title/keywords",
        "german_requirement": de_req,
        "german_level": de_lvl,
        "german_evidence": "Keyword match",
        "ad_language": "en" if "experience" in text or "requirements" in text else "de",
        "country": "Germany",
        "is_tech_related": is_tech,
        "tech_domain": tech_domain,
        "domain_evidence": "Rule fallback",
    }


def evaluate_decision(
    classified: dict[str, Any],
    candidate_level: str = "A2",
    include_thesis: bool = True,
    keep_abroad: bool = False,
) -> tuple[str, str]:
    """Evaluate whether the job should be kept or dropped.

    Returns:
        (decision: 'keep'|'drop', reason: str)
    """
    role = str(classified.get("role_type") or "").strip()
    allowed_roles = set(KEEP_ROLES)
    if include_thesis:
        allowed_roles.add("thesis")

    if role not in allowed_roles:
        return "drop", f"role_type '{role}' not in target roles ({', '.join(sorted(allowed_roles))})"

    # German check
    de_req = str(classified.get("german_requirement") or "").strip()
    de_lvl = str(classified.get("german_level") or "unspecified").strip()
    if de_req == "required":
        req_rank = CEFR_RANK.get(de_lvl, CEFR_RANK[UNSPECIFIED_REQUIRED_LEVEL])
        cand_rank = CEFR_RANK.get(candidate_level, CEFR_RANK["A2"])
        if req_rank > cand_rank:
            return "drop", f"German required ({de_lvl}) exceeds candidate level ({candidate_level})"

    # Country check
    country = str(classified.get("country") or "").strip()
    if not keep_abroad and country and country.lower() not in ("germany", "deutschland", "remote"):
        return "drop", f"location is outside Germany ({country})"

    # Tech check
    if not classified.get("is_tech_related", True) or classified.get("tech_domain") == "non_tech":
        return "drop", f"non-tech role ({classified.get('tech_domain')})"

    return "keep", "passed all screening gates (student/intern role, German requirement compatible, Germany tech)"


def screen_jobs(
    input_csv: Path | None = None,
    output_csv: Path | None = None,
    report_csv: Path | None = None,
    include_thesis: bool = True,
    keep_abroad: bool = False,
) -> pd.DataFrame:
    """Run screening on jobs from input_csv and write screened_jobs.csv & report."""
    config.ensure_dirs()
    in_path = input_csv or config.UNAPPLIED_CSV
    if not in_path.exists():
        in_path = config.FILTERED_CSV
    out_path = output_csv or config.SCREENED_CSV
    rep_path = report_csv or config.SCREENING_REPORT_CSV

    if not in_path.exists():
        print(f"[SCREENER] Error: Input file not found: {in_path}")
        return pd.DataFrame()

    frame = pd.read_csv(in_path, keep_default_na=False)
    if frame.empty:
        print("[SCREENER] No jobs in input to screen.")
        pd.DataFrame().to_csv(out_path, index=False)
        return pd.DataFrame()

    # Load cache (combine local and main project cache if available)
    cache: dict[str, Any] = {}
    main_cache_path = config.PROJECT_ROOT / "output" / "jobs" / "screening_cache.json"
    if main_cache_path.exists():
        try:
            cache.update(json.loads(main_cache_path.read_text(encoding="utf-8")))
        except Exception:
            pass
    if config.SCREENING_CACHE_JSON.exists():
        try:
            cache.update(json.loads(config.SCREENING_CACHE_JSON.read_text(encoding="utf-8")))
        except Exception:
            pass

    token = load_first_key()
    cand_level = get_candidate_german_level()
    print(f"[SCREENER] Candidate German level: {cand_level}")
    print(f"[SCREENER] Screening {len(frame)} jobs with LLM (token available: {bool(token)})...")

    screened_rows = []
    report_rows = []

    for idx, row in frame.iterrows():
        job_dict = row.to_dict()
        url = str(job_dict.get("job_url") or "").strip()
        company = str(job_dict.get("company") or "")
        title = str(job_dict.get("title") or "")

        # Check cache
        classified = None
        if url in cache and cache[url].get("version") == SCREEN_VERSION:
            classified = cache[url].get("facts")

        if classified is None:
            # Check non-tech fast regex
            if _NON_TECH_TITLE_RE.search(title):
                classified = {
                    "role_type": "working_student",
                    "role_evidence": "Title match",
                    "german_requirement": "none",
                    "german_level": "none",
                    "german_evidence": "",
                    "ad_language": "en",
                    "country": "Germany",
                    "is_tech_related": False,
                    "tech_domain": "non_tech",
                    "domain_evidence": f"Excluded by non-tech title pattern: {title}",
                }
            elif token:
                try:
                    classified = _classify_with_llm(job_dict, token)
                except Exception as exc:
                    print(f"[SCREENER] LLM error for {company} - {title} ({exc}), using rule fallback")
                    classified = _fallback_rule_screen(job_dict)
            else:
                classified = _fallback_rule_screen(job_dict)

            cache[url] = {
                "version": SCREEN_VERSION,
                "url": url,
                "company": company,
                "title": title,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "facts": classified,
            }

        decision, reason = evaluate_decision(
            classified,
            candidate_level=cand_level,
            include_thesis=include_thesis,
            keep_abroad=keep_abroad,
        )

        rep_item = dict(job_dict)
        rep_item.update(classified)
        rep_item["decision"] = decision
        rep_item["reason"] = reason
        report_rows.append(rep_item)

        if decision == "keep":
            row_kept = dict(job_dict)
            row_kept.update(classified)
            row_kept["screening_decision"] = decision
            row_kept["screening_reason"] = reason
            screened_rows.append(row_kept)

    # Save cache
    config.SCREENING_CACHE_JSON.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")

    # Save report
    rep_df = pd.DataFrame(report_rows)
    rep_df.to_csv(rep_path, index=False, encoding="utf-8-sig")

    # Save screened jobs
    kept_df = pd.DataFrame(screened_rows)
    kept_df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"[SCREENER] Screening complete: {len(kept_df)} / {len(frame)} jobs KEPT -> {out_path}")
    print(f"[SCREENER] Detailed report saved to {rep_path}")
    return kept_df


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM screening for working student jobs")
    parser.add_argument("--include-thesis", action="store_true", default=True, help="Keep thesis positions")
    parser.add_argument("--keep-abroad", action="store_true", help="Keep positions outside Germany")
    args = parser.parse_args(argv)

    df = screen_jobs(include_thesis=args.include_thesis, keep_abroad=args.keep_abroad)
    return 0 if not df.empty else 1


if __name__ == "__main__":
    raise SystemExit(main())
