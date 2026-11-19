"""
Email message templates — Phase 3 (cold outreach to German recruiting/employment
agencies, pitching the sender as a candidate for placement), v3.

Personalized per recipient per company (see PERSONALIZATION_PLAN.md):

    Layer 1  greeting     per-person first name, else "Hi {Company} team,"
    Layer 2  hook line    company focus + researched why + hiring evidence
    Layer 3  skills match sender skills ∩ company technical_focus
    Layer 4  role line    sender roles ∩ company relevant_roles
    Layer 5  subject      "Working Student / Intern at {Company} — {focus}"
    Layer 6  signature    name, phone, reply email + at most one profile link
    Layer 7  (optional)   pre-written per-company hook injected verbatim

Guardrail: every placeholder resolves to a value or a written fallback —
never an empty string, never a "TODO". A missing value produces a slightly
less personal email, never a broken one.

Facts keys used here (sender facts come from `.env`; per-recipient facts come
from the row in `contacts_to_send.csv`):

    company / contact_name      per-recipient (CSV row)
    technical_focus             per-recipient, "; "- or ","-separated list
    why_target                  per-recipient, researched reason (Phase 1)
    relevant_roles              per-recipient, role titles the company uses
    current_hiring_evidence     per-recipient, hiring evidence (Phase 1)
    website                     per-recipient
    company_hook                optional pre-written hook (Layer 7)

    sender_name / sender_email / contact_email / phone
    degree / university / education_extra
    skills                      structured: "Python: 3y, PyTorch: 1y, SQL"
    availability / german_level / sender_location
    sender_roles                "AI Engineering Working Student, ..."
    linkedin / github / portfolio   optional, at most one is used
    has_resume                  True when an attachment is actually attached
"""

import html
import re

# Names containing any of these are treated as role inboxes, not people.
# ("Recruiting Team" -> "Hi Parloa team,", "Malte Kosub" -> "Hi Malte,")
ROLE_INBOX_WORDS = (
    "team", "contact", "press", "job", "career", "hiring", "talent",
    "recruit", "hr", "people", "info", "office", "general", "bewerbung",
    "karriere", "applicat", "arbeit", "datenschutz", "security", "privacy",
    "support", "hello", "mail", "welcome", "student", "intern", "empfang",
    "zentrale", "buero", "gf", "legal", "sales", "complaint", "developer",
    "protection", "hinweis", "branch", "inbox", "corporate", "location",
    "region", "standort", "niederlassung", "filiale", "department", "division",
    "candidate", "service", "partner", "relations", "inquir", "enquir",
    "headquarter", "acquisition", "management", "placement", "community",
    "editorial", "compliance", "dpo", "arbeitgeber", "germany",
)

_FOCUS_SPLIT = re.compile(r"[;,]")


# --------------------------------------------------------------------------
# Small text helpers
# --------------------------------------------------------------------------

def _first(value):
    """Return the first non-empty stripped value, or ''."""
    if value is None:
        return ""
    return str(value).strip()


def _shorten(text, limit=12):
    """Trim to at most `limit` words, adding ' …' when cut."""
    text = _first(text).rstrip(".,;")
    if not text:
        return ""
    words = text.split()
    if len(words) <= limit:
        return text
    return " ".join(words[: limit - 1]).rstrip(".,;") + " …"


def _focus_terms(facts):
    """technical_focus -> list of terms (split on ';' or ',')."""
    raw = _first(facts.get("technical_focus"))
    return [p for p in (_FOCUS_SPLIT.split(raw)) if p.strip()]


def focus_headline(facts):
    """First focus term — used in the subject and the hook sentence."""
    terms = _focus_terms(facts)
    return terms[0] if terms else ""


def _is_role_inbox(contact_name):
    name = _first(contact_name).lower()
    if not name:
        return True
    return any(word in name for word in ROLE_INBOX_WORDS)


def greeting(facts):
    """Layer 1 — per-person first name, else 'Hi {Company} team,'."""
    company = facts["company"]
    contact_name = _first(facts.get("contact_name"))
    if _is_role_inbox(contact_name):
        return f"Hi {company} team,"
    return f"Hi {contact_name.split()[0]},"


def _hiring_fragment(facts):
    """'I see you're hiring for {roles}.'"""
    roles = _first(facts.get("relevant_roles"))
    evidence = _first(facts.get("current_hiring_evidence"))
    if roles:
        return f"I see you're hiring for {_shorten(roles, 8)}."
    if evidence:
        return "I see you're hiring."
    return ""


def _hook_sentence(facts):
    """Layer 2 — company focus + why + hiring evidence (or Layer 7 hook)."""
    pre_written = _first(facts.get("company_hook"))
    if pre_written:
        return pre_written

    company = facts["company"]
    headline = focus_headline(facts)
    why = _shorten(facts.get("why_target"), 12)
    hiring = _hiring_fragment(facts)

    if headline:
        base = f"I've been following {company}'s work in {headline}."
        if why:
            base = f"I've been following {company}'s work in {headline} ({why})."
    else:
        base = f"I've been following {company}'s software engineering and product developments."
    if hiring:
        base += " " + hiring
    return base


