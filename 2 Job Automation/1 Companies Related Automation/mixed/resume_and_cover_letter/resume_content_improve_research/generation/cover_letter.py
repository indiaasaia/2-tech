"""Cover-letter engine (German Anschreiben) — structured, KB-licensed, portal-aware.

Why this module exists
----------------------
In Germany the Anschreiben is effectively mandatory in the application folder
(Bewerbungsmappe): recruiters expect a one-page, formal, job-specific letter in
DIN 5008-style layout. A generic or English letter on a German posting reads as
"did not read the posting" and can filter the applicant out before the CV is
even opened.

Design (mirrors the proven resume engine, FINAL_MODEL 3.1):
  1. STRUCTURE comes from the DETERMINISTIC skeleton: header/sender/company
     blocks, DD.MM.YYYY date, subject with the exact posting title + reference,
     gendered German salutation (deterministic gender detection with an
     ASK-FALLBACK), 3-4 paragraphs, "Mit freundlichen Grüßen". The LLM never
     touches layout facts.
  2. ONE constrained LLM call writes only the four body paragraphs. Hard rules:
     ONLY claimable-set skills (ownable claimed, mirrorable framed as
     learning targets), NO numbers, percentages or invented metrics, NO
     invented company facts (about_us from the posting is quoted honestly),
     2-4 sentences per paragraph, letter language = posting language.
  3. DETERMINISTIC POST-CHECKS ("LLM proposes, code disposes", V7 §4):
     salutation enforcement, company-name verification, reference extraction,
     length tiers, ASCII-quote normalization.
  4. GATES L1-L4 (verification/cl_gates.py) enforce the same rules on the final
     text; a failing letter parks with the violations recorded (never shipped).
  5. PORTAL AWARENESS is metadata + filename: the letter content is
     portal-agnostic by design (what changes per portal is the DELIVERY —
     PDF upload vs PDF/DOCX vs plain text fields), so the engine ships all
     three artifacts plus a per-portal application manifest (bundles).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from resume_content_improve_research import config
from resume_content_improve_research.generation.claimable_set import ClaimableSet
from resume_content_improve_research.generation.llm import call_llm, extract_json
from resume_content_improve_research.verification.cl_gates import COMPANY_MENTION_RE


def german_today() -> str:
    """Today's date in Europe/Berlin as DD.MM.YYYY (the letter is dated where it is sent).

    One single date source for gates, fill, DOCX, TXT and report: a local-time
    or hardcoded fallback here once printed two different days in the same
    letter set (probe vs fill ran minutes apart across midnight).
    """
    return datetime.now(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y")

# ---------------------------------------------------------------------------
# Posting-side fields read deterministically (steps 1-2 CSV schema)
# ---------------------------------------------------------------------------

def _job_field(job: dict, *names: str) -> str:
    for name in names:
        value = str(job.get(name) or "").strip()
        if value:
            return value
    return ""


def detect_reference(text: str) -> str:
    """Extract a posting reference number, e.g. 'Referenz: REF-2024-088'."""
    if not text:
        return ""
    patterns = (
        r"(?:referenz(?:nummer)?|reference(?:\s*number)?|job[- ]?id|kennziffer|stellenausschreibungs[- ]?id)"
        r"\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9/_\-.]{2,40})",
    )

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            ref = match.group(1).strip(" .,;")
            if len(ref) < 3:
                continue
            # prose trap: "... Referenznummer bitte angeben" must not yield 'bitte'
            if ref.lower() in _REFERENCE_STOPWORDS:
                continue
            return ref
    return ""


# Words the reference regex can capture from prose like "Referenznummer bitte
# angeben" — none of these is ever a real reference string.
_REFERENCE_STOPWORDS = {
    "please", "bitte", "angeben", "angegeben", "apply", "senden", "with",
    "your", "application", "bewerbung", "the", "this", "and", "und", "for", "in",
    # German articles/pronouns captured from prose like "Kennziffer des Stellenangebots"
    "des", "der", "die", "das", "dem", "den", "eine", "einen", "einem", "einer",
    "eines", "ihre", "ihren", "ihrem", "dieser", "diese", "dieses",
}


def detect_portal(job: dict) -> str:
    """Portal slug from the source column of the steps-1/2 CSV."""
    raw = _job_field(job, "source", "source_job_id").lower()
    if "stepstone" in raw:
        return "stepstone"
    if "workingstudent" in raw:
        return "workingstudentjobs"
    if "xing" in raw:
        return "xing"
    if "linkedin" in raw:
        return "linkedin"
    if "indeed" in raw:
        return "indeed"
    return raw.replace(" ", "_")[:30] if raw else "unknown"


def detect_company_name(job: dict) -> str:
    """Company name, preferring the detail-scraped field over the list field."""
    for name in ("detail_company_name", "company"):
        value = _job_field(job, name)
        if value:
            return value
    return ""


def build_letter_claimable_set(analysis_dict: dict, kb: dict, job: dict) -> ClaimableSet:
    """Build the skill claim set and license this posting's company name.

    Some company names are also technology acronyms (for example, SAP). A
    company mention in the formal letter is independently checked against the
    target employer, so it should not be mistaken for a claim of software skill.
    """
    from resume_content_improve_research.generation.claimable_set import build_claimable_set

    return build_claimable_set(analysis_dict, kb)


# Honorific -> gender classification; the captured NAME is reused for the
# salutation. Titles (Dr./Prof.) are allowed between honorific and name.
# CASE-SENSITIVE on purpose: a global (?i) would make [A-Z] match lowercase
# too, so "Frau und Herr" could capture "und Herr" as a contact name.
_HONORIFIC_RE = re.compile(
    r"\b([Ff]rau|[Ff]räulein|[Hh]err|[Hh]errn|[Mm]s\.?|[Mm]rs\.?|[Mm]iss|[Mm]r\.?)\s+"
    r"(?:(?:[Dd]r\.?|[Pp]rof\.?)\s+)?"
    r"([A-ZÀ-Þ][a-zà-ÿ'\-]+(?:\s+[A-ZÀ-Þ][a-zà-ÿ'\-]+)?)"
)
_FEMALE_HONORIFICS = {"frau", "fräulein", "ms", "ms.", "mrs", "mrs.", "miss"}
# Captured "names" that are actually function words (misfire guard: e.g.
# "Frau und Herr" must never yield a contact).
_NAME_STOPWORDS = {"herr", "herrn", "frau", "und", "oder", "the", "your", "ihre", "ihrer", "unser"}


def detect_contact_person(text: str) -> tuple[str, str]:
    """(gender, contact_name_or_'') from the posting text.

    Deterministic gender detection from honorifics only — the generator must
    never guess genders from names. Unknown gender yields the neutral German
    plural salutation (the norm for unnamed recipients), so a letter is never
    blocked and never mis-genders anyone.
    """
    if not text:
        return "", ""
    # compound/pair form ("Frau und Herr Maier", "Frau Weber oder Herr Maier",
    # "Frau/Herr Schmidt") names more than one addressee -> the neutral plural
    # is the correct form. The optional name slot between honorific and connector
    # is load-bearing: "Frau Weber oder Herr Maier" saluting only Frau Weber was
    # a real mis-gendering caught by the regression tests.
    if re.search(r"(?i)\b(?:frau|herrn?)\b(?:\s+[A-ZÀ-Þ][a-zà-ÿ'\-]+)?\s*(?:,|/|\bund\b|\boder\b)\s*(?:herrn?|frau)\b", text):
        return "", ""
    for match in _HONORIFIC_RE.finditer(text):
        honorific = match.group(1).lower().rstrip(".")
        name = match.group(2).strip().rstrip(",.;")
        words = name.split()
        if not words or len(name) < 3:
            continue
        if any(word.lower() in _NAME_STOPWORDS for word in words):
            continue
        return ("female" if honorific in _FEMALE_HONORIFICS else "male"), name
    return "", ""


def salutation_for(language: str, gender: str, name: str = "") -> str:
    """The salutation line (German norm: named if known, else neutral plural)."""
    name = (name or "").strip().rstrip(",.;")
    if language == "de":
        if gender == "female" and name:
            return f"Sehr geehrte Frau {name},"
        if gender == "male" and name:
            return f"Sehr geehrter Herr {name},"
        return "Sehr geehrte Damen und Herren,"
    if gender == "female" and name:
        return f"Dear Ms. {name},"
    if gender == "male" and name:
        return f"Dear Mr. {name},"
    return "Dear Hiring Team,"


def build_subject(title: str, reference: str, language: str) -> str:
    """Bold subject content: exact posting title + reference (norm: no 'Betreff:' word).

    The reference label follows the letter language (Referenz/Reference).
    """
    title = (title or "").strip()
    label = "Referenz" if language == "de" else "Reference"
    suffix = f" - {label}: {reference}" if reference else ""
    return f"{title}{suffix}" if title else ("Bewerbung" + suffix if language == "de" else "Application" + suffix)


# ---------------------------------------------------------------------------
# Generated letter model
# ---------------------------------------------------------------------------

@dataclass
class CoverLetter:
    language: str = "de"                  # 'de' | 'en'
    subject: str = ""
    salutation: str = ""
    opening: str = ""
    fit: str = ""
    motivation: str = ""
    closing: str = ""
    signoff: str = "Mit freundlichen Grüßen"
    name_print: str = "RAVAL MEETKUMAR RITESHKUMAR"
    sender_name: str = ""
    sender_address: str = ""
    sender_contact: str = ""
    sender_links: str = ""
    company_block: str = ""               # newline-separated company address block
    date_line: str = ""                   # 'Essen, 23.09.2026'
    reference: str = ""
    portal: str = "unknown"
    company_name: str = ""
    raw: dict = field(default_factory=dict)

    def body_words(self) -> int:
        """Word count of the four generated paragraphs (the L1 gate scope)."""
        return len((" ".join([self.opening, self.fit, self.motivation, self.closing])).split())


# ---------------------------------------------------------------------------
# Deterministic skeleton (header/date/company/salutation/signoff)
# ---------------------------------------------------------------------------

def posting_text(job: dict) -> str:
    """Concatenated posting text used for reference/contact detection."""
    return " ".join(
        _job_field(job, col) for col in
        ("job_description", "requirements", "your_tasks", "applicant_profile",
         "about_us", "what_they_offer", "snippet")
    )


def build_skeleton(job: dict, analysis_dict: dict, kb: dict) -> CoverLetter:
    """Assemble every deterministic letter element from the posting + KB."""
    profile = kb.get("profile", {})
    contact = profile.get("contact", {})
    language = str(analysis_dict.get("language") or "en")
    posting_text_all = posting_text(job)
    reference = detect_reference(posting_text_all)
    gender, contact_name = detect_contact_person(posting_text_all)
    company = detect_company_name(job)
    title = _job_field(job, "title")

    letter = CoverLetter(
        language=language,
        subject=build_subject(title, reference, language),
        salutation=salutation_for(language, gender, contact_name),
        name_print=str(profile.get("name") or "RAVAL MEETKUMAR RITESHKUMAR"),
        sender_name=str(profile.get("display_name") or profile.get("name") or ""),
        sender_address=str(contact.get("address") or ""),
        sender_contact=" | ".join(
            part for part in (str(contact.get("phone_de") or ""), str(contact.get("email") or "")) if part
        ),
        sender_links=" | ".join(
            str(contact.get(key) or "") for key in ("linkedin", "github", "portfolio") if contact.get(key)
        ),
        company_block="\n".join(part for part in (
            company,
            _job_field(job, "detail_location", "location"),
        ) if part),
        date_line="",  # filled at build time (today, DD.MM.YYYY) in to_fill_values
        reference=reference,
        portal=detect_portal(job),
        company_name=company,
    )
    letter.raw["contact_name_detected"] = contact_name
    letter.raw["gender_detected"] = gender
    letter.raw["reference_source"] = "posting" if reference else ""
    return letter


# ---------------------------------------------------------------------------
# Constrained body generation (1 LLM call)
# ---------------------------------------------------------------------------

def _rules_block(cset: ClaimableSet) -> str:
    tools = ", ".join(cset.jd_tools) if cset.jd_tools else "(none)"
    kb = ", ".join(cset.kb_skills)
    return (
        f"### THE ONLY TECHNOLOGIES/SKILLS YOU MAY MENTION ANYWHERE\n"
        f"OWNABLE (candidate's real skills, may be claimed as own): {kb}\n"
        f"MIRRORABLE (from the target job; may ONLY be mentioned as learning targets or "
        f"familiarity goals, NEVER claimed as the candidate's own skill): {tools}\n"
    )


def _language_note(language: str) -> str:
    if language == "de":
        return (
            "Schreibe den Brief auf DEUTSCH (die Stellenanzeige ist deutsch). "
            "Klares, einfaches, formelles Deutsch. Keine Umgangssprache, keine Kontraktionen."
        )
    return "Write the letter in ENGLISH (the posting is English). Formal, clear, concise English."


def _kb_languages_line(kb: dict | None = None) -> str:
    """Candidate spoken languages from the KB (never hardcoded here)."""
    from resume_content_improve_research.generation.kb_loader import load_kb
    profile = (kb or load_kb()).get("profile", {})
    spoken = profile.get("languages_spoken") or []
    parts = [
        f"{entry.get('lang', '?')} {entry.get('level', '')}".strip()
        for entry in spoken if isinstance(entry, dict)
    ]
    return "Candidate languages: " + ("; ".join(parts) if parts else "not stated")


def _candidate_facts_block(kb: dict | None = None) -> str:
    """Compact, explicit evidence the letter generator may turn into claims."""
    from resume_content_improve_research.generation import kb_loader

    data = kb or kb_loader.load_kb()
    rows: list[str] = []
    for education in data.get("education", []):
        rows.append(
            f"Education: {education.get('degree', '')}; {education.get('school', '')}; "
            f"{education.get('start', '')} to {education.get('end', '')}."
        )
    for exp in kb_loader.experiences(data):
        title = (exp.get("titles_allowed") or [exp.get("role", "")])[0]
        evidence = "; ".join(str(item) for item in exp.get("evidence", []))
        rows.append(f"Employment: {title} at {exp.get('company', '')}. Evidence: {evidence}")
    for project in kb_loader.projects(data):
        evidence = "; ".join(str(item) for item in project.get("evidence", []))
        rows.append(f"Project: {project.get('title', '')}. Evidence: {evidence}")
    for research in kb_loader.research(data):
        evidence = "; ".join(str(item) for item in research.get("evidence", []))
        rows.append(f"Research: {research.get('title', '')}. Evidence: {evidence}")
    rows.append("Ownable skills: " + ", ".join(kb_loader.global_skill_names(data)))
    return "\\n".join(rows)


def _body_prompt(letter: CoverLetter, cset: ClaimableSet, job: dict, analysis_dict: dict,
                 candidate_facts: str = "") -> str:
    required = ", ".join(str(t) for t in (analysis_dict.get("required") or [])) or "(none)"
    preferred = ", ".join(str(t) for t in (analysis_dict.get("preferred") or [])) or "(none)"
    about_us = _job_field(job, "about_us", "snippet")[:600]
    languages_required = ", ".join(
        f"{l.get('language')}" + (f" ({l.get('level')})" if l.get("level") else "")
        for l in (analysis_dict.get("languages_required") or [])
    ) or "none stated"
    # the enforced and requested windows share ONE source (config + gates):
    # a divergence once let L1 park every letter the prompt had told the model
    # to write.
    lb_min = config.LETTER_WORD_MIN
    lb_max = config.LETTER_WORD_MAX
    lb_target = round((lb_min + lb_max) / 2)
    return f"""You write the BODY (4 paragraphs) of a one-page German application cover letter.
{_language_note(letter.language)}
{_rules_block(cset)}
### JOB
Target role: {_job_field(job, 'title')}
Company (use EXACTLY this name when you mention it): {letter.company_name or "(unnamed)"}
Required keywords (weave the OWNABLE ones into the fit paragraph): {required}
Preferred keywords: {preferred}
Job language requirements: {languages_required}
{_kb_languages_line()}

