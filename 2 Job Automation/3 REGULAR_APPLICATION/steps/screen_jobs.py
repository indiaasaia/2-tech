"""Step 2b: LLM screening of the fetched jobs (role type, German requirement, country).

One Ollama call (gpt-oss:120b, the same client the engine uses) per job reads
the ad and returns structured facts; a deterministic rule then keeps or drops
the job, so the decision is explainable and easy to change:

  role     keep working student / internship / student assistant (thesis with
           --include-thesis); drop senior, experienced, entry-level full-time,
           apprenticeship, freelance and other roles
  German   drop when German is REQUIRED above your level (A2, read from the KB);
           "nice to have" never drops a job
  country  drop jobs outside Germany (your permit covers Germany only;
           --keep-abroad disables this)

Decisions are cached per job URL (output/jobs/screening_cache.json), so an
overlapping --days window never pays twice. If the LLM fails for a job, a
rule-based classifier on the title and text decides instead.

Input : output/jobs/filtered_jobs.csv (step 2)
Output: output/jobs/screened_jobs.csv (kept jobs = engine input)
        output/jobs/screening_report.csv (every job with its decision and evidence)

Run alone:  python steps/screen_jobs.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine import config  # noqa: E402
config.ensure_utf8_stdout()
from engine.generation.llm import LLMError, call_llm, extract_json, load_first_key  # noqa: E402

JOBS_DIR = PROJECT_ROOT / "output" / "jobs"
INPUT_CSV = JOBS_DIR / "filtered_jobs.csv"
OUTPUT_CSV = JOBS_DIR / "screened_jobs.csv"
REPORT_CSV = JOBS_DIR / "screening_report.csv"
CACHE_PATH = JOBS_DIR / "screening_cache.json"
KB_PATH = PROJECT_ROOT / "engine" / "knowledge_base" / "candidate_kb.json"

ROLE_TYPES = ("working_student", "internship", "student_assistant", "thesis", "apprenticeship",
              "entry_level", "experienced", "senior", "freelance", "other")
KEEP_ROLES = {"working_student", "internship", "student_assistant"}
CEFR_RANK = {"none": 0, "A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6, "native": 6}
# "German required" without a level means business German in practice
UNSPECIFIED_REQUIRED_LEVEL = "B2"
EXCERPT_CHARS = 3500
SCREEN_VERSION = 2           # bump to invalidate cached decisions after a prompt change
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


# ---------------------------------------------------------------------------
# candidate level
# ---------------------------------------------------------------------------
def candidate_german_level(kb_path: Path = KB_PATH) -> str:
    """The candidate's German CEFR level from the KB ('A2 (conversational)' -> 'A2')."""
    try:
        kb = json.loads(kb_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "A2"
    for entry in (kb.get("profile") or {}).get("languages_spoken") or []:
        if str(entry.get("lang") or "").lower() in ("german", "deutsch"):
            match = re.search(r"\b([ABC][12])\b", str(entry.get("level") or ""))
            if match:
                return match.group(1)
    return "A2"


# ---------------------------------------------------------------------------
# prompt + classification
# ---------------------------------------------------------------------------
def _excerpt(job: dict) -> str:
    """Language and seniority demands usually sit in the profile/requirements: those first."""
    parts = []
    for column in ("requirements", "applicant_profile", "your_tasks", "job_description", "what_they_offer", "snippet"):
        text = " ".join(str(job.get(column) or "").split())
        if text and text.lower() != "nan" and text not in parts:
            parts.append(f"[{column}] {text}")
    return "\n".join(parts)[:EXCERPT_CHARS]


def screen_prompt(job: dict) -> str:
    return f"""Classify this job ad. Read it carefully; answer only from the ad.

TITLE: {job.get('title', '')}
COMPANY: {job.get('company', '')}
LOCATION: {job.get('detail_location') or job.get('location') or ''}
AD TEXT:
{_excerpt(job)}

Return ONLY this JSON:
{{"role_type": one of {list(ROLE_TYPES)},
 "role_evidence": "<=12 words quoted from the title/ad that decide the role type",
 "is_tech_related": true | false,
 "tech_domain": one of {list(TECH_DOMAINS)},
 "domain_evidence": "<=12 words showing tech domain or why non-tech",
 "german_requirement": "none" | "nice_to_have" | "required",
 "german_level": "none" | "A1" | "A2" | "B1" | "B2" | "C1" | "C2" | "native" | "unspecified",
 "german_evidence": "<=15 words quoted from the ad about German, or empty",
 "ad_language": "en" | "de" | "mixed",
 "country": "<country of the workplace, e.g. Germany, United Kingdom>" or "unknown"}}

Rules:
- role_type: working_student = Werkstudent/working student (part-time while studying);
  internship = Praktikum/intern/placement (incl. mandatory internship); student_assistant =
  studentische/wissenschaftliche Hilfskraft, HiWi, student assistant; thesis = Bachelor/Master thesis;
  senior = senior/lead/principal/head roles; experienced = needs several years of professional
  experience; entry_level = junior/graduate/trainee/full-time employee roles; apprenticeship =
  Ausbildung/duales Studium; freelance = freelancer/contractor.
- is_tech_related: true if the role involves computer science, software, data/AI, IT systems,
  automation, robotics, hardware/electronics, or tech-driven business/product roles.
  false if non-technical (e.g. physiotherapy, healthcare, nursing, hospitality, manual trades, salon, teaching).
- tech_domain: primary domain or "non_tech" if not tech-related.
- german_requirement: "required" only if the ad demands German (e.g. "fluent German", "sehr gute
  Deutschkenntnisse", "German C1", "German required"); "nice_to_have" if German is a plus/advantage.
  A German-written ad with no stated language demand is "none" (record ad_language "de").
- german_level: map words to CEFR: basic/Grundkenntnisse=A2, good/gute=B2, very good/fluent/
  fließend/verhandlungssicher=C1, native/Muttersprache=native; "unspecified" if required without level.
- country: where the job is located (a UK city means United Kingdom)."""


def _norm(value: object, allowed: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip()
    for item in allowed:
        if text.lower() == item.lower():
            return item
    return default


def parse_classification(data: dict | None) -> dict | None:
    """Validated, normalized classification ({} fields coerced) or None when unusable."""
    if not isinstance(data, dict) or "role_type" not in data:
        return None
    level = str(data.get("german_level") or "none").strip()
    level = level.upper() if re.fullmatch(r"(?i)[abc][12]", level) else level.lower()
    is_tech = data.get("is_tech_related")
    if not isinstance(is_tech, bool):
        is_tech = str(is_tech).strip().lower() in ("true", "1", "yes") if is_tech is not None else True
    return {
        "role_type": _norm(data.get("role_type"), ROLE_TYPES, "other"),
        "role_evidence": str(data.get("role_evidence") or "")[:160],
        "is_tech_related": is_tech,
        "tech_domain": _norm(data.get("tech_domain"), TECH_DOMAINS, "software" if is_tech else "non_tech"),
        "domain_evidence": str(data.get("domain_evidence") or "")[:160],
        "german_requirement": _norm(data.get("german_requirement"), ("none", "nice_to_have", "required"), "none"),
        "german_level": level if level in CEFR_RANK or level == "unspecified" else "unspecified",
        "german_evidence": str(data.get("german_evidence") or "")[:200],
        "ad_language": _norm(data.get("ad_language"), ("en", "de", "mixed"), "en"),
        "country": str(data.get("country") or "unknown").strip() or "unknown",
    }


_STUDENT_TITLE_RE = re.compile(r"(?i)werkstudent|working[\s-]?student|work student|student\w*\s+(?:assistant|job)|"
                               r"hilfskraft|\bhiwi\b")
_INTERN_TITLE_RE = re.compile(r"(?i)\bintern\b|internship|praktik|placement|\bpraktikum")
_THESIS_TITLE_RE = re.compile(r"(?i)\bthesis\b|abschlussarbeit|masterarbeit|bachelorarbeit")
_SENIOR_TITLE_RE = re.compile(r"(?i)\b(?:senior|sr\.|lead|principal|head of|director|vp|chief)\b")
_GERMAN_REQUIRED_RE = re.compile(
    r"(?i)german required|fluent (?:in )?german|german \(?(?:c1|c2|b2)|(?:sehr )?gute deutschkenntnisse|"
    r"fließend(?:e)? deutsch|deutsch (?:fließend|verhandlungssicher)|verhandlungssicher\w* deutsch|"
    r"business[- ]fluent german|native german|deutsch als muttersprache")
_ABROAD_RE = re.compile(r"(?i)\b(?:united kingdom|england|scotland|wales|northern ireland|london|bristol|manchester|"
                        r"leeds|nottingham|birmingham|belfast|glasgow|edinburgh|dublin|ireland|usa|united states)\b")


def rule_classification(job: dict) -> dict:
    """Fallback when the LLM is unavailable: title/text rules (conservative)."""
    title = str(job.get("title") or "")
    text = f"{title} {_excerpt(job)}"
    if _STUDENT_TITLE_RE.search(title):
        role = "working_student" if not _INTERN_TITLE_RE.search(title) else "internship"
    elif _INTERN_TITLE_RE.search(title):
        role = "internship"
    elif _THESIS_TITLE_RE.search(title):
        role = "thesis"
    elif _SENIOR_TITLE_RE.search(title):
        role = "senior"
    else:
        role = "other"
    required = bool(_GERMAN_REQUIRED_RE.search(text))
    location = f"{job.get('detail_location') or ''} {job.get('location') or ''}"
    is_non_tech = bool(_NON_TECH_TITLE_RE.search(title))
    return {
        "role_type": role, "role_evidence": title[:160],
        "is_tech_related": not is_non_tech,
        "tech_domain": "non_tech" if is_non_tech else "software",
        "domain_evidence": _NON_TECH_TITLE_RE.search(title).group(0) if is_non_tech else "rule fallback",
        "german_requirement": "required" if required else "none",
        "german_level": "unspecified" if required else "none",
        "german_evidence": (_GERMAN_REQUIRED_RE.search(text).group(0) if required else ""),
        "ad_language": "en", "country": "United Kingdom" if _ABROAD_RE.search(location) else "unknown",
    }


def classify_job(job: dict, token: str) -> tuple[dict, str]:
    """(classification, source) with source 'llm' or 'rule'. One call + one JSON repair."""
    prompt = screen_prompt(job)
    for attempt in range(2):
        try:
            raw = call_llm(prompt if attempt == 0 else prompt + "\n\nReturn ONLY the JSON object, nothing else.",
                           token, temperature=0.0, max_tokens=2000)
        except LLMError as exc:
            print(f"    LLM unavailable ({str(exc)[:80]}) -> rule fallback")
            break
        parsed = parse_classification(extract_json(raw))
        if parsed:
            return parsed, "llm"
    return rule_classification(job), "rule"


# ---------------------------------------------------------------------------
# decision
# ---------------------------------------------------------------------------
def decide(c: dict, title: str, candidate_level: str = "A2", include_thesis: bool = False,
           keep_abroad: bool = False) -> tuple[bool, str]:
    """(keep, reason) from a classification. Pure function: no I/O."""
    if _NON_TECH_TITLE_RE.search(title):
        return False, f"non-tech title: {_NON_TECH_TITLE_RE.search(title).group(0)}"
    if c.get("is_tech_related") is False or c.get("tech_domain") == "non_tech":
        return False, f"non-tech: {c.get('domain_evidence') or 'classified as non-tech'}"

    keep_roles = KEEP_ROLES | ({"thesis"} if include_thesis else set())
    role = c.get("role_type", "other")
    if role in keep_roles and _SENIOR_TITLE_RE.search(title) and not (
            _STUDENT_TITLE_RE.search(title) or _INTERN_TITLE_RE.search(title)):
        role = "senior"                      # the title overrules a mislabel
    if role not in keep_roles:
        return False, f"role: {role}"
    if c.get("german_requirement") == "required":
        level = c.get("german_level") or "unspecified"
        level = UNSPECIFIED_REQUIRED_LEVEL if level in ("unspecified", "none") else level
        if CEFR_RANK.get(level, 4) > CEFR_RANK.get(candidate_level, 2):
            return False, f"German {level} required (you: {candidate_level})"
    country = str(c.get("country") or "unknown").strip().lower()
    if not keep_abroad and country not in ("germany", "deutschland", "de", "unknown", ""):
        return False, f"location: {c.get('country')}"
    return True, "keep"


# ---------------------------------------------------------------------------
# step
# ---------------------------------------------------------------------------
def _load_cache() -> dict:
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def screen_jobs(input_csv: Path = INPUT_CSV, output_csv: Path = OUTPUT_CSV, include_thesis: bool = False,
                keep_abroad: bool = False, use_llm: bool = True) -> int:
    """Screen every job; writes the kept jobs + a full report. Returns the number kept."""
    if not input_csv.exists():
        raise RuntimeError(f"input not found: {input_csv} - run steps/filter_jobs.py first")
    frame = pd.read_csv(input_csv)
    if frame.empty:
        frame.to_csv(output_csv, index=False, encoding="utf-8")
        print("[SCREEN] no jobs to screen")
        return 0

    candidate_level = candidate_german_level()
    token = load_first_key() if use_llm else ""
    if use_llm and not token:
        print("[SCREEN] no Ollama key found -> rule-based screening only")
    cache = _load_cache()
    rows, keep_mask, calls = [], [], 0
    jobs = frame.to_dict("records")
    print(f"[SCREEN] {len(jobs)} job(s) | your German: {candidate_level} | keep roles: "
          f"{sorted(KEEP_ROLES | ({'thesis'} if include_thesis else set()))}"
          + (" | abroad kept" if keep_abroad else " | Germany only"))
    for index, job in enumerate(jobs, 1):
        url = str(job.get("job_url") or "")
        title_str = str(job.get("title") or "")
        cached = cache.get(url)
        is_senior = bool(_SENIOR_TITLE_RE.search(title_str) and not (
            _STUDENT_TITLE_RE.search(title_str) or _INTERN_TITLE_RE.search(title_str)))
        if _NON_TECH_TITLE_RE.search(title_str) or is_senior:
            classification, source = rule_classification(job), "rule"
        elif cached and cached.get("version") == SCREEN_VERSION and cached.get("source") == "llm":
            classification, source = cached["classification"], "cache"
        elif token:
            classification, source = classify_job(job, token)
            calls += 1
            if source == "llm":
                cache[url] = {"version": SCREEN_VERSION, "source": "llm", "classification": classification,
                              "screened_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                CACHE_PATH.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
        else:
            classification, source = rule_classification(job), "rule"
        keep, reason = decide(classification, str(job.get("title") or ""), candidate_level,
                              include_thesis=include_thesis, keep_abroad=keep_abroad)
        keep_mask.append(keep)
        rows.append({"decision": "keep" if keep else "drop", "reason": reason, "source": source,
                     "title": job.get("title", ""), "company": job.get("company", ""),
                     "job_source": job.get("source", ""), **classification, "job_url": url})
        print(f"  [{index}/{len(jobs)}] {'KEEP' if keep else 'drop'} {str(job.get('title', ''))[:55]:55} "
              f"| {reason} ({source})")

    kept = frame[pd.Series(keep_mask, index=frame.index)].reset_index(drop=True)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    kept.to_csv(output_csv, index=False, encoding="utf-8")
    report = pd.DataFrame(rows)
    report.to_csv(REPORT_CSV, index=False, encoding="utf-8")
    # category = first word: "role: senior" -> role, "German C1 required ..." -> German, "location: UK" -> location
    reasons = report[report.decision == "drop"]["reason"].str.split(r"[:\s]").str[0].value_counts().to_dict()
    print(f"[SCREEN] kept {len(kept)}/{len(frame)} | dropped by: {reasons or 'nothing'} | "
          f"LLM calls: {calls} | report -> {REPORT_CSV}")
    return len(kept)


if __name__ == "__main__":
    import argparse
    import traceback

    parser = argparse.ArgumentParser(description="LLM screening: role type, German requirement, country (step 2b)")
    parser.add_argument("--include-thesis", action="store_true", help="also keep Bachelor/Master thesis positions")
    parser.add_argument("--keep-abroad", action="store_true", help="also keep jobs outside Germany")
    parser.add_argument("--no-llm", action="store_true", help="rule-based screening only (no API calls)")
    args = parser.parse_args()
    try:
        screen_jobs(include_thesis=args.include_thesis, keep_abroad=args.keep_abroad, use_llm=not args.no_llm)
    except Exception as exc:  # noqa: BLE001 - CLI entry point: report and exit non-zero
        print(f"[SCREEN] FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise SystemExit(1) from exc