def _structured_skills(raw):
    """'Python: 3y, PyTorch: 1y, SQL' -> ['Python', 'PyTorch', 'SQL']."""
    out = []
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        name = chunk.split(":", 1)[0].strip()
        if name:
            out.append(name)
    return out


def _match_skills(facts):
    """Layer 3 — sender skills that appear in the company's focus terms."""
    skills = _structured_skills(facts.get("skills"))
    terms = _focus_terms(facts)
    if not skills or not terms:
        return None
    lower_terms = [t.lower() for t in terms]
    matched = []
    for skill in skills:
        low = skill.lower()
        if any(low in t or t in low for t in lower_terms):
            matched.append(skill)
    return matched or None


def _skills_line(facts):
    """Layer 3 — skills-match sentence with fallbacks."""
    matched = _match_skills(facts)
    headline = focus_headline(facts)
    if matched:
        shown = ", ".join(matched[:3])
        if headline:
            return f"I build with {shown}. A direct fit for your {headline} engineering."
        return f"I build with {shown}. A direct fit for your engineering team."
    if headline:
        return f"Your {headline} work is exactly what I want to grow into."
    skills_raw = _first(facts.get("skills"))
    if skills_raw:
        return f"I build with {skills_raw}."
    return "I want to grow into exactly this space."


def _fit_sentence(roles_raw):
    """'Role A, Role B, …' -> a clean fit line (chunk-based, no mid-word cuts)."""
    chunks = [c.strip() for c in _first(roles_raw).split(",") if c.strip()]
    if not chunks:
        return "Strong fit for your open roles."
    if len(chunks) > 2:
        return "Strong fit for roles like " + ", ".join(chunks[:3]) + ", …"
    return f"Strong fit for your {', '.join(chunks)} roles."


def _role_line(facts):
    """Layer 4 — sender roles ∩ company roles, with fallbacks."""
    sender_roles = [r.strip() for r in (facts.get("sender_roles") or "").split(",") if r.strip()]
    company_roles = _first(facts.get("relevant_roles"))
    if not sender_roles and not company_roles:
        return "Happy to help with engineering or research tasks."
    if sender_roles and company_roles:
        s_tokens = set(re.findall(r"[a-z]+", " ".join(sender_roles).lower()))
        c_tokens = set(re.findall(r"[a-z]+", company_roles.lower()))
        if s_tokens & c_tokens:
            return _fit_sentence(company_roles)
    if sender_roles:
        return f"Strong fit for your {', '.join(sender_roles[:3])} roles."
    return _fit_sentence(company_roles)


def _intro(facts):
    """Layer 2 intro — degree + university, with fallbacks."""
    degree = _first(facts.get("degree"))
    university = _first(facts.get("university"))
    extra = _first(facts.get("education_extra"))
    if degree and university:
        base = f"I'm {facts['sender_name']}. {degree} student at {university}."
    elif university:
        base = f"I'm {facts['sender_name']}. Student at {university}."
    else:
        base = f"I'm {facts['sender_name']}."
    return base + (f" {extra}" if extra else "")


def _availability_line(facts):
    location = _first(facts.get("sender_location")) or "Berlin"
    german = _first(facts.get("german_level"))
    availability = _first(facts.get("availability"))
    parts = [f"Based in {location}"]
    if german:
        parts.append(f"German at {german}")
    if availability:
        parts.append(f"Available {availability}")
    return ". ".join(parts) + "."


def _cta(facts):
    resume = "My CV is attached. " if facts.get("has_resume") else ""
    return resume + "Could we connect briefly about potential working student or internship opportunities on your team?"


_LINK_LABELS = {"linkedin": "LinkedIn", "github": "GitHub", "portfolio": "Portfolio"}


def _signature(facts):
    """Layer 6 — name, phone, reply email, at most one profile link."""
    lines = [facts["sender_name"]]
    phone = _first(facts.get("phone"))
    email = _first(facts.get("contact_email"))
    if phone:
        lines.append(f"Phone: {phone}")
    if email:
        lines.append(f"Email: {email}")
    for key in ("linkedin", "github", "portfolio"):
        url = _first(facts.get(key))
        if url:
            lines.append(f"{_LINK_LABELS.get(key, key.capitalize())}: {url}")
            break
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Public template API
# --------------------------------------------------------------------------

def subject(facts):
    """Layer 5 — 'Working Student / Intern ({headline}) — {Company}'."""
    headline = focus_headline(facts)
    if headline:
        return f"Working Student / Intern ({headline}) — {facts['company']}"
    return f"Working Student / Intern (AI & Software Engineering) — {facts['company']}"


def _sections(facts):
    return [
        greeting(facts),
        _intro(facts),
        _hook_sentence(facts),
        _skills_line(facts),
        _role_line(facts),
        _availability_line(facts),
        _cta(facts),
        "Best regards,\n" + _signature(facts),
    ]


def plain_body(facts):
    return "\n\n".join(s for s in _sections(facts) if s and s.strip())


def html_body(facts):
    paragraphs = ["<p>" + html.escape(s).replace("\n", "<br>") + "</p>"
                  for s in _sections(facts) if s and s.strip()]
    return (
        "<html>\n"
        "  <body style=\"font-family: Arial, sans-serif; font-size: 14px; color: #222;\">\n"
        + "\n".join("    " + p for p in paragraphs) +
        "\n  </body>\n"
        "</html>"
    )