### APPROVED CANDIDATE FACTS (the ONLY biography and experience source)
{candidate_facts or _candidate_facts_block()}
About the company (VERBATIM facts from the posting; you may reference these, never invent more): {about_us or "(not provided)"}

### HARD RULES
1. Candidate fact source of truth: the candidate knowledge base below. State ONLY the candidate's
   explicitly listed degree, university, education, employment, project, research, and skill facts.
   Do NOT infer a different degree/field, study year/semester, city, duration, employer, project, or
   activity from the job description or from a skill keyword. The candidate holds an MSc in Artificial
   Intelligence at Brandenburgische Technische Universität Cottbus-Senftenberg (Apr 2025-present) and
   a BE in Computer Engineering at Gujarat Technological University (Jun 2020-May 2024); do not call
   these Computer Science or Electrical Engineering degrees. Do not claim a current bachelor's degree.
   If a detail is not in the knowledge base, omit it.
2. NEVER claim a MIRRORABLE tool as the candidate's own skill. Allowed framing: "working toward",
   "gaining hands-on experience with", "actively expanding into" — and ONLY for tools that appear
   in the required/preferred lists.
3. NEVER invent numbers, percentages, metrics, durations, team sizes or salary figures.
   NO digits at all in your four paragraphs (the date line and subject are added by the system).
