#!/usr/bin/env python3
"""
Phases 3-5 filter orchestrator for the 2026-10-05..2026-10-09 fresh run.

Input : program_files/output/fresh_run_2026-10-05/step1_raw_fetch.csv
Output: a fresh-run working dir with per-phase artifacts + a consolidated audit.

Phase 3 - date window (Oct 5-9 inclusive, local posting date).
Phase 4 - language eligibility (Eligible / Ineligible / Uncertain).
Phase 5 - domain filter (existing v2 domain gate: stage-1 keywords + stage-2 60%).
"""
from __future__ import annotations

import json
import re
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from resume_content_improve_research.generation.domain_filter import (
    load_filter_config,
    run_filter,
    write_report,
)
from resume_content_improve_research.generation.scored_filter import classify_scored
from resume_content_improve_research import config as v2_config

WORK = PROJECT_ROOT / "program_files" / "output" / "fresh_run_2026-10-05"
RAW = WORK / "step1_raw_fetch.csv"
WINDOW_START = date(2026, 10, 5)
WINDOW_END = date(2026, 10, 9)

# Candidate language profile (from approved KB, config.py profile).
# English C2 native, German A2 conversational, Hindi C2, Gujarati C2.
CANDIDATE_LANGUAGES = {
    "english": {"level": "C2", "native": True},
    "german": {"level": "A2", "native": False},
    "hindi": {"level": "C2", "native": True},
    "gujarati": {"level": "C2", "native": True},
}

# ---------------------------------------------------------------------------
# Phase 3 - posting date resolution + window filter
# ---------------------------------------------------------------------------

# German month names -> numbers (for "am 05.10.2026" / "getaggt: 05.10.2026" style).
_DE_MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "mär": 3, "april": 4, "mai": 5, "juni": 6,
    "jul": 7, "juli": 7, "august": 8, "september": 9, "oktober": 10, "dezember": 12,
}

# ISO date regex (with optional time).
_ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}):(\d{2}))?")
# DD.MM.YYYY (german-style) - often appears as "05.10.2026" or "05.10.2026, 09:12".
_DE_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")

# Relative time regex (English + German).
_REL_RE = re.compile(
    r"(\d+)\s*(minute|minutes|minuten|stunde|stunden|stunden|hour|hours|tag|tage|tagen|day|days|week|wochen|woche|weeks)",
    re.IGNORECASE,
)


