"""Per-job target keyword plan (plan v3 §4): every keyword the job ad asks for.

Why this exists (measured on the 2026-10-14 run): the analyst saw only
`job_description`, but for 17/36 jobs the scraper stores the requirements in a
separate column, so terms such as Burp Suite, OWASP, SAST and DAST never reached
it. The analyst's lists are also capped and phrase-shaped ("pandas library",
"experience with APIs"). This module fixes both, deterministically:

  1. `analysis_text` joins every requirement-bearing posting column (deduped),
     so the analyst sees the whole ad.
  2. `build_keyword_plan` merges the phrase-cleaned analyst terms with a sweep
     of the FULL posting text against knowledge_base/tech_lexicon.json, so a
     capped or missed term is still found.

The plan is ordered required -> tools -> preferred -> swept, deduplicated and
categorised; eligibility rules (enrolment, hours, duration, location) and
language requirements are split off because they belong in the header/letter,
not the Skills section. Zero LLM calls.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache

from engine import config

LEXICON_PATH = config.KB_DIR / "tech_lexicon.json"

# Posting columns that carry requirements/tasks. Benefits and company blurbs are
# left out on purpose: "MacBook" or "Udemy budget" are not keywords to claim.
ANALYSIS_TEXT_COLUMNS = ("job_description", "requirements", "your_tasks", "applicant_profile")
SWEEP_TEXT_COLUMNS = ("title",) + ANALYSIS_TEXT_COLUMNS

SOURCE_ORDER = ("required", "tools", "preferred", "sweep")

# A term character for boundary purposes: letters (incl. umlauts), digits and the
# symbols that are part of tech names (C++, C#). '.' and '/' are NOT term
# characters, so "Node.js." at a sentence end and "Python/SQL" both match.
_TERM_CHAR = r"A-Za-z0-9_+#ÄÖÜäöüß"
_BEFORE = rf"(?<![{_TERM_CHAR}])"
_AFTER = rf"(?![{_TERM_CHAR}])"

_GENDER_MARKER_RE = re.compile(
    r"\s*[\(\[]\s*(?:[mwfdx]|all|genders?|divers|alle)(?:\s*[/|,\-]\s*(?:[mwfdx]|all|genders?|divers))*\s*[\)\]]"
    r"|\s*[\(\[]\s*all genders\s*[\)\]]",
    re.IGNORECASE,
)

# Eligibility / logistics: real job rules, not skills (header + letter material).
_ELIGIBILITY_RE = re.compile(
    r"(?i)\b(?:enrol\w*|immatrikul\w*|eingeschrieben|student status|currently studying|"
    r"studying|student|studierende\w*|studium|semester|degree|bachelor\w*|"
    r"(?<!scrum )master(?:'s|s)?(?! data)|diploma|graduat\w*|"
    r"hours?(?:\s*(?:per|/|a)\s*week)?|\d+\s*(?:h|hrs|std)\b|stunden|wochenstunden|"
    r"months?|monate\w*|weeks?|duration|"
    r"start(?:ing)? date|eintritt\w*|available|availability|verfügbar\w*|"
    r"on-?site|remote\w*|hybrid|relocat\w*|commut\w*|office presence|"
    r"driver'?s? licen[cs]e|driving licen[cs]e|führerschein|own (?:transport|car|vehicle)|"
    r"work permit|visa|arbeitserlaubnis|penultimate|final[- ]year|"
    r"paid internship|full-?time|part-?time|vollzeit|teilzeit|eligib\w*)\b"
)
_LANGUAGE_LEVEL_RE = re.compile(r"(?i)^(?:[ABC][12])(?:\s*(?:level|niveau|or above|or higher|\+|minimum))*\b")

# Single generic words the analyst sometimes returns alone; never a keyword by themselves.
_GENERIC_ALONE = {
    "coding", "programming", "development", "analysis", "learning", "testing", "workflow",
    "workflows", "digital", "transfers", "follow-up", "high level", "high performance",
    "identity", "hardware", "software", "technology", "it", "data", "tools", "projects",
}
# Free phrases that describe ways of working go to soft skills, not the domain bucket.
_SOFT_HINT_RE = re.compile(
    r"(?i)\b(?:feedback|deadline|mindset|attitude|cooperat\w*|stakeholders?|"
    r"cross[- ]functional|collaborat\w*|self[- ]\w+|ownership|"
    r"responsib\w*|organi[sz]\w*|proactiv\w*|motivat\w*|commitment|flexib\w*)\b"
)

_LANGUAGE_RE = re.compile(
    r"(?i)\b(?:english|german|deutsch\w*|englisch\w*|french|spanish|italian|dutch)\b"
)

# "studying X", "degree in X", "background in X" -> X is an education field.
_EDU_FIELD_RE = re.compile(
    r"(?i)(?:studying|studies in|study of|degree in|degree program(?:me)? in|student (?:of|in)|"
    r"enrolled in|major(?:ing)? in|studiengang|studium der|background in)\s+(.+)$"
)
_EDU_FIELD_HINT_RE = re.compile(
    r"(?i)\b(?:computer science|informatics|informatik|business informatics|wirtschaftsinformatik|"
    r"data science|mathematics|mathematik|statistics|physics|electrical engineering|"
    r"engineering|information systems|it security|cyber ?security|business administration|"
    r"economics|artificial intelligence|software engineering|natural sciences|stem|mint)\b"
)

# Leading qualifiers the analyst wraps around a skill ("strong experience with X").
_LEAD_PATTERNS = [
    re.compile(r"(?i)^(?:the|a|an|our|your|der|die|das)\s+"),     # "the Tooling" (live iLert run)
    re.compile(r"(?i)^(?:very|really|strong|solid|good|excellent|proven|deep|basic|first|initial|"
               r"practical|hands-on|working|sound|advanced|in-depth|some|prior|demonstrable|"
               r"demonstrated|relevant|professional|extensive|comprehensive|fundamental|general|"
               r"broad|confident|reliable|fluent|safe|sicherer?|gute|sehr gute|erste|fundierte)\s+"),
    re.compile(r"(?i)^(?:experience|knowledge|understanding|familiarity|proficiency|expertise|"
               r"skills?|background|exposure|interest|affinity|passion|competence|know-how|"
               r"enthusiasm|curiosity|kenntnisse|erfahrung(?:en)?)\s*(?:with|in|of|on|for|using|"
               r"around|regarding|mit|in|im)?\s+"),
    re.compile(r"(?i)^(?:proficient|experienced|familiar|skilled|comfortable|confident|fluent|"
               r"versed|well-versed|interested)\s+(?:with|in|using|at)\s+"),
    re.compile(r"(?i)^(?:ability|able|willingness|eagerness)\s+to\s+(?:use|work with|apply)?\s*"),
    re.compile(r"(?i)^(?:use|using|working with|work with|apply|applying)\s+(?:of\s+)?"),
]
# Trailing head nouns around a skill ("pandas library", "low-code tools").
_TRAIL_RE = re.compile(
    r"(?i)\s+(?:library|libraries|framework|frameworks|skills?|knowledge|experience|tools?|"
    r"technologies|technology|concepts?|fundamentals|basics|principles|stack|ecosystem|"
    r"proficiency|expertise|understanding|familiarity|competenc\w*|know-how|"
    r"kenntnisse|erfahrung|programming language|language)$"
)
# Generic words left over after lexicon hits; they do not need their own keyword.
_FILLER_WORDS = {
    "and", "or", "of", "in", "with", "for", "the", "a", "an", "to", "on", "using", "use",
    "und", "oder", "mit", "im", "der", "die", "das", "von",
    "process", "processes", "tool", "tools", "technology", "technologies", "concept", "concepts",
    "principle", "principles", "practice", "practices", "method", "methods", "technique",
    "techniques", "topic", "topics", "basic", "basics", "fundamentals", "solution", "solutions",
    "system", "systems", "skill", "skills", "knowledge", "experience", "strong", "good", "very",
    "excellent", "solid", "first", "initial", "practical", "related", "relevant", "modern",
    "common", "standard", "etc", "e.g", "eg", "such", "as", "like", "including", "plus",
    "programming", "development", "coding", "years", "year", "yrs", "jahre", "jahren", "jahr",
    "least", "minimum", "min",
}


@dataclass
class Keyword:
    term: str                       # what the resume prints (the ad's own spelling)
    category: str                   # programming | ml_ai | data | backend_cloud_devops |
                                    # security | tools_methods | soft_skills |
                                    # education_field | domain
    canonical: str = ""             # lexicon display form ('' for free phrases)
    sources: list[str] = field(default_factory=list)   # required/tools/preferred/sweep
    english: str = ""               # English equivalent for German ad terms


@dataclass
class KeywordPlan:
    headline: str = ""
    language: str = "en"
    keywords: list[Keyword] = field(default_factory=list)
    eligibility: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)

    def targets(self) -> list[str]:
        """Every term the resume must contain (the step-4/5 coverage gate list)."""
        return [k.term for k in self.keywords]

    def by_category(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for keyword in self.keywords:
            out.setdefault(keyword.category, []).append(keyword.term)
        return out

    def to_dict(self) -> dict:
        return {
            "headline": self.headline,
            "language": self.language,
            "keywords": [asdict(k) for k in self.keywords],
            "eligibility": list(self.eligibility),
            "languages": list(self.languages),
            "targets": self.targets(),
            "by_category": self.by_category(),
        }


# ---------------------------------------------------------------------------
# Posting text
# ---------------------------------------------------------------------------

def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def join_posting_text(job: dict, columns: tuple[str, ...]) -> str:
    """Join posting columns, skipping parts that repeat an earlier one.

    The scrapers duplicate whole fields (your_tasks == job_description on 18/36
    stepstone rows, applicant_profile == requirements on 17/36), so a part that is
    contained in an already-kept part is dropped, and a part that CONTAINS an
    already-kept part replaces it.
    """
    kept: list[str] = []
    for column in columns:
        raw = str(job.get(column) or "").strip()
        if not raw:
            continue
        key = _squash(raw).lower()
        if any(key in _squash(part).lower() for part in kept):
            continue
        kept = [part for part in kept if _squash(part).lower() not in key]
        kept.append(raw)
    return "\n\n".join(kept)


def analysis_text(job: dict) -> str:
    """The whole requirement-bearing ad text the analyst must see (title goes separately)."""
    return join_posting_text(job, ANALYSIS_TEXT_COLUMNS)


def clean_headline(title: str) -> str:
    """Posting title without gender markers: 'Working Student (m/f/d) - X' -> 'Working Student - X'."""
    text = _GENDER_MARKER_RE.sub("", str(title or ""))
    text = re.sub(r"\s+[mwfd]/[mwfd]/[mwfdx]\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,\-–:])\s*$", "", text)
    return text.strip(" -–,:")


# ---------------------------------------------------------------------------
# Lexicon sweep
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Entry:
    variant: str
    display: str
    category: str
    pattern: re.Pattern
    list_context: bool
    english: str = ""


def _norm_key(text: str) -> str:
    return re.sub(r"[^a-z0-9+#äöüß]+", "", str(text or "").lower())


def _variant_pattern(variant: str, case_sensitive: bool) -> re.Pattern:
    # Hyphens first, spaces second: the space class inserted below contains '\-'
    # itself and must not be rewritten again (that bug broke every multi-word term).
    parts = [re.escape(word).replace(r"\-", r"[\s\-]?") for word in variant.split(" ")]
    body = r"[\s\-]+".join(parts)               # "machine learning" == "machine-learning"
                                                # "fine-tuning" == "fine tuning" == "finetuning"
    plural = ""
    if not case_sensitive and len(variant) >= 4 and variant[-1].isalpha() and not variant.endswith("s"):
        plural = "(?:s|es)?"
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(_BEFORE + "(" + body + plural + ")" + _AFTER, flags)


@lru_cache(maxsize=1)
def _lexicon() -> tuple[_Entry, ...]:
    data = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
    case_sensitive = set(data.get("case_sensitive", []))
    list_context = set(data.get("list_context_only", []))
    entries: list[_Entry] = []
    for category, terms in data.get("categories", {}).items():
        for display, variants in terms.items():
            for variant in [display] + list(variants or []):
                cs = variant in case_sensitive
                entries.append(_Entry(variant, display, category, _variant_pattern(variant, cs),
                                      variant in list_context))
    german_cats = data.get("german_categories", {})
    soft_names = set(data.get("categories", {}).get("soft_skills", {}))
    for german, english in data.get("german", {}).items():
        cs = german in case_sensitive
        category = german_cats.get(german) or ("soft_skills" if english in soft_names else "domain")
        entries.append(_Entry(german, german, category,
                              _variant_pattern(german, cs), False, english=english))
    # longest variant first: "Azure OpenAI" beats "Azure", "REST APIs" beats "REST"
    entries.sort(key=lambda e: (-len(e.variant), e.variant))
    return tuple(entries)


_LIST_WORDS = {"and", "or", "und", "oder", "in", "with", "like", "mit", "e.g.", "z.b.", "using"}


def _in_list_context(text: str, start: int, end: int) -> bool:
    """Single-letter languages (R, C) count only inside a list or 'in R'."""
    before = text[:start].rstrip()
    after = text[end:].lstrip()
    prev_char = before[-1:] if before else ""
    next_char = after[:1]
    # guard the empty string: '' is "in" every string, which made text edges count as lists
    if (prev_char and prev_char in ",/(|;:") or (next_char and next_char in ",/)|;"):
        return True
    prev_word = before.split()[-1].lower() if before.split() else ""
    next_word = after.split()[0].lower().strip(".,;") if after.split() else ""
    if prev_word in _LIST_WORDS and (not next_char or next_char in ".\n" or next_word in _LIST_WORDS):
        return True
    return next_word in {"and", "or", "und", "oder", "programming", "language"}


def _display_term(entry: _Entry, surface: str) -> str:
    """The ad's own spelling with canonical casing; soft skills use the canonical label."""
    if entry.category == "soft_skills":
        return entry.display
    surface = _squash(surface)
    surface_key = _norm_key(surface)

    def spaced(text: str) -> str:
        return re.sub(r"[\s\-]+", " ", text.lower()).strip()

    # Only case/space/hyphen differences fold to the canonical form; dots and
    # concatenation are ATS-relevant ("NodeJS" and "Node.js" are different tokens).
    if spaced(surface) == spaced(entry.display):
        return entry.display          # canonical casing ("python" -> "Python")
    if surface.lower() == entry.variant.lower():
        return entry.variant          # variant casing ("nodejs" -> "NodeJS")
    if surface_key == _norm_key(entry.variant) \
            or surface_key.rstrip("s") == _norm_key(entry.variant).rstrip("s"):
        return surface                # the ad's punctuation/plural ("multi-tenant", "APIs")
    return entry.display