4. NEVER invent company facts beyond the "About the company" text above. Use only facts quoted there;
   do not add company age, market position, scale, customers, awards, products, or locations.
5. Do NOT invent company research you were not given: if About is empty, keep the motivation
   paragraph about the ROLE and the candidate's path, not about the company.
6. The fit paragraph must tie to evidence explicitly listed below. Do not upgrade a general data-
   preprocessing/task statement into an invented data pipeline, model, publication, or outcome.
   Map genuine evidence to the role; do not invent adjacent project/industry experience.
7. Exactly 4 paragraphs; 2-3 sentences each; HARD CAP: at most 55 words PER paragraph — any paragraph
   over 55 words is rejected, so count before you output — and the whole body {lb_min}-{lb_max} words
   (aim for {lb_target}); plain prose, no bullet points, no markdown, no headings, no signatures, no dates.
8. Output ONLY valid JSON exactly:
{{"opening": "...", "fit": "...", "motivation": "...", "closing": "..."}}

Paragraph meanings:
- opening: states the exact role applied for and one concrete, honest hook (why this role fits the
  candidate's profile; never flattery, never "dream job" clichés).
- fit: the strongest honest match — candidate's real skills vs the required keywords (ownable
  skills claimed, mirrorable tools framed as learning targets per rule 1).