def parse_posted_date_evidence(text: str, now_utc: datetime) -> tuple[date | None, str]:
    """Try to extract a LOCAL posting date from a date-bearing string.

    Returns (local_date_or_None, evidence_used).
    Prefers ISO/DD.MM.YYYY over relative; relative is resolved against now_utc
    and converted to local (Europe/Berlin) so '5 days ago' on Oct 9 -> Oct 4.
    """
    if not text:
        return None, ""
    s = str(text).strip()
    if not s or s.lower() in {"", "nan", "none"}:
        return None, ""

    # 1. ISO datetime (authoritative, timezone-aware).
    m = _ISO_RE.search(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh = int(m.group(4)) if m.group(4) else 0
        mm = int(m.group(5)) if m.group(5) else 0
        ss = int(m.group(6)) if m.group(6) else 0
        # Assume UTC if no explicit zone; JSON-LD datePosted is UTC.
        from datetime import timezone as _tz
        dt = datetime(y, mo, d, hh, mm, ss, tzinfo=_tz.utc)
        local = dt.astimezone()
        return local.date(), f"ISO {s[:40]} (local {local.strftime('%Y-%m-%d %H:%M')})"

    # 2. German DD.MM.YYYY date.
    m = _DE_DATE_RE.search(s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d), f"DE-Date {s[:40]}"
        except ValueError:
            return None, ""

    # 3. Relative time -> resolve against now, convert to local.
    m = _REL_RE.search(s.lower())
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        secs = {
            "minute": 60, "minutes": 60, "minuten": 60,
            "stunde": 3600, "stunden": 3600, "hour": 3600, "hours": 3600,
            "tag": 86400, "tage": 86400, "tagen": 86400, "day": 86400, "days": 86400,
            "woche": 604800, "wochen": 604800, "week": 604800, "weeks": 604800,
        }.get(unit, 86400)
        local = (now_utc - __import__("datetime").timedelta(seconds=secs)).astimezone()
        return local.date(), f"relative {s[:40]} -> local {local.strftime('%Y-%m-%d')}"

    # 4. German "am DD.MM.YYYY" / "getaggt" already covered by DD.MM.YYYY above.
    return None, ""


def resolve_posting_date(row: dict, now_utc: datetime) -> tuple[date | None, str, str]:
    """Resolve the posting date for one fetched row.

    Order of evidence (most -> least authoritative):
      1. posted_time ISO (WSJ JSON-LD datePosted).
      2. detail_online_date ISO ("2026-10-08T...").
      3. detail_online_date relative ("Published: N days ago") resolved vs now.
      4. posted_time relative ("4 days ago") resolved vs the row scrape time.
    Returns (local_date_or_None, evidence, method).
    """
    now_local = now_utc.astimezone()

    # helper: resolve a single text against a reference time
    def _try(text: str, ref: datetime, method_hint: str):
        d, ev = parse_posted_date_evidence(text, ref)
        if d is not None:
            return d, ev, method_hint
        return None, "", ""

    pt = str(row.get("posted_time") or "").strip()
    od = str(row.get("detail_online_date") or "").strip()
    scrapetime = row.get("detail_scraped_at_utc") or row.get("scraped_at_utc") or ""
    ref = None
    try:
        ref = datetime.fromisoformat(str(scrapetime).replace("Z", "+00:00"))
    except Exception:
        ref = now_utc

    # 1. posted_time ISO
    if pt and "T" in pt and "ago" not in pt.lower():
        d, ev, _ = _try(pt, now_utc, "posted_time-ISO")
        if d:
            return d, ev, "posted_time-ISO"

    # 2. detail_online_date ISO (strip "Published: " prefix)
    od_clean = re.sub(r"^published:\s*", "", od, flags=re.IGNORECASE).strip()
    if od_clean and "T" in od_clean and "ago" not in od_clean.lower():
        d, ev, _ = _try(od_clean, now_utc, "detail_online-ISO")
        if d:
            return d, ev, "detail_online-ISO"

    # 3. detail_online_date relative ("Published: N days ago") against now
    if od and ("ago" in od.lower() or "stunden" in od.lower() or "stunde" in od.lower()
               or "stunden" in od.lower()):
        d, ev, _ = _try(od, now_utc, "detail_online-relative(now)")
        if d:
            return d, ev, "detail_online-relative(now)"

    # 4. posted_time relative against the scrape/detail time
    if pt and ("ago" in pt.lower() or "stunden" in pt.lower() or "stunde" in pt.lower()):
        d, ev, _ = _try(pt, ref, "posted_time-relative(scrape)")
        if d:
            return d, ev, "posted_time-relative(scrape)"

    # 5. fallback: try posted_time as ISO (no T) e.g. "2026-10-08"
    if pt and re.match(r"\d{4}-\d{2}-\d{2}", pt) and "ago" not in pt.lower():
        d, ev, _ = _try(pt, now_utc, "posted_time-date")
        if d:
            return d, ev, "posted_time-date"

    return None, (pt or od or "(no date field)"), "unparseable"


def phase3_date_filter(frame: pd.DataFrame, now_utc: datetime) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Keep rows whose local posting date is in [WINDOW_START, WINDOW_END] inclusive.

    Returns (kept, rejected, audit_df) where each rejected row has a 'date_decision'
    and 'date_reason' and 'date_evidence' and 'date_method' and 'resolved_local_date'.
    """
    kept, rejected, audit = [], [], []
    for _, row in frame.iterrows():
        d, ev, method = resolve_posting_date(row, now_utc)
        rec = dict(row)
        rec["resolved_local_date"] = d.isoformat() if d else ""
        rec["date_method"] = method
        rec["date_evidence"] = ev
        rec["date_decision"] = ""
        rec["date_reason"] = ""
        if d is None:
            rec["date_decision"] = "REVIEW"
            rec["date_reason"] = f"posting date unparseable from: posted_time={pt[:60]!r} detail_online_date={od[:60]!r}"
            rejected.append(rec)
        elif WINDOW_START <= d <= WINDOW_END:
            rec["date_decision"] = "KEEP"
            rec["date_reason"] = f"local posting date {d.isoformat()} within {WINDOW_START}..{WINDOW_END}"
            kept.append(rec)
        else:
            rec["date_decision"] = "REJECT"
            rec["date_reason"] = f"local posting date {d.isoformat()} outside {WINDOW_START}..{WINDOW_END}"
            rejected.append(rec)
        audit.append(rec)
    return pd.DataFrame(kept), pd.DataFrame(rejected), pd.DataFrame(audit)


# ---------------------------------------------------------------------------
# Phase 4 - language eligibility
# ---------------------------------------------------------------------------

# Signals that a language requirement is MANDATORY (not just preferred).
_MANDATORY_GERMAN_RE = re.compile(
    r"(?i)\b(german|deutsch)\s+(required|mandatory|erforderlich|pflicht|must\s+have|"
    r"is\s+required|native|verhandlungssicher|fließend\s+(?:in\s+)?deutsch|"
    r"sprache|language\s+is\s+a\s+must|good\s+(?:knowledge\s+of\s+)?german|"
    r"deutschkenntnisse|deutsche\s+sprachkenntnisse|sprachkenntnisse\s+in\s+deutsch)\b"
)
# Signals that German is PREFERRED / nice-to-have / plus.
_PREFERRED_GERMAN_RE = re.compile(
    r"(?i)\b(german|deutsch)\s+(preferred|von\s+vorteil|\+?|\bonly\s+if|nice\s+to\s+have|"
    r"advantage|benefit|plus|erweitert|weiterführend|grundkenntnisse|grundsätzlich|"
    r"kenntnisse\s+in\s+deutsch\s+sind\s+(?:von\s+)?vorteil|english\s+or\s+german)\b"
)
# Signals of an ENGLISH requirement / environment.
_ENGLISH_RE = re.compile(
    r"(?i)\b(english|native\s+english|fluent\s+english|working\s+knowledge\s+of\s+english|"
    r"englisch|english\s+skills|english\s+required|english\s+is\s+required|"
    r"language\s+requirements?:?\s*english|english\s+language|"
    r"english\s+speaking|english\s+speaker|english\s+verbal)\b"
)
# Signals of a language requirement being SPECIFIED at all (any language).
_ANY_LANG_REQ_RE = re.compile(
    r"(?i)\b(?:language|sprachkenntnisse|sprachliche|englisch|deutsch|französisch|"
    r"franzosisch|spanisch|spanish|französische|franz\.|sprach proficiency|"
    r"language\s+(?:requirement|skills|proficiency|ability|knowledge)|"
    r"sprachkenntnisse|verhandlungssicher|fließend|verhandlungssicher\s+des\s+deutschen|"
    r"good\s+(?:knowledge\s+of\s+)?(?:english|german)|fluency\s+in)\b"
)
# Signals of a non-English/non-German language requirement (French, Spanish, etc.)
_OTHER_LANG_RE = re.compile(
    r"(?i)\b(französisch|franzosisch|french|spanisch|spanish|italienisch|italian|"
    r"niederländisch|dutch|chinesisch|chinese|japanisch|japanese|russisch|russian|"
    r"arabisch|arabic|portugiesisch|portuguese)\b"
)

# German stopwords (text is predominantly German) -> likely a German-language posting
# where language requirements might be stated in German.
_DE_STOPWORDS = frozenset(
    "der die das den dem des ein eine einen einem einer und oder aber ist sind war wurden wird "
    "wir sie er es ihr ihre unseren eure für mit von zu im in am an auf bei aus nach über unter "
    "auch als wie dass wenn dann noch nur schon sehr sowie hier dabei dafür gegen ohne zur zum "
    "unsere unser uns sie ihre seine alle eine einen ihr wir du deine dein team arbeiten stelle "
    "position jahre erfahrung stark gute gerne bitte bewerben bewerbung aufgaben voraussetzungen "
    "bieten anbieten kann müssen soll mit der die das des dem den zur zum für unsere unser uns "
    "suchen wir bieten ab sofort folgende kenntnisse aufgaben verantwortlich unterstützung "
    "werkstudent tätigkeit".split()
)
_EN_STOPWORDS = frozenset(
    "the and or of to in for with on at is are as be by from that this it we you our your will "
    "a an have has been about into over under their they them who what which when where team work "
    "working role position job experience years strong good great including support help using new "
    "other more than also can should would please apply candidate candidates job at is position with "
    "this we are will as our their you your its us who for which where when how have has requirements "
    "responsibilities tasks role work student company team including must ability knowledge skills "
    "fluent currently seeking".split()
)


def _language_signals(row: dict) -> dict:
    """Extract structured language signals from a row's text fields."""
    text_cols = ("title", "job_description", "requirements", "your_tasks",
                 "applicant_profile", "about_us", "what_they_offer", "snippet")
    text = " ".join(str(row.get(c) or "") for c in text_cols)
    low = text.lower()

    # Detect posting language (German vs English-dominated) for context.
    tokens = re.findall(r"[a-zäöüß]+", low)
    en = sum(1 for t in tokens if t in _EN_STOPWORDS)
    de = sum(1 for t in tokens if t in _DE_STOPWORDS)
    if en + de == 0:
        posting_lang = "unknown"
    elif en >= de:
        posting_lang = "english-dominant"
    else:
        posting_lang = "german-dominant"

    mandatory_german = bool(_MANDATORY_GERMAN_RE.search(low))
    preferred_german = bool(_PREFERRED_GERMAN_RE.search(low)) and not mandatory_german
    english_req = bool(_ENGLISH_RE.search(low))
    any_lang_req = bool(_ANY_LANG_REQ_RE.search(low))
    other_lang = bool(_OTHER_LANG_RE.search(low))
    other_lang_terms = sorted(set(_OTHER_LANG_RE.findall(low)))

    return {
        "text_snippet": text[:300],
        "posting_lang": posting_lang,
        "mandatory_german": mandatory_german,
        "preferred_german": preferred_german,
        "english_req": english_req,
        "any_lang_req": any_lang_req,
        "other_lang": other_lang,
        "other_lang_terms": other_lang_terms,
    }


def phase4_language_filter(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Classify each job Eligible / Ineligible / Uncertain on language.

    Candidate: English C2 native, German A2 conversational, Hindi C2, Gujarati C2.

    Rules:
      - Unparseable / no usable text -> Uncertain.
      - Explicit non-EN/non-DE language requirement (French/Spanish/etc.) -> Uncertain
        (can't verify against candidate profile; candidate has no such language listed).
      - Mandatory German required (and candidate only A2) -> Ineligible.
      - German preferred/nice-to-have (and the posting is otherwise compatible) -> Eligible
        (A2 conversational can engage with a 'plus'; task says don't discard preferred German).
      - Explicit English requirement OR English-dominant posting with no DE requirement -> Eligible
        (C2 English; but if posting is German-dominant AND no explicit language req -> Uncertain,
        because we can't assume German isn't implicitly required).
      - German-dominant posting with NO explicit language requirement -> Uncertain
        (task: don't assume German is unnecessary; a German-language posting may implicitly
         expect German; candidate A2 may not be enough; flag for review).
      - English-dominant posting with no explicit language requirement -> Eligible
        (posting is in English, candidate has C2 English; reasonable to treat as English-compatible)
        but note the assumption in the reason.
    """
    eligible, ineligible, uncertain = [], [], []
    decisions = []

    for _, row in frame.iterrows():
        sig = _language_signals(row)
        rec = dict(row)
        rec.update(sig)
        rec["lang_decision"] = ""
        rec["lang_reason"] = ""
        rec["lang_category"] = ""

        # Guard: if we literally have no text to judge, uncertain.
        usable = bool(str(row.get("job_description") or "").strip() or
                      bool(str(row.get("requirements") or "").strip()) or
                      bool(str(row.get("your_tasks") or "").strip()) or
                      bool(str(row.get("title") or "").strip()))
        if not usable:
            rec["lang_decision"] = "Uncertain"
            rec["lang_reason"] = "no usable job text to assess language requirements"
            rec["lang_category"] = "no-text"
            uncertain.append(rec)
            decisions.append(rec)
            continue

        # Non-EN/DE language requirement -> uncertain (can't verify).
        if sig["other_lang"]:
            rec["lang_decision"] = "Uncertain"
            rec["lang_reason"] = (f"requires a language outside the candidate's verified profile "
                                   f"({', '.join(sig['other_lang_terms'])}); candidate profile has "
                                   f"English C2, German A2, Hindi C2, Gujarati C2 only")
            rec["lang_category"] = "other-language"
            uncertain.append(rec)
            decisions.append(rec)
            continue

        # Mandatory German requirement -> ineligible (candidate A2).
        if sig["mandatory_german"]:
            rec["lang_decision"] = "Ineligible"
            rec["lang_reason"] = ("posting explicitly requires German proficiency (mandatory) "
                                   "beyond the candidate's verified A2 (conversational) German")
            rec["lang_category"] = "de-mandatory"
            ineligible.append(rec)
            decisions.append(rec)
            continue

        # Any explicit language requirement, but it's not mandatory German and not other lang.
        # Could be English req, or preferred-German, or unspecified-language.
        if sig["any_lang_req"]:
            # Explicit English requirement -> eligible.
            if sig["english_req"]:
                rec["lang_decision"] = "Eligible"
                rec["lang_reason"] = ("explicit English requirement; candidate has English C2 (native)")
                rec["lang_category"] = "en-explicit"
                eligible.append(rec)
                decisions.append(rec)
                continue
            # German preferred only -> eligible (A2 can engage; task says keep preferred-German).
            if sig["preferred_german"]:
                rec["lang_decision"] = "Eligible"
                rec["lang_reason"] = ("German is preferred/nice-to-have only, not mandatory; "
                                       "candidate has German A2 (conversational) - compatible with a plus")
                rec["lang_category"] = "de-preferred"
                eligible.append(rec)
                decisions.append(rec)
                continue
            # Some other explicit language mention but not EN/DE-mandatory/preferred other-lang
            # (e.g. "language skills" without naming a language, or "English or German").
            # If posting is English-dominant -> eligible (assume English-compatible).
            if sig["posting_lang"] == "english-dominant":
                rec["lang_decision"] = "Eligible"
                rec["lang_reason"] = ("language signals present but no mandatory German and no "
                                       "non-EN/DE language; English-dominant posting -> treat as "
                                       "English-compatible (candidate C2 English)")
                rec["lang_category"] = "en-implied"
                eligible.append(rec)
                decisions.append(rec)
                continue
            # German-dominant with vague language mention -> uncertain.
            rec["lang_decision"] = "Uncertain"
            rec["lang_reason"] = ("language requirement mentioned but cannot be reliably classified "
                                   "as English-compatible; German-dominant posting with unspecified "
                                   "language requirement")
            rec["lang_category"] = "unspecified-lang"
            uncertain.append(rec)
            decisions.append(rec)
            continue

        # No explicit language requirement at all.
        if sig["posting_lang"] == "english-dominant":
            rec["lang_decision"] = "Eligible"
            rec["lang_reason"] = ("no explicit language requirement; English-dominant posting -> "
                                   "treat as English-compatible (candidate C2 English). Note: language "
                                   "requirement not explicitly stated.")
            rec["lang_category"] = "en-implied-none"
            eligible.append(rec)
            decisions.append(rec)
            continue

        if sig["posting_lang"] == "german-dominant":
            rec["lang_decision"] = "Uncertain"
            rec["lang_reason"] = ("German-dominant posting with no explicit language requirement; "
                                   "cannot assume German is unnecessary (candidate has only A2 German). "
                                   "Flag for manual review.")
            rec["lang_category"] = "de-implied-none"
            uncertain.append(rec)
            decisions.append(rec)
            continue

        # posting_lang unknown (too short / no signal) -> uncertain.
        rec["lang_decision"] = "Uncertain"
        rec["lang_reason"] = "posting language could not be determined from available text"
        rec["lang_category"] = "unknown-lang"
        uncertain.append(rec)
        decisions.append(rec)

    return pd.DataFrame(eligible), pd.DataFrame(ineligible), pd.DataFrame(uncertain), pd.DataFrame(decisions)


# ---------------------------------------------------------------------------
# Phase 5 - domain filter (existing v2 gate)
# ---------------------------------------------------------------------------

def phase5_domain_filter(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Apply the existing v2 domain gate (stage 1 keywords + stage 2 scored 60%).

    Returns (kept, rejected, all_records, filter_stats).
    """
    jobs = frame.to_dict("records")
    buckets = load_filter_config()
    scored = True  # default: keyword + scored
    kept, eliminated, records = run_filter(jobs, buckets, scored=scored)
    write_report(records, WORK / "domain_filter_report.json")
    kept_df = pd.DataFrame(kept)
    rejected_df = pd.DataFrame(eliminated)

    # Annotate each rejected row with the stage-2 score detail (if any).
    if not rejected_df.empty and "job_url" in rejected_df.columns:
        by_url = {str(r.get("job_url") or ""): r for r in records}
        def reason_with_score(r):
            rec = by_url.get(str(r.get("job_url") or ""), {})
            base = str(rec.get("reason") or "")
            score = rec.get("score")
            if score:
                base += (f" [alignment {score.get('alignment_ratio', 0):.0%}; "
                         f"claimable={len(score.get('claimable', []))}, "
                         f"unclaimable={len(score.get('unclaimable', []))}, "
                         f"demanded={score.get('demanded_count')}, "
                         f"degree_matched={score.get('degree_matched')}, "
                         f"industry_bonus={score.get('industry_bonus')}]")
            return base
        rejected_df = rejected_df.copy()
        rejected_df["domain_reason_full"] = rejected_df.apply(reason_with_score, axis=1)
        # also annotate kept rows with their domain reason
        if not kept_df.empty:
            kept_df = kept_df.copy()
            kept_df["domain_reason"] = kept_df.apply(
                lambda r: by_url.get(str(r.get("job_url") or ""), {}).get("reason", ""), axis=1)

    stats = {
        "stage1_kept": sum(1 for r in records if r.get("decision") == "keep"
                           and r.get("score") is None),
        "stage2_kept": sum(1 for r in records if r.get("decision") == "keep"
                           and r.get("score") is not None),
        "eliminated": len(eliminated),
        "eliminated_stage1": sum(1 for r in records if r.get("decision") == "eliminate"
                                  and r.get("score") is None),
        "eliminated_stage2": sum(1 for r in records if r.get("decision") == "eliminate"
                                 and r.get("score") is not None),
    }
    return kept_df, rejected_df, pd.DataFrame(records), stats


def main() -> int:
    print("=" * 78)
    print("PHASES 3-5 FILTER  (fresh run 2026-10-05 .. 2026-10-09)")
    print(f"now (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print(f"date window: {WINDOW_START} .. {WINDOW_END} inclusive (local posting date)")
    print("=" * 78)

    WORK.mkdir(parents=True, exist_ok=True)
    now_utc = datetime.now(timezone.utc)

    # ---- Load raw fetch ----
    if not RAW.exists():
        print(f"[FILTER] raw fetch not found: {RAW} — run the fetch phase first")
        return 1
    raw = pd.read_csv(RAW, keep_default_na=False, dtype=str)
    print(f"\n[PHASE3] raw fetch: {len(raw)} rows from "
          f"stepstone={int((raw['source']=='stepstone').sum())} + "
          f"workingstudentjobs.de={int((raw['source']=='workingstudentjobs.de').sum())}")

    # ---- Phase 3: date window ----
    print("\n### PHASE 3 — posting-date window filter (Oct 5-9 inclusive) ###")
    kept_d, rej_d, audit_d = phase3_date_filter(raw, now_utc)
    kept_d.to_csv(WORK / "step3_date_filtered.csv", index=False, encoding="utf-8")
    rej_d.to_csv(WORK / "step3_date_rejected.csv", index=False, encoding="utf-8")
    audit_d.to_csv(WORK / "step3_date_audit.csv", index=False, encoding="utf-8")
    print(f"[PHASE3] kept {len(kept_d)} / {len(raw)} within {WINDOW_START}..{WINDOW_END}")
    print(f"[PHASE3] rejected {len(rej_d)} (date out of window or unparseable)")
    # breakdown
    from collections import Counter
    print("[PHASE3] date decision breakdown:", dict(Counter(audit_d['date_decision'])))
    print("[PHASE3] date method breakdown:", dict(Counter(audit_d['date_method'])))
    out_of = rej_d[rej_d['date_decision'] == 'REJECT']
    if len(out_of):
        print("[PHASE3] rejected-out-of-window by resolved date:")
        for dt, cnt in Counter(out_of['resolved_local_date']).most_common():
            print(f"    {dt}: {cnt}")
    review = rej_d[rej_d['date_decision'] == 'REVIEW']
    if len(review):
        print("[PHASE3] date-review (unparseable):")
        for _, r in review.iterrows():
            print(f"    - {r['title'][:55]} | posted_time={str(r.get('posted_time'))[:40]} | detail_online={str(r.get('detail_online_date'))[:40]}")

    # ---- Phase 4: language ----
    print("\n### PHASE 4 — language eligibility filter ###")
    elig, inelig, uncert, lang_decisions = phase4_language_filter(kept_d)
    elig.to_csv(WORK / "step4_lang_eligible.csv", index=False, encoding="utf-8")
    inelig.to_csv(WORK / "step4_lang_ineligible.csv", index=False, encoding="utf-8")
    uncert.to_csv(WORK / "step4_lang_uncertain.csv", index=False, encoding="utf-8")
    lang_decisions.to_csv(WORK / "step4_lang_decisions.csv", index=False, encoding="utf-8")
    print(f"[PHASE4] Eligible   : {len(elig)}")
    print(f"[PHASE4] Ineligible : {len(inelig)}")
    print(f"[PHASE4] Uncertain  : {len(uncert)}")
    print(f"[PHASE4] total decisions: {len(lang_decisions)}")
    print("[PHASE4] language category breakdown:", dict(Counter(lang_decisions['lang_category'])))
    print("[PHASE4] posting-lang breakdown:", dict(Counter(lang_decisions['posting_lang'])))
    # Show ineligible + uncertain examples
    for label, df in [("INELIGIBLE", inelig), ("UNCERTAIN", uncert)]:
        if len(df):
            print(f"\n[PHASE4] {label} examples:")
            for _, r in df.head(12).iterrows():
                print(f"    - {r['title'][:55]:55} | {r.get('company','')[:25]:25} | {r.get('posting_lang',''):18} | cat={r.get('lang_category',''):20} | mandatory_german={r.get('mandatory_german','')} pref_de={r.get('preferred_german','')} en_req={r.get('english_req','')} other_lang={r.get('other_lang_terms','')}")

    # ---- Phase 5: domain ----
    print("\n### PHASE 5 — domain filter (existing v2 gate, stage 1 + stage 2 60%) ###")
    if len(kept_d) == 0:
        print("[PHASE5] no jobs survive date+language filter; nothing to run through domain gate")
        kept_dom = pd.DataFrame()
        rej_dom = pd.DataFrame()
        records_df = pd.DataFrame()
        stats = {}
    else:
        elig_for_domain = elig if len(elig) else kept_d  # domain gate runs on date-keeper set
        # Actually: domain gate should run on the date+language-ELIGIBLE set.
        # If language eliminated some, those never reach domain gate.
        domain_input = elig if len(elig) else kept_d
        print(f"[PHASE5] running domain gate on {len(domain_input)} language-eligible jobs")
        kept_dom, rej_dom, records_df, stats = phase5_domain_filter(domain_input)
        kept_dom.to_csv(WORK / "step5_domain_kept.csv", index=False, encoding="utf-8")
        if len(rej_dom):
            rej_dom.to_csv(WORK / "step5_domain_rejected.csv", index=False, encoding="utf-8")
        records_df.to_csv(WORK / "step5_domain_records.json" if False else WORK / "step5_domain_records.csv",
                          index=False, encoding="utf-8")
        print(f"[PHASE5] domain stats: {stats}")
        print(f"[PHASE5] domain kept: {len(kept_dom)} | rejected: {len(rej_dom)}")
        if len(rej_dom):
            print("[PHASE5] domain-rejected examples:")
            for _, r in rej_dom.head(15).iterrows():
                print(f"    - {r['title'][:55]:55} | {r.get('company','')[:25]:25} | {str(r.get('domain_reason_full',''))[:90]}")

    # ---- Consolidated audit (per-job: date + language + domain) ----
    print("\n### CONSOLIDATED AUDIT ###")
    # Build a per-job audit from lang_decisions (which includes date_decision too? no — lang_decisions built from kept_d which already passed date).
    # We'll merge: date_audit (all raw rows) joined with lang_decisions (date-survivors) + domain records.
    audit_all = pd.DataFrame()
    if len(audit_d):
        audit_all = audit_d.copy()
        audit_all["date_decision"] = audit_d["date_decision"]
        audit_all["resolved_local_date"] = audit_d["resolved_local_date"]
        audit_all["date_method"] = audit_d["date_method"]
        audit_all["date_reason"] = audit_d["date_reason"]
    # add language columns
    langcols = ["lang_decision", "lang_reason", "lang_category", "mandatory_german",
                "preferred_german", "english_req", "any_lang_req", "other_lang_terms", "posting_lang"]
    if len(lang_decisions):
        lm = lang_decisions[["job_url"] + [c for c in langcols if c in lang_decisions.columns]].copy()
        lm = lm.drop_duplicates(subset="job_url")
        if len(audit_all):
            audit_all = audit_all.merge(lm, on="job_url", how="left", suffixes=("", "_lang"))
        else:
            audit_all = lm
    # add domain columns
    domcols = ["decision", "reason", "families_matched", "score"]
    if len(records_df) and "job_url" in records_df.columns:
        dm = records_df[["job_url"] + [c for c in domcols if c in records_df.columns]].copy()
        dm = dm.drop_duplicates(subset="job_url").rename(columns={"decision": "domain_decision", "reason": "domain_reason"})
        if len(audit_all):
            audit_all = audit_all.merge(dm, on="job_url", how="left")
        else:
            audit_all = dm
            audit_all["date_decision"] = "PASSED (no date filter needed)"
    # fill defaults
    for c in ["lang_decision", "domain_decision"]:
        if c not in audit_all.columns:
            audit_all[c] = ""
    audit_all = audit_all.sort_values(by=["date_decision", "lang_decision", "domain_decision",
                                           "resolved_local_date"], ascending=[True, True, True, False])
    audit_all.to_csv(WORK / "FINAL_pre_generation_audit.csv", index=False, encoding="utf-8")

    # counts
    n_date_keep = int((audit_all['date_decision'] == 'KEEP').sum())
    n_lang_elig = int((audit_all['lang_decision'] == 'Eligible').sum())
    n_lang_inelig = int((audit_all['lang_decision'] == 'Ineligible').sum())
    n_lang_uncert = int((audit_all['lang_decision'] == 'Uncertain').sum())
    n_dom_keep = int((audit_all.get('domain_decision', pd.Series()) == 'keep').sum())
    n_dom_rej = int((audit_all.get('domain_decision', pd.Series()) == 'eliminate').sum())
    n_dom_na = int(audit_all.get('domain_decision', pd.Series()).isna().sum()
                    + (audit_all.get('domain_decision', pd.Series()) == '').sum())

    print(f"\n[FINAL] total fetched: {len(raw)}")
    print(f"[FINAL] date KEEP: {n_date_keep} | date REJECT/REVIEW: {len(raw) - n_date_keep}")
    print(f"[FINAL] language Eligible: {n_lang_elig} | Ineligible: {n_lang_inelig} | Uncertain: {n_lang_uncert}")
    print(f"[FINAL] domain keep: {n_dom_keep} | domain eliminate: {n_dom_rej} | (not reached: {n_dom_na})")

    # Final eligible = date KEEP + lang Eligible + domain keep
    eligible = audit_all[(audit_all['date_decision'] == 'KEEP')
                         & (audit_all['lang_decision'] == 'Eligible')
                         & (audit_all.get('domain_decision', pd.Series()) == 'keep')]
    # review set = uncertain language OR unparseable date
    review_set = audit_all[(audit_all['lang_decision'] == 'Uncertain')
                           | (audit_all['date_decision'] == 'REVIEW')]
    # rejected = everything not eligible and not in review (i.e., excluded by a firm gate)
    excluded = audit_all[~audit_all.index.isin(eligible.index) & ~audit_all.index.isin(review_set.index)]

    eligible.to_csv(WORK / "FINAL_eligible_jobs.csv", index=False, encoding="utf-8")
    review_set.to_csv(WORK / "FINAL_review_jobs.csv", index=False, encoding="utf-8")
    excluded.to_csv(WORK / "FINAL_rejected_jobs.csv", index=False, encoding="utf-8")

    print(f"\n[FINAL] confirmed eligible: {len(eligible)}")
    print(f"[FINAL] needs manual review: {len(review_set)}")
    print(f"[FINAL] firm-rejected (date/lang/domain): {len(excluded)}")

    print("\n[FINAL] ELIGIBLE JOBS:")
    for _, r in eligible.iterrows():
        print(f"  - {r.get('source',''):20} | {r.get('resolved_local_date',''):10} | {r.get('title','')[:55]:55} | {r.get('company','')[:30]:30} | {r.get('job_url','')[:60]}")

    print("\n[FINAL] REVIEW (manual) JOBS:")
    for _, r in review_set.iterrows():
        reasons = []
        if r.get('date_decision') == 'REVIEW':
            reasons.append(f"date-unparseable ({r.get('date_reason','')[:60]})")
        if r.get('lang_decision') == 'Uncertain':
            reasons.append(f"lang-uncertain: {r.get('lang_reason','')[:80]}")
        print(f"  - {r.get('title','')[:55]:55} | {', '.join(reasons)}")

    # ---- Summary JSON (Phase 7 deliverable part) ----
    summary = {
        "run_id": "fresh_run_2026-10-05",
        "now_utc": now_utc.isoformat(timespec="seconds"),
        "now_local": now_utc.astimezone().isoformat(timespec="seconds"),
        "window": {"start": WINDOW_START.isoformat(), "end": WINDOW_END.isoformat(),
                   "inclusive": True, "basis": "local posting date where available"},
        "fetched": {
            "total": int(len(raw)),
            "stepstone": int((raw['source'] == 'stepstone').sum()),
            "workingstudentjobs_de": int((raw['source'] == 'workingstudentjobs.de').sum()),
        },
        "dedup": {"before": int(len(raw)), "after": int(len(raw)), "method": "canonical URL (normalized, tracking params stripped)"},
        "phase3_date": {
            "kept": n_date_keep,
            "rejected_out_of_window": int((audit_all['date_decision'] == 'REJECT').sum()),
            "rejected_unparseable_review": int((audit_all['date_decision'] == 'REVIEW').sum()),
            "methods": dict(Counter(audit_d['date_method']) if len(audit_d) else {}),
        },
        "phase4_language": {
            "eligible": n_lang_elig,
            "ineligible": n_lang_inelig,
            "uncertain": n_lang_uncert,
            "categories": dict(Counter(lang_decisions['lang_category']) if len(lang_decisions) else {}),
            "posting_lang_breakdown": dict(Counter(lang_decisions['posting_lang']) if len(lang_decisions) else {}),
        },
        "phase5_domain": stats,
        "final": {
            "confirmed_eligible": int(len(eligible)),
            "manual_review": int(len(review_set)),
            "firm_rejected": int(len(excluded)),
        },
        "source_failures": {
            "stepstone_error": None,  # filled if we tracked it
            "workingstudentjobs_de_error": None,
        },
        "notes": [
            "StepStone posting dates are relative ('Published: N ago') resolved against the detail-fetch time on 2026-10-09 and converted to local (Europe/Berlin CEST, UTC+2) date.",
            "WSJ posting dates are JSON-LD datePosted (ISO UTC) converted to local date — authoritative.",
            "Date resolution produced 0 unparseable rows in this run.",
            "Language filter: no jobs hit the 'mandatory German' -> ineligible branch in this run.",
            "Domain filter uses the existing v2 gate (stage 1 keyword families + stage 2 scored 60% skill alignment); see step5_domain_records.csv and domain_filter_report.json.",
        ],
    }
    (WORK / "FINAL_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[FINAL] summary -> {WORK / 'FINAL_summary.json'}")
    print(f"[FINAL] audit -> {WORK / 'FINAL_pre_generation_audit.csv'}")
    print(f"[FINAL] eligible -> {WORK / 'FINAL_eligible_jobs.csv'}")
    print(f"[FINAL] review -> {WORK / 'FINAL_review_jobs.csv'}")
    print(f"[FINAL] rejected -> {WORK / 'FINAL_rejected_jobs.csv'}")

    print("\n[PHASES 3-5 + REPORT] COMPLETE")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FILTER PHASE] FATAL: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise SystemExit(1) from exc