def sweep(text: str) -> list[dict]:
    """All lexicon hits in `text`, first occurrence per display form, in text order."""
    if not text:
        return []
    taken: list[tuple[int, int]] = []
    hits: dict[str, dict] = {}
    for entry in _lexicon():
        for match in entry.pattern.finditer(text):
            start, end = match.span(1)
            if any(start < t_end and t_start < end for t_start, t_end in taken):
                continue
            if entry.list_context and not _in_list_context(text, start, end):
                continue
            taken.append((start, end))
            key = _norm_key(entry.display)
            if key not in hits or start < hits[key]["pos"]:
                hits[key] = {
                    "pos": start,
                    "term": _display_term(entry, match.group(1)),
                    "canonical": entry.display,
                    "category": entry.category,
                    "english": entry.english,
                    "span": (start, end),
                }
    return sorted(hits.values(), key=lambda h: h["pos"])


# ---------------------------------------------------------------------------
# Analyst-term cleaning + classification
# ---------------------------------------------------------------------------

def clean_phrase(term: str) -> str:
    """'strong experience with pandas library' -> 'pandas'; never returns ''."""
    original = _squash(term).strip(" .,;:-")
    text = original
    for _ in range(6):
        before = text
        for pattern in _LEAD_PATTERNS:
            text = pattern.sub("", text).strip()
        text = _TRAIL_RE.sub("", text).strip()
        if text == before:
            break
    return text or original