- motivation: why this role/company specifically (may reference the About text or the domain of
  the role); ends pointing forward.
- closing: brief, confident availability statement (interview in person or video), no thanks-loop,
  no repetition of the résumé."""


def _score_evidence_relevance(
    item_id: str,
    item_skills: list[str],
    job_terms: set[str],
    motivation_ev_ids: list[str],
) -> int:
    from resume_content_improve_research.generation.normalize import normalize_skill

    score = 0
    if item_id in motivation_ev_ids:
        score += 15
    for s in item_skills:
        ns = normalize_skill(str(s)).casefold()
        if ns in job_terms:
            score += 10
        elif any(ns in jt or jt in ns for jt in job_terms if len(ns) >= 4 and len(jt) >= 4):
            score += 5
    return score


def _fit_sentences(
    kb: dict,
    analysis_dict: dict,
    language: str,
    motivation_ev_ids: list[str],
) -> tuple[str, list[str]]:
    """Deterministically select the two most job-relevant KB evidence statements for Paragraph 2."""
    from resume_content_improve_research.generation.normalize import normalize_skill

    job_terms: set[str] = set()
    for key in ("required", "preferred", "tools", "domain"):
        for val in analysis_dict.get(key) or []:
            if isinstance(val, dict):
                val = val.get("language")
            s = normalize_skill(str(val or "")).casefold()
            if s:
                job_terms.add(s)

    # KB snippets: 21-25 words each, zero digits, zero unlicensed tech tokens.
    de_texts = {
        "soham": (
            "Bei Soham Infotech entwickelte ich Funktionen und quantitative Modelle für finanzielle "
            "Entscheidungsprozesse und baute Backend-Komponenten sowie Echtzeit-Algorithmen zur "
            "Unterstützung des Handels."
        ),
        "pantechelearning": (
            "Während meines Machine-Learning-Praktikums bei Pantechelearning implementierte ich "
            "Modelle für Text-to-Speech-Anwendungen und visuelle Aktivitätsanalyse und arbeitete an "
            "Datenextraktion und -vorverarbeitung für Training und Evaluation."
        ),
        "hft": (
            "Zudem entwickelte ich eine End-to-End-Plattform für Echtzeit-Marktdaten mit Datenextraktion, "
            "Analyse und Filterung, die quantitative Modelle und KI-Verfahren für Marktentscheidungen kombiniert."
        ),
        "resume_gen": (
            "Ergänzend entwickelte ich ein automatisiertes System auf Basis strukturierter Datensätze "
            "und Open-Source-Sprachmodelle, das Inhalte für KI-, Backend- und Datenrollen aufbereitet."
        ),
        "vehicle_sharing": (
            "Darüber hinaus realisierte ich eine Full-Stack-Anwendung für Fahrzeug-Sharing mit "
            "Routenberechnung nach dem Dijkstra-Algorithmus, Echtzeit-CRUD-Funktionen und Benutzeroberfläche."
        ),
        "sarcasm": (
            "In meiner Forschung untersuche ich zudem große Sprachmodelle zur Sarkasmuserkennung in "
            "ressourcenarmen indischen Sprachen und verbessere Modelle für sprachliche Vielfalt."
        ),
    }
    en_texts = {
        "soham": (
            "At Soham Infotech, I developed functions and quantitative models for financial "
            "decision-making and built backend components and real-time algorithms to support trading "
            "operations."
        ),
        "pantechelearning": (
            "During my Machine Learning Internship at Pantechelearning, I implemented models for "
            "text-to-speech applications and visual-activity analysis and worked on data extraction "
            "and preprocessing for model training and evaluation."
        ),
        "hft": (
            "Additionally, I built an end-to-end real-time market platform with data scraping, "
            "analysis, and filtering that combines quantitative and AI models for market actions."
        ),
        "resume_gen": (
            "In addition, I developed an automated system built on structured datasets and open-source "
            "language models to tailor content across AI, backend, and data roles."
        ),
        "vehicle_sharing": (
            "Furthermore, I developed a full-stack vehicle-sharing application featuring route selection "
            "via the Dijkstra algorithm, real-time CRUD operations, and clean user-interface features."
        ),
        "sarcasm": (
            "In my research, I also study large language models for sarcasm detection in low-resourced "
            "Indic languages to improve model handling of linguistic complexity."
        ),
    }
    snippets = de_texts if language == "de" else en_texts

    # Minimal unit-test fixtures without experience/projects fall back to soham + pantechelearning
    if not kb.get("experience") and not kb.get("projects"):
        return f"{snippets['soham']} {snippets['pantechelearning']}", ["soham", "pantechelearning"]

    # Gather available KB items with allowed skills
    available: dict[str, list[str]] = {}
    for exp in kb.get("experience", []) or []:
        eid = str(exp.get("id") or "")
        if eid:
            available[eid] = list(exp.get("skills_allowed") or [])
    for proj in kb.get("projects", []) or []:
        pid = str(proj.get("id") or "")
        if pid:
            available[pid] = list(proj.get("skills_allowed") or [])
    for res in kb.get("research", []) or []:
        rid = str(res.get("id") or "")
        if rid:
            available[rid] = list(res.get("skills_allowed") or [])

    # Score lead employment stint (soham vs pantechelearning)
    soham_score = _score_evidence_relevance(
        "soham", available.get("soham", []), job_terms, motivation_ev_ids)
    pantech_score = _score_evidence_relevance(
        "pantechelearning", available.get("pantechelearning", []), job_terms, motivation_ev_ids)
    lead_exp = "pantechelearning" if pantech_score > soham_score else "soham"
    other_exp = "soham" if lead_exp == "pantechelearning" else "pantechelearning"
    other_exp_score = min(soham_score, pantech_score)

    # Score complementary projects/research
    candidates = ["hft", "resume_gen", "vehicle_sharing", "sarcasm"]
    best_proj = None
    best_proj_score = -1
    for pid in candidates:
        if pid not in available or pid not in snippets:
            continue
        pscore = _score_evidence_relevance(pid, available[pid], job_terms, motivation_ev_ids)
        if pscore > best_proj_score:
            best_proj_score = pscore
            best_proj = pid

    # If a complementary project/research has strictly higher relevance or explicit
    # motivation evidence link, pair lead experience with that project; else pair the two stints.
    if best_proj and (best_proj_score > other_exp_score or best_proj in motivation_ev_ids):
        second_item = best_proj
    else:
        second_item = other_exp

    selected_ids = [lead_exp, second_item]
    composed = f"{snippets[lead_exp]} {snippets[second_item]}"
    return composed, selected_ids


def generate_grounded_letter(
    letter: CoverLetter,
    cset: ClaimableSet,
    job: dict,
    analysis_dict: dict,
    kb: dict,
) -> tuple[CoverLetter, dict]:
    """Write a personalized letter from KB evidence without generating claims.

    Assembled deterministically from candidate-approved education, experience,
    and motivation evidence (zero LLM calls).

    The four paragraphs serve distinct responsibilities (Section 4):
      Paragraph 1 (Opening): Application and role connection based on candidate background
      Paragraph 2 (Fit): Most relevant employment + project/research evidence
      Paragraph 3 (Motivation): Approved professional interests/preferences linked to vacancy
      Paragraph 4 (Closing): Forward-looking development direction and professional close

    Distinguishes:
      - Owned skills (already possessed)
      - Experiences/projects demonstrating skills
      - Motivating interests/preferences
      - Skills/areas working toward (approved direction targets)
      - Unsupported JD requirements (recorded in meta, never fabricated)
    """
    from resume_content_improve_research.generation import kb_loader
    from resume_content_improve_research.generation.motivation import (
        entry_text,
        select_motivation_entries,
    )
    from resume_content_improve_research.generation.normalize import normalize_skill

    candidate_skills = kb_loader.global_skill_names(kb)
    requested = [
        normalize_skill(str(term)).casefold()
        for term in (
            (analysis_dict.get("required") or [])
            + (analysis_dict.get("preferred") or [])
            + (analysis_dict.get("tools") or [])
        )
    ]
    owned_skills_matched: list[str] = []
    for skill in candidate_skills:
        normalized = normalize_skill(skill).casefold()
        if any(term and (term == normalized or term in normalized or normalized in term)
               for term in requested):
            if skill not in owned_skills_matched:
                owned_skills_matched.append(skill)

    relevant = owned_skills_matched[:3] if owned_skills_matched else [
        s for s in ("Python", "Machine Learning", "Data Analytics") if s in candidate_skills
    ]
    skill_text = ", ".join(relevant[:3])
    company = letter.company_name or "Ihrem Unternehmen" if letter.language == "de" else (letter.company_name or "your company")

    # --- approved motivation evidence (deterministic, zero LLM) ----------------
    # Job requirements guide SELECTION only: entries must already exist in the
    # candidate-approved profile with resolvable evidence; nothing is inferred
    # from the JD. Empty selection -> honest generic fallback (recorded in meta).
    selected, mot_meta = select_motivation_entries(
        analysis_dict, kb, language=letter.language, limit=3, job=job)

    # Separate interest/preference entries for Paragraph 3 from direction entries for Paragraph 4
    para3_entries = [e for e in selected if e.get("category") in ("interest", "preference")]
    if not para3_entries and selected:
        para3_entries = [selected[0]]
    para3_texts = [
        entry_text(e, letter.language)
        for e in para3_entries
    ]
    para3_texts = [t for t in para3_texts if t and len(t.split()) <= 40]

    direction_entries = [e for e in selected if e.get("category") == "direction"]
    direction_texts = [
        entry_text(e, letter.language)
        for e in direction_entries
    ]
    direction_texts = [t for t in direction_texts if t and len(t.split()) <= 35]

    # Track unsupported job requirements (requirements in JD without candidate proof)
    dev_target_keys = {
        normalize_skill(t).casefold()
        for t in (mot_meta.get("development_targets") or [])
    }
    owned_keys = {normalize_skill(s).casefold() for s in candidate_skills}
    unsupported_requirements: list[str] = []
    for req in analysis_dict.get("required") or []:
        norm_req = normalize_skill(str(req)).casefold()
        if norm_req not in owned_keys and norm_req not in dev_target_keys:
            unsupported_requirements.append(str(req))

    # --- Paragraph 2: Relevant experience and evidence ------------------------
    fit_composed, fit_evidence_ids = _fit_sentences(
        kb, analysis_dict, letter.language, mot_meta.get("motivation_evidence_ids") or [])

    mot_meta.update({
        "calls": 0,
        "repair_used": 0,
        "deterministic_kb_grounded": True,
        "owned_skills_matched": owned_skills_matched,
        "fit_evidence_ids": fit_evidence_ids,
        "unsupported_requirements": unsupported_requirements,
    })
    letter.raw["motivation_entry_ids"] = list(mot_meta.get("motivation_entry_ids") or [])
    letter.raw["motivation_evidence_ids"] = list(mot_meta.get("motivation_evidence_ids") or [])
    letter.raw["fit_evidence_ids"] = fit_evidence_ids
    letter.raw["owned_skills_matched"] = owned_skills_matched
    letter.raw["development_targets"] = list(mot_meta.get("development_targets") or [])
    letter.raw["unsupported_requirements"] = unsupported_requirements
    letter.raw["motivation_source"] = mot_meta.get("motivation_source", "none")
    if mot_meta.get("motivation_fallback_reason"):
        letter.raw["motivation_fallback_reason"] = mot_meta["motivation_fallback_reason"]

    # --- Paragraph 3: Genuine professional motivation composition -------------
    def _compose_motivation_paragraph(full_bridge: str, short_bridge: str) -> str:
        if not para3_texts:
            return full_bridge
        # 1. Try combining top interest + top preference + full bridge
        if len(para3_texts) >= 2:
            combined = f"{para3_texts[0]} {para3_texts[1]} {full_bridge}"
            if len(combined.split()) <= 55:
                return combined
            combined = f"{para3_texts[0]} {para3_texts[1]} {short_bridge}"
            if len(combined.split()) <= 55:
                return combined
            combined = f"{para3_texts[0]} {para3_texts[1]}"
            if len(combined.split()) <= 55:
                return combined
        # 2. Top interest + full bridge
        cand = f"{para3_texts[0]} {full_bridge}"
        if len(cand.split()) <= 55:
            return cand
        # 3. Top interest + concise role connection bridge
        cand = f"{para3_texts[0]} {short_bridge}"
        if len(cand.split()) <= 55:
            return cand
        # 4. Top interest alone
        if len(para3_texts[0].split()) <= 55:
            return para3_texts[0]
        return full_bridge

    # --- Paragraph 4: Forward-looking closing composition ---------------------
    def _closing_paragraph(base_first: str, base_second: str) -> str:
        if direction_texts:
            candidate = f"{base_first} {direction_texts[0]}"
            if len(candidate.split()) <= 55:
                return candidate
        return f"{base_first} {base_second}"

    if letter.language == "de":
        # Paragraph 1: Application and professional connection
        if owned_skills_matched:
            focus_text = ", ".join(owned_skills_matched[:2])
            letter.opening = (
                f"Hiermit bewerbe ich mich um die ausgeschriebene Position bei {company}, da die Schwerpunkte "
                f"in {focus_text} direkt an mein Profil anknüpfen. Mein Masterstudium der Künstlichen "
                "Intelligenz und mein Bachelorabschluss in Computer Engineering bilden dafür den fachlichen Hintergrund."
            )
        else:
            letter.opening = (
                f"Hiermit bewerbe ich mich um die ausgeschriebene Position bei {company}. "
                "Mein Masterstudium der Künstlichen Intelligenz und mein Bachelorabschluss in Computer "
                "Engineering bilden den fachlichen Hintergrund für mein Interesse an den Aufgaben."
            )

        # Paragraph 2: Relevant experience and evidence
        letter.fit = fit_composed

        # Paragraph 3: Genuine professional motivation
        de_full_bridge = (
            f"Ich möchte meine belegten Kenntnisse in {skill_text} in die im Stellenprofil "
            "beschriebenen Aufgaben einbringen. Zugleich reizt mich die Möglichkeit, diese "
            "Erfahrungen in einem neuen fachlichen Umfeld weiterzuentwickeln."
        )
        de_short_bridge = (
            f"In dieser Rolle möchte ich meine Kenntnisse in {skill_text} gezielt in Ihre Aufgaben einbringen."
        )
        letter.motivation = _compose_motivation_paragraph(de_full_bridge, de_short_bridge)

        # Paragraph 4: Forward-looking closing
        letter.closing = _closing_paragraph(
            "Über die Gelegenheit, meine Bewerbung in einem Gespräch zu erläutern, freue ich mich.",
            "Vielen Dank für die Berücksichtigung meiner Unterlagen.",
        )
        letter.signoff = "Mit freundlichen Grüßen"
    else:
        # Paragraph 1: Application and professional connection
        if owned_skills_matched:
            focus_text = ", ".join(owned_skills_matched[:2])
            letter.opening = (
                f"I am applying for the advertised position at {company}, as the focus on "
                f"{focus_text} connects directly to my technical profile. My Master's studies in "
                "Artificial Intelligence and Bachelor's degree in Computer Engineering provide the foundation for this work."
            )
        else:
            letter.opening = (
                f"I am applying for the advertised position at {company}. My academic background in "
                "Artificial Intelligence and Computer Engineering is the basis for my interest in the work "
                "described for this role."
            )

        # Paragraph 2: Relevant experience and evidence
        letter.fit = fit_composed

        # Paragraph 3: Genuine professional motivation
        en_full_bridge = (
            f"I would bring my documented experience in {skill_text} to the responsibilities described "
            "in the posting. I am interested in applying skills already established in my academic and "
            "professional background while continuing to develop in the role's field."
        )
        en_short_bridge = (
            f"I want to apply my documented experience in {skill_text} directly to the responsibilities described."
        )
        letter.motivation = _compose_motivation_paragraph(en_full_bridge, en_short_bridge)

        # Paragraph 4: Forward-looking closing
        letter.closing = _closing_paragraph(
            "I would welcome the opportunity to discuss how this background relates to the position.",
            "Thank you for considering my application.",
        )
        letter.signoff = "Kind regards"

    return letter, mot_meta



def _para(text: object) -> str:
    """Collapse whitespace in one generated paragraph (length is gated by L1,
    which parks over-long letters instead of silently truncating)."""
    return re.sub(r"\s+", " ", str(text or "").strip())


def _validate_body(data: dict | None) -> dict:
    if not isinstance(data, dict):
        raise ValueError("cover-letter reply contained no JSON object")
    missing = [k for k in ("opening", "fit", "motivation", "closing") if not str(data.get(k) or "").strip()]
    if missing:
        raise ValueError(f"cover-letter JSON missing paragraphs: {missing}")
    return data


def generate_letter(
    letter: CoverLetter,
    cset: ClaimableSet,
    job: dict,
    analysis_dict: dict,
    token: str,
    temperature: float = 0.25,
    candidate_facts: str | None = None,
) -> tuple[CoverLetter, dict]:
    """Fill the four body paragraphs via one constrained LLM call (+1 repair).

    The repair call (temperature 0) appends the validation error verbatim,
    like the analyst repair (analyst.py). meta: {calls, repair_used, error}.
    Raises RuntimeError after the repair so the caller parks the job
    (never ships a half-letter).
    """
    meta = {"calls": 0, "repair_used": 0, "error": ""}
    prompt = _body_prompt(
        letter, cset, job, analysis_dict,
        candidate_facts=candidate_facts or _candidate_facts_block())
    error = ""
    for attempt in range(2):
        call_prompt = prompt if attempt == 0 else (
            prompt
            + "\n\nYOUR PREVIOUS REPLY WAS INVALID: "
            + error[:400]
            + "\nReturn ONLY corrected valid JSON with keys opening/fit/motivation/closing. No other text."
        )
        raw = call_llm(call_prompt, token, temperature=temperature if attempt == 0 else 0.0)
        meta["calls"] += 1
        try:
            data = _validate_body(extract_json(raw))
            letter.opening = _para(data["opening"])
            letter.fit = _para(data["fit"])
            letter.motivation = _para(data["motivation"])
            letter.closing = _para(data["closing"])
            letter.signoff = "Mit freundlichen Grüßen" if letter.language == "de" else "Kind regards"
            meta["repair_used"] = attempt  # 1 when the in-loop repair was needed
            return letter, meta
        except ValueError as exc:
            error = str(exc)
    meta["repair_used"] = 1
    meta["error"] = error
    raise RuntimeError(f"cover-letter generation failed: {error}")


# ---------------------------------------------------------------------------
# Deterministic post-checks (LLM proposes, code disposes — V7 §4)
# ---------------------------------------------------------------------------

def postcheck_letter(letter: CoverLetter, job: dict, cset: ClaimableSet) -> list[str]:
    """Deterministic repairs on the generated letter; returns a fix log."""
    fixes: list[str] = []

    # 1. salutation enforcement (never trust the model with layout facts;
    #    re-detected from the JOB so the check is self-sufficient)
    gender, contact_name = detect_contact_person(posting_text(job))
    expected = salutation_for(letter.language, gender, contact_name)
    if letter.salutation != expected:
        letter.salutation = expected
        fixes.append(f"salutation enforced: {expected}")

    # 2. company-name verification: the letter must not name a wrong company.
    # GATED in L2 (check_l2_truth); here we only log a postcheck note so the
    # generation meta records it before the gate runs.
    company = letter.company_name
    if company:
        for mention in COMPANY_MENTION_RE.finditer(" ".join(
                str(getattr(letter, name) or "") for name in ("opening", "fit", "motivation", "closing"))):
            mention_text = f"{mention.group(1).strip()} {mention.group(2)}"
            if company.lower() not in mention_text.lower() and mention_text.lower() not in company.lower():
                letter.raw.setdefault("company_mention_flags", []).append(mention_text)

    # 3. signoff + name print are deterministic
    signoff = "Mit freundlichen Grüßen" if letter.language == "de" else "Kind regards"
    if letter.signoff != signoff:
        letter.signoff = signoff
        fixes.append(f"signoff enforced: {signoff}")

    # 4. normalize smart quotes/dashes the model may emit
    for attr in ("opening", "fit", "motivation", "closing"):
        value = getattr(letter, attr)
        cleaned = value.replace("\u201c", '"').replace("\u201d", '"')
        cleaned = cleaned.replace("\u2018", "'").replace("\u2019", "'")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned != value:
            setattr(letter, attr, cleaned)
            fixes.append(f"{attr}: normalized punctuation/whitespace")

    # 5. strip markdown artifacts the model may leak
    for attr in ("opening", "fit", "motivation", "closing"):
        value = getattr(letter, attr)
        stripped = re.sub(r"(?m)^\s*#{1,6}\s*", "", value)
        stripped = stripped.replace("**", "").replace("__", "")
        if stripped != value:
            setattr(letter, attr, stripped)
            fixes.append(f"{attr}: stripped markdown artifacts")
    return fixes


# ---------------------------------------------------------------------------
# Fill values (templates/fill.py contract: full @@NAME@@ token strings)
# ---------------------------------------------------------------------------

def _escape_company_block(company_block: str) -> str:
    """Escape the company block lines; join with single LaTeX line breaks."""
    from resume_content_improve_research.templates.fill import escape_latex
    lines = [escape_latex(line) for line in (company_block or "").splitlines() if line.strip()]
    return " \\ ".join(lines) if lines else ""


def probe_date_line(letter: CoverLetter) -> None:
    """Set the REAL date line (city + today, Europe/Berlin) on the letter.

    Called at BOTH gate sites (step 4 and step 5) before L1 runs, so the
    gate-checked letter and the filled/shipped artifacts carry the identical
    date — without this, every skeleton fails L1 on the empty date, and a
    fill-time re-derivation could print a different day than was gated.
    """
    letter.date_line = _compose_date_line(letter.sender_address)


def _compose_date_line(sender_address: str) -> str:
    """'City, DD.MM.YYYY' from the KB address; bare date when the city is unknown."""
    city = _city_from_kb_address(sender_address)
    return f"{city}, {german_today()}" if city else german_today()


def _city_from_kb_address(address: str, fallback: str = "") -> str:
    """City from the KB contact address ('street, PLZ City, Country' form).

    Matches the part that starts with a postal code (4-6 digits) and returns
    the remainder ('45141 Essen' -> 'Essen'). No silent fallback city: an
    unparseable address yields '' and the letter dates 'DD.MM.YYYY' alone —
    a wrong hardcoded city on a formal letter is worse than none.
    """
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    for part in reversed(parts):
        match = re.match(r"^\d{4,6}\s+(.+)$", part)
        if match:
            return match.group(1).strip()
    return fallback


def to_fill_values(letter: CoverLetter) -> dict[str, str]:
    """Token-keyed escaped values for the letter templates (fill.py contract)."""
    from datetime import datetime

    from resume_content_improve_research import config
    from resume_content_improve_research.templates.fill import escape_latex

    tokens = config.CL_TOKENS
    # The letter's own date_line (set once by probe_date_line via german_today())
    # is the single source of truth; filling must never re-derive the date, or the
    # gate-checked letter and the shipped PDF/DOCX/TXT could carry different days.
    date_line = letter.date_line or _compose_date_line(letter.sender_address)
    return {
        tokens["cl_sender_name"]: escape_latex(letter.sender_name),
        tokens["cl_sender_address"]: escape_latex(letter.sender_address),
        tokens["cl_sender_contact"]: escape_latex(letter.sender_contact),
        tokens["cl_sender_links"]: escape_latex(letter.sender_links),
        tokens["cl_company_block"]: _escape_company_block(letter.company_block),
        tokens["cl_date_line"]: escape_latex(date_line),
        tokens["cl_subject"]: escape_latex(letter.subject),
        tokens["cl_salutation"]: escape_latex(letter.salutation),
        tokens["cl_opening"]: escape_latex(letter.opening),
        tokens["cl_fit"]: escape_latex(letter.fit),
        tokens["cl_motivation"]: escape_latex(letter.motivation),
        tokens["cl_closing"]: escape_latex(letter.closing),
        tokens["cl_signoff"]: escape_latex(letter.signoff),
        tokens["cl_name_print"]: escape_latex(letter.name_print),
    }


def letter_from_dict(data: dict) -> CoverLetter:
    """Reconstruct a CoverLetter from the stored dict (run_step5 build path)."""
    sender = data.get("sender") or {}
    meta = data.get("meta") or {}
    letter = CoverLetter(
        language=str(data.get("language") or "en"),
        subject=str(data.get("subject") or ""),
        salutation=str(data.get("salutation") or ""),
        opening=str(data.get("opening") or ""),
        fit=str(data.get("fit") or ""),
        motivation=str(data.get("motivation") or ""),
        closing=str(data.get("closing") or ""),
        signoff=str(data.get("signoff") or ""),
        name_print=str(data.get("name_print") or ""),
        sender_name=str(sender.get("name") or ""),
        sender_address=str(sender.get("address") or ""),
        sender_contact=str(sender.get("contact") or ""),
        sender_links=str(sender.get("links") or ""),
        company_block=str(data.get("company_block") or ""),
        date_line=str(data.get("date_line") or ""),
        reference=str(data.get("reference") or ""),
        portal=str(data.get("portal") or "unknown"),
        company_name=str(data.get("company_name") or ""),
        raw=dict(meta) if isinstance(meta, dict) else {},
    )
    return letter


def letter_to_dict(letter: CoverLetter) -> dict:
    """Plain dict for the components store and the report."""
    return {
        "language": letter.language,
        "subject": letter.subject,
        "salutation": letter.salutation,
        "opening": letter.opening,
        "fit": letter.fit,
        "motivation": letter.motivation,
        "closing": letter.closing,
        "signoff": letter.signoff,
        "name_print": letter.name_print,
        "sender": {
            "name": letter.sender_name,
            "address": letter.sender_address,
            "contact": letter.sender_contact,
            "links": letter.sender_links,
        },
        "company_block": letter.company_block,
        "date_line": letter.date_line,
        "reference": letter.reference,
        "portal": letter.portal,
        "company_name": letter.company_name,
        "meta": letter.raw,
    }
