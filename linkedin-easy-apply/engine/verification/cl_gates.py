"""Cover-letter gates L1-L4 (fail = never ship) — the letter-side gates G1-G3.

The letter is additionally licensed to name the candidate's OWN past employers
(Soham Infotech, Pantechelearning) — the KB-licensed whitelist is built from
`kb['experience']` company fields, so the mapping stays config-free.

Measured bounds: LLM bodies on real postings land at ~110-160 words (4×55 max
per paragraph); config's 180 minimum would park healthy German letters, so L1
enforces 100-330 (measured one-page fit at 11pt) and drives the same constants
into the prompt so the model aims inside the enforced window.

L1 structure/parse sanity: the deterministic skeleton is complete, the body has
   4 paragraphs within the one-page word bounds, subject/salutation/sign-off
   follow the German norm, date is DD.MM.YYYY.
L2 truth licensing: the same claim surface as the resume G2 (tech tokens ⊆
   claimable set; no digits/spelled-out numbers; no percentages) PLUS letter-
   specific license: no salary demands, no invented company research.
L3 artifact integrity: no leftover @@CL_ tokens, no markdown leakage, no
   apostrophe dates, no placeholder residue.
L4 language agreement: the letter's language matches the posting's language
   (de posting -> de letter; en posting -> en letter), checked on the FINAL
   text so a mislabeled analysis cannot slip a wrong-language letter through.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from engine import config
from engine.verification.gates import check_g2_claims

# A company mention = capitalized word run ending in a German legal form.
# Words must START uppercase (case-SENSITIVE on purpose): the greedy variant
# once swallowed "Bank AG und die Commerzbank GmbH" into ONE mention — lowercase
# function words break the run, so two companies are detected separately.
# The legal form must stand as its own word: with '\s*' the name "Fraunhofer IESE"
# was read as "Fraunhofer IE" + legal form "SE" and the target employer's own name
# failed L2 (measured on the 2026-10-17 letter dry run).
COMPANY_MENTION_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,4})\s+"
    r"(GmbH|AG|SE|UG|KG|e\.K\.)(?![A-Za-z])"
)


def company_mentions(text: str) -> list[str]:
    """Deduplicated legal-form company mentions in `text` (order preserved)."""
    seen: list[str] = []
    for match in COMPANY_MENTION_RE.finditer(text or ""):
        mention = f"{match.group(1).strip()} {match.group(2)}".strip()
        if mention and mention.lower() not in (s.lower() for s in seen):
            seen.append(mention)
    return seen


def _kb_employers() -> set[str]:
    """The candidate's own past employers (KB-licensed names in letters)."""
    from engine.generation import kb_loader
    try:
        return {
            str(exp.get("company") or "").strip().lower()
            for exp in kb_loader.experiences(kb_loader.load_kb())
            if str(exp.get("company") or "").strip()
        }
    except Exception:  # noqa: BLE001 - a KB read failure must not kill gating
        return set()

_FIELD = r"(?:computer science|informatics|business informatics|electrical engineering|data science|" \
         r"software engineering|information systems)"
_BIOGRAPHY_PATTERNS = (
    (re.compile(rf"(?i)\b{_FIELD}\s+(?:student|degree|studies|master'?s?|bachelor'?s?|programme|program)\b"),
     "degree relabelled"),
    (re.compile(rf"(?i)\b(?:student|degree|studies|master'?s?|bachelor'?s?)\s+(?:of|in)\s+{_FIELD}\b"),
     "degree relabelled"),
    (re.compile(rf"(?i)\bstudying\s+{_FIELD}\b"), "degree relabelled"),
    (re.compile(r"(?i)\b(?:informatikstudi\w*|informatikstudent\w*|studium der (?:wirtschafts)?informatik|"
                r"wirtschaftsinformatikstudi\w*)\b"), "degree relabelled"),
    (re.compile(r"(?i)\bbachelor'?s?\s+student\b|\bbachelorstudent\w*\b|\bcurrently\s+(?:pursuing|studying)\s+"
                r"(?:a\s+)?bachelor"), "bachelor claim"),
    (re.compile(r"(?i)\b(?:first|second|third|fourth|fifth|sixth|seventh|\d+(?:st|nd|rd|th)?)\s+semester\b|"
                r"\b(?:\d+\.|erst|zweit|dritt|viert|fünft|sechst)\w*\s+(?:fach)?semester\b"), "semester claim"),
    (re.compile(r"(?i)\b(?:\w+|\d+)\+?\s+years?\s+of\s+(?:professional\s+|industry\s+|hands-on\s+)?experience\b|"
                r"\b(?:\w+|\d+)\s+jahren?\s+(?:berufs)?erfahrung\b"), "years of experience"),
)