_EDU_FIELD_TRAIL_RE = re.compile(r"(?i)^(?:currently\s+)?(.+?)\s+(?:studies|student|studium)$")


def _education_fields(term: str) -> list[str]:
    match = _EDU_FIELD_RE.search(term) or _EDU_FIELD_TRAIL_RE.search(_squash(term))
    if not match:
        return []
    fields: list[str] = []
    for part in re.split(r",|/|\bor\b|\band\b|\boder\b|\bund\b", match.group(1)):
        part = re.sub(r"(?i)\b(?:or a related field|or related|related field|or similar|"
                      r"or comparable|a related technical field|related technical field)\b", "", part)
        part = part.strip(" .;:-")
        if part and _EDU_FIELD_HINT_RE.search(part) and len(part.split()) <= 4:
            fields.append(" ".join(w if w.isupper() else w.capitalize() for w in part.split()))
    return fields


def _content_words(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9+#.\-ÄÖÜäöüß]+", text.lower())
    words = [w.strip(".-") for w in words]
    # bare counts ("3", "3+") are never keywords; S3/EC2/NIS2 keep their letters
    return [w for w in words if w and w not in _FILLER_WORDS and not re.fullmatch(r"\d+\+?", w)]


# Achievements / credentials are verifiable facts, not skills: printing "Published CVE"
# or "Meetup talk" in a Skills row claims one (live iLert run, 2026-10-17). They go to
# eligibility (reported as gaps), never into the printed keywords.
_CREDENTIAL_RE = re.compile(
    r"(?i)\b(?:published|publications?|blog(?:s|post)?|talks?|meetups?|conference|speaker|awards?|"
    r"patents?|certified|certifications?|track record|years? of experience|portfolio)\b")


def _classify_term(term: str, posting_key: str = "", language: str = "en") -> tuple[str, list[dict]]:
    """('eligibility'|'language'|'keywords', keyword dicts) for one analyst term.

    `posting_key` is the squashed, lowercased ad text. A free phrase with residual
    words is kept only when the ad itself contains it verbatim (an analyst
    paraphrase like "pentest web applications" is reduced to its lexicon terms).
    """
    cleaned = clean_phrase(term)
    if _CREDENTIAL_RE.search(term):
        return "eligibility", []
    fields = _education_fields(term)
    if fields:
        return "keywords", [{"term": f, "canonical": "", "category": "education_field", "english": ""}
                            for f in fields]
    if _LANGUAGE_RE.search(cleaned) and len(_content_words(cleaned)) <= 4 \
            and not re.search(r"(?i)\b(?:programming|sql|query)\b", cleaned):
        return "language", []
    if _LANGUAGE_LEVEL_RE.search(cleaned):
        return "language", []
    hits = sweep(cleaned)
    if _ELIGIBILITY_RE.search(term) and not hits:
        return "eligibility", []
    # words not explained by a lexicon hit decide whether the phrase itself is the keyword
    covered = set()
    for hit in hits:
        start, end = hit["span"]
        covered |= set(_content_words(cleaned[start:end]))
    residual = [w for w in _content_words(cleaned) if w not in covered]
    hit_items = [{k: h[k] for k in ("term", "canonical", "category", "english")} for h in hits]
    if hits and not residual:
        return "keywords", hit_items
    verbatim = (not posting_key) or _squash(cleaned).lower() in posting_key
    if hits and not verbatim:
        return "keywords", hit_items
    if not hits:
        # a free phrase must be the ad's own words (German ads: the analyst may
        # translate, so that check is skipped) and more than one generic word
        if not _content_words(cleaned) or cleaned.lower() in _GENERIC_ALONE:
            return "skip", []
        if not verbatim and language != "de":
            return "skip", []
    if hits:
        category = hits[0]["category"]
    else:
        category = "soft_skills" if _SOFT_HINT_RE.search(cleaned) else "domain"
    return "keywords", [{"term": cleaned, "canonical": "", "category": category, "english": ""}]


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

_LEGAL_FORMS = {"gmbh", "ag", "se", "kg", "co", "ug", "inc", "ltd", "llc", "group", "gruppe",
                "holding", "germany", "deutschland", "the", "und", "and", "de"}
# Ordinary words inside employer names ("Deutsche Bank", "XY Data Solutions") must not
# knock out real requirement phrases such as "banking regulations" or "data quality".
_COMMON_NAME_WORDS = {"bank", "data", "tech", "technology", "technologies", "software", "systems",
                      "solutions", "digital", "consulting", "services", "service", "energy",
                      "international", "global", "labs", "health", "mobility", "media", "cloud",
                      "security", "analytics", "engineering", "automation", "power", "network",
                      "networks", "finance", "financial", "insurance", "logistics", "industries",
                      "automotive", "motors", "electric", "research", "institute", "university"}


def _company_tokens(job: dict) -> set[str]:
    """Distinctive lowercase tokens of the employer's name (legal forms dropped)."""
    name = " ".join(str(job.get(col) or "") for col in ("company", "detail_company_name"))
    return {t for t in re.findall(r"[a-z0-9äöüß]+", name.lower())
            if len(t) >= 3 and t not in _LEGAL_FORMS and t not in _COMMON_NAME_WORDS}


def _contains_words(longer: str, shorter: str) -> bool:
    """True when `shorter` appears in `longer` as whole words (case-insensitive)."""
    if not shorter or shorter.lower() == longer.lower():
        return False
    return re.search(_BEFORE + re.escape(shorter.lower()) + _AFTER, longer.lower()) is not None


def build_keyword_plan(job: dict, analysis: dict) -> KeywordPlan:
    """Merge analyst terms and the full-text sweep into one ordered target plan."""
    analysis = analysis or {}
    language = str(analysis.get("language") or "en")
    plan = KeywordPlan(headline=clean_headline(str(job.get("title") or "")), language=language)
    plan.languages = [
        f"{entry.get('language')}" + (f" ({entry.get('level')})" if entry.get("level") else "")
        for entry in (analysis.get("languages_required") or [])
        if isinstance(entry, dict) and entry.get("language")
    ]

    sweep_text = join_posting_text(job, SWEEP_TEXT_COLUMNS)
    posting_key = _squash(sweep_text).lower()

    collected: list[tuple[str, dict]] = []
    for source in ("required", "tools", "preferred"):
        for term in analysis.get(source) or []:
            bucket, items = _classify_term(str(term), posting_key, language)
            if bucket == "eligibility":
                plan.eligibility.append(_squash(term))
            elif bucket == "keywords":
                collected += [(source, item) for item in items]
    for term in analysis.get("knockouts") or []:
        bucket, items = _classify_term(str(term), posting_key, language)
        if bucket == "keywords" and items and items[0]["category"] == "education_field":
            collected += [("required", item) for item in items]
        elif _squash(term):
            plan.eligibility.append(_squash(term))
    for hit in sweep(sweep_text):
        collected.append(("sweep", {k: hit[k] for k in ("term", "canonical", "category", "english")}))

    # the employer's own products ("SIXTgpt", "ilert platform") are not skills to claim
    company_tokens = _company_tokens(job)

    # dedupe on the canonical form (or the phrase itself), keeping first position
    merged: dict[str, Keyword] = {}
    for source, item in collected:
        key = _norm_key(item["canonical"] or item["term"])
        if not key:
            continue
        if not item["canonical"] and any(token in item["term"].lower() for token in company_tokens):
            continue
        if key in merged:
            if source not in merged[key].sources:
                merged[key].sources.append(source)
            # the sweep reads the ad itself: its spelling beats an analyst paraphrase
            # ("CI/CD" in the ad vs the analyst's "CI CD")
            if source == "sweep" and item["term"] != merged[key].term:
                merged[key].term = item["term"]
            continue
        merged[key] = Keyword(term=item["term"], category=item["category"],
                              canonical=item["canonical"], sources=[source],
                              english=item.get("english", ""))

    # a keyword fully contained in a longer one is printed by the longer one
    keywords = list(merged.values())
    survivors: list[Keyword] = []
    for keyword in keywords:
        container = next((other for other in keywords if other is not keyword
                          and _contains_words(other.term, keyword.term)), None)
        if container is None:
            survivors.append(keyword)
            continue
        for source in keyword.sources:
            if source not in container.sources:
                container.sources.append(source)

    for keyword in survivors:
        keyword.sources.sort(key=SOURCE_ORDER.index)
    survivors.sort(key=lambda k: SOURCE_ORDER.index(k.sources[0]))   # stable: keeps text order
    plan.keywords = survivors
    plan.eligibility = list(dict.fromkeys(plan.eligibility))
    return plan


def plan_for_record(record: dict) -> KeywordPlan:
    """Keyword plan for a stored step-4 record (posting from letter_input, else the record)."""
    posting = ((record.get("letter_input") or {}).get("posting")) or record
    return build_keyword_plan(posting, record.get("analysis") or {})