# German function words; their absence marks an English letter in a de envelope.
_DE_MARKERS = re.compile(r"(?i)\b(und|mit|ich|meine|mich|für|über|als|sehr geehrte|"
                         r"mit freundlichen grüßen|stellenanzeige|bewerbung)\b")


@dataclass
class LetterGateResult:
    gate: str
    passed: bool
    findings: list[str] = field(default_factory=list)


def _body_text(letter) -> str:
    return " ".join(
        str(getattr(letter, name) or "")
        for name in ("opening", "fit", "motivation", "closing")
    )


def check_l1_structure(letter) -> list[str]:
    """Skeleton completeness + one-page bounds + German-norm elements."""
    findings: list[str] = []
    if not letter.subject.strip():
        findings.append("L1: subject line empty")
    if not letter.salutation.strip():
        findings.append("L1: salutation empty")
    for name in ("opening", "fit", "motivation", "closing"):
        para = str(getattr(letter, name) or "").strip()
        if not para:
            findings.append(f"L1: body paragraph '{name}' is empty")
        elif len(para.split()) > config.LETTER_PARAGRAPH_MAX:
            findings.append(f"L1: paragraph '{name}' over {config.LETTER_PARAGRAPH_MAX} words "
                            f"({len(para.split())})")
    words = letter.body_words()
    if words < config.LETTER_WORD_MIN:
        findings.append(f"L1: letter body {words} words — too short (stub), min {config.LETTER_WORD_MIN}")
    if words > config.LETTER_WORD_MAX:
        findings.append(f"L1: letter body {words} words — over the one-page norm, max {config.LETTER_WORD_MAX}")
    if letter.language == "de" and "grüßen" not in letter.signoff.lower():
        findings.append("L1: German letter must close with 'Mit freundlichen Grüßen'")
    if not re.search(r"\d{2}\.\d{2}\.\d{4}", letter.date_line or ""):
        findings.append("L1: date line must be DD.MM.YYYY")
    if letter.sender_name and letter.name_print and letter.sender_name.lower() not in letter.name_print.lower():
        findings.append("L1: name_print does not match sender name")
    if not letter.company_name:
        findings.append("L1: company name missing (address block will be empty)")
    return findings


def check_l2_truth(letter, cset, licensed_digits: set[str], own_employers: set[str] | None = None) -> list[str]:
    """Truth licensing on the letter body: claimable set + digits + no salary claims.

    `own_employers` overrides the KB-derived employer whitelist (tests); None
    means derive it from the real KB.
    """
    text = _body_text(letter)
    company = str(getattr(letter, "company_name", "") or "")
    # A target employer can also match a technology acronym (e.g. SAP). It is
    # validated as a company mention below, not as a candidate skills claim.
    tech_text = text
    if company:
        company_words = re.escape(company.strip())
        tech_text = re.sub(rf"(?i)\b{company_words}\b", "[target employer]", tech_text)
        # Parenthesized employer acronyms (e.g. AWS in Amazon Web Services
        # (AWS)) are also target-name tokens, not candidate skill claims.
        for acronym in re.findall(r"\(([A-Z]{2,8})\)", company):
            tech_text = re.sub(rf"\b{re.escape(acronym)}\b", "[target employer]", tech_text)
    findings = check_g2_claims(tech_text, cset, licensed_digits)

    salary = re.search(
        r"(?i)\b(\d[\d.,]*\s*(?:€|eur|euro|k\b)|gehalt|gehaltswunsch|salary expectation|"
        r"salary requirement|earnings of)\b",
        text,
    )
    if salary:
        findings.append(f"L2: salary/money demand in letter: {salary.group(0)!r} (never auto-generated)")

    for claim in re.finditer(
        r"(?i)(preisgekrönt|marktführend|award-winning|market-leading|"
        r"your innovative products|your groundbreaking)",
        text,
    ):
        findings.append(f"L2: unverifiable company flattery: {claim.group(0)!r}")

    own = _kb_employers() if own_employers is None else own_employers
    # The deterministic address block repeats the employer's full legal name,
    # but the conservative mention regex can split suffixes such as "Co. KG".
    # Treat mentions wholly contained in the exact target name as licensed.
    target_words = re.sub(r"[^a-z0-9]+", " ", company.lower()).split()
    target_forms = {" ".join(target_words)}
    for size in range(1, len(target_words)):
        target_forms.add(" ".join(target_words[-size:]))
    for mention in company_mentions(text):
        low = mention.lower()
        normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", low).split())
        if company and (company.lower() in low or low in company.lower()
                       or normalized in target_forms):
            continue
        if any(emp in low or low in emp for emp in own):
            continue
        findings.append(
            f"L2: company {mention!r} named in the letter but backed by neither the posting nor the KB"
        )

    # Reject unconfirmed placeholder or draft markers leaked into body text
    placeholder_hit = re.search(r"(?i)\b(TODO_CANDIDATE|PLACEHOLDER_ONLY|GUESS)\b", text)
    if placeholder_hit:
        findings.append(f"L2: unapproved placeholder/guess marker in letter: {placeholder_hit.group(0)!r}")

    # Biography inferred from the job ad (the measured reason the LLM letter path was
    # once switched off): degree relabelling, bachelor/semester claims, invented
    # years of experience. The KB facts are MSc AI (in progress) + BE Computer Eng.
    bio_text = text
    title = re.sub(r"^(?:Bewerbung als|Application for)\s+", "", str(getattr(letter, "subject", "") or ""))
    title = re.split(r"\s+-\s+(?:Referenz|Reference):", title)[0].strip()
    if title:
        from engine.generation.keywords import clean_headline
        # the job title itself ("Working Student in Data Science") is not a biography claim
        for form in {title, clean_headline(title)}:
            if form:
                bio_text = re.sub(re.escape(form), "[job title]", bio_text, flags=re.IGNORECASE)
    for pattern, what in _BIOGRAPHY_PATTERNS:
        hit = pattern.search(bio_text)
        if hit:
            findings.append(f"L2: biography not in the KB ({what}): {hit.group(0)!r}")

    # Policy v3 (2026-10-17): job-ad keywords may be named as the candidate's skills
    # (they are part of cset.mentionable() via the keyword plan), so the former
    # "mirrorable tool claimed as owned" rule is gone; invented companies, numbers
    # and technology the job never mentioned are still rejected above.

    # Traceability check for motivation statements sourced from motivation_profile
    raw = getattr(letter, "raw", None) or {}
    if isinstance(raw, dict):
        if raw.get("motivation_unapproved"):
            findings.append("L2: motivation statement comes from an unapproved profile entry")
        if raw.get("motivation_source") == "profile":
            entry_ids = raw.get("motivation_entry_ids") or []
            evidence_ids = raw.get("motivation_evidence_ids")
            if not entry_ids:
                findings.append("L2: motivation_source is 'profile' but motivation_entry_ids is empty")
            if evidence_ids is not None and not evidence_ids:
                findings.append("L2: motivation statement from profile lacks traceable KB evidence ids")
            for eid in evidence_ids or []:
                if not str(eid).strip() or re.search(r"(?i)\b(TODO_CANDIDATE|GUESS)\b", str(eid)):
                    findings.append(f"L2: motivation evidence id {eid!r} is unapproved or invalid")
    return findings


def check_l3_artifact(filled_text: str) -> list[str]:
    """Artifact integrity on the FILLED letter text (pre-compile)."""
    findings: list[str] = []
    if "@@" in filled_text:
        findings.append("L3: leftover @@CL_ tokens in filled letter")
    if re.search(r"(?m)^\s*#{1,6}\s", filled_text):
        findings.append("L3: markdown heading leaked into the letter")
    if "**" in filled_text or "__" in filled_text:
        findings.append("L3: markdown bold leaked into the letter")
    if re.search(r"[A-Z][a-z]{2}[’']\d{2}\b", filled_text):
        findings.append("L3: apostrophe-year date present (Dec'23 style)")
    for marker in ("LATEX_ERROR", "Undefined control sequence"):
        if marker in filled_text:
            findings.append(f"L3: LaTeX error marker in filled text: {marker!r}")
    if re.search(r"(?m)^! [A-Z]", filled_text):
        findings.append("L3: LaTeX error marker in filled text: '! '")
    return findings


def check_l4_language(letter) -> list[str]:
    """Letter language must agree with the posting language."""
    body = _body_text(letter)
    findings: list[str] = []
    german_markers = len(_DE_MARKERS.findall(body))
    if letter.language == "de" and german_markers < 2:
        findings.append(
            f"L4: letter labeled de but only {german_markers} German markers in the body "
            "— wrong-language body?"
        )
    if letter.language == "en" and german_markers >= 3:
        findings.append(
            f"L4: letter labeled en but {german_markers} German markers in the body "
            "— wrong-language body?"
        )
    if letter.language == "de" and not letter.salutation.lower().startswith("sehr geehrte"):
        findings.append("L4: de letter missing the German salutation")
    if letter.language == "en" and "dear" not in letter.salutation.lower():
        findings.append("L4: en letter missing an English salutation")
    return findings


def run_letter_gates(letter, cset, licensed_digits: set[str], filled_text: str = "") -> list[LetterGateResult]:
    """All four letter gates on the intent (filled_text adds the artifact side)."""
    results = [
        LetterGateResult("L1", True, check_l1_structure(letter)),
        LetterGateResult("L2", True, check_l2_truth(letter, cset, licensed_digits)),
        LetterGateResult("L3", True, check_l3_artifact(filled_text or _body_text(letter))),
        LetterGateResult("L4", True, check_l4_language(letter)),
    ]
    for result in results:
        result.passed = not result.findings
    return results
