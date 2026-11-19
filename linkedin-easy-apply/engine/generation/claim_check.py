"""Done-work claims over keywords the KB does not back (profile + cover letter).

Policy v3: every job keyword may be PRINTED, but a keyword the candidate's KB
does not back may only appear in skills-list framing ("My toolkit also includes
X", "Role-relevant skills: X"), never as work done ("Using pandas I trained
models", "hands-on experience in NumPy"). Measured 2026-10-17 on 4 live jobs:
the LLM wrote such claims in 3/4 profiles and 3/4 letters despite the prompt
rule, so this check is deterministic. Zero LLM calls.
"""
from __future__ import annotations

import re

from engine.generation.keywords import _norm_key

# Sentence shapes that state the candidate DID / HAS something.
CLAIM_RE = re.compile(
    r"(?i)\b(built|developed|created|implemented|performed|trained|designed|delivered|delivering|"
    r"deployed|engineered|integrated|applied|applying(?!\s+(?:for|to)\b)|prepared|monitored|analy[sz]ed|tested|testing|"
    r"used|using|worked|work with|working with|experience[ds]?|expertise|proven|hands-on|background in|"
    r"skilled|proficient|as i did|gebaut|entwickelt|erstellt|implementiert|eingesetzt|erfahrung|"
    r"habe ich|arbeite mit)\b")
FIRST_PERSON_CLAIM_RE = re.compile(
    r"(?i)\bmy (?:experience|background|work|expertise)\b|\bI (?:have |had )?(?:built|developed|created|"
    r"implemented|used|worked|performed|trained|designed|delivered|deployed|engineered|integrated|"
    r"applied|analy[sz]ed|tested)\b|\bich habe\b|\bmeine erfahrung\b")
# Sentences that are an honest skills list (the policy's allowed framing).
SKILLS_LIST_RE = re.compile(
    r"(?i)^\s*(my (toolkit|skills?|skill set) (also )?(includes?|covers?|spans?)|"
    r"role-relevant skills|skills relevant to|further skills|"
    r"zu meinen (weiteren )?kenntnissen|weitere kenntnisse)")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_NON_CLAIM = ("soft_skills", "education_field")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split(" ".join(str(text or "").split())) if s.strip()]


def _term_re(term: str) -> re.Pattern:
    return re.compile(r"(?<![A-Za-z0-9+#])" + re.escape(term) + r"(?![A-Za-z0-9+#])", re.I)


def unbacked_terms(plan: dict | None, kb: dict) -> list[str]:
    """Plan keywords the KB does not back (technical + domain; soft skills excluded)."""
    from engine.verification.keyword_gate import kb_backing

    if not plan:
        return []
    out = list(kb_backing(plan, kb)["prep_terms"])
    backed = _backed_keys(kb)
    for keyword in plan.get("keywords") or []:
        if keyword.get("category") != "domain":
            continue
        term = str(keyword.get("term") or "")
        if _norm_key(term) not in backed and term not in out:
            out.append(term)
    return out


def _backed_keys(kb: dict) -> set[str]:
    from engine.generation import kb_loader
    from engine.generation.evidence_vocab import _keys_for, allowed_keys

    keys: set[str] = set()
    for skill in kb_loader.global_skills(kb):
        for name in [str(skill.get("name") or "")] + [str(a) for a in skill.get("aliases", [])]:
            keys |= set(_keys_for(name))
    for entry in kb_loader.experiences(kb) + kb_loader.projects(kb) + kb_loader.research(kb):
        keys |= allowed_keys(entry, kb)
    return keys


# What follows these markers is the job's work, not the candidate's past
# ("I can apply my API experience to Webhooks" claims APIs, not Webhooks).
_FORWARD_RE = re.compile(
    r"(?i)\b(?:I can|I could|I will|I would|I want to|I look forward|equips? me to|prepares? me to|"
    r"preparing me to|prepared me to|enables? me to|allows? me to|allowing me to|lets me|so that I can|"
    r"ready to|to help|kann ich|werde ich|möchte ich)\b")


def _without(sentence: str, exclude: tuple[str, ...]) -> str:
    """The sentence minus quoted job-title text ("I am applying for the Working
    Student Data Science position" names the role, it claims nothing) and minus
    the forward-looking tail."""
    for phrase in sorted((p for p in exclude if p and p.strip()), key=len, reverse=True):
        sentence = re.sub(re.escape(phrase.strip()), " ", sentence, flags=re.I)
    return _FORWARD_RE.split(sentence, maxsplit=1)[0]


def claim_sentences(text: str, kb: dict, plan: dict | None, exclude: tuple[str, ...] = (),
                    first_person_only: bool = False) -> list[tuple[str, list[str]]]:
    """(sentence, unbacked terms) for every sentence that states an unbacked keyword as done work."""
    terms = unbacked_terms(plan, kb)
    if not terms:
        return []
    pattern = FIRST_PERSON_CLAIM_RE if first_person_only else CLAIM_RE
    out: list[tuple[str, list[str]]] = []
    for sentence in sentences(text):
        claim_part = _without(sentence, exclude)
        if SKILLS_LIST_RE.match(sentence) or not pattern.search(claim_part):
            continue
        hits = [t for t in terms if _term_re(t).search(claim_part)]
        if hits:
            out.append((sentence, hits))
    return out


def claim_violations(text: str, kb: dict, plan: dict | None, exclude: tuple[str, ...] = (),
                     first_person_only: bool = False) -> list[str]:
    """Findings: an unbacked keyword inside a sentence that claims done work.
    `exclude` = job-title forms to ignore (the title is quoted, not claimed).
    `first_person_only` (letter motivation): only explicit "I built / my experience"
    sentences count; "the chance to apply data science here" talks about the role."""
    return [f"claim: {', '.join(hits)} stated as done work, but the KB does not back it "
            f"(only allowed in a skills list): {sentence[:90]!r}"
            for sentence, hits in claim_sentences(text, kb, plan, exclude, first_person_only)]


def drop_sentences(text: str, bad: list[str]) -> str:
    """`text` without the listed sentences (matched on their first 50 characters)."""
    keys = [" ".join(b.split())[:50].lower() for b in bad if b and b.strip()]
    return " ".join(s for s in sentences(text) if not any(s.lower().startswith(k) or k.startswith(s.lower()[:50])
                                                          for k in keys))


def violating_terms(text: str, kb: dict, plan: dict | None) -> list[str]:
    out: list[str] = []
    for _sentence, hits in claim_sentences(text, kb, plan):
        out += [t for t in hits if t not in out]
    return out


def honest_profile(profile: str, kb: dict, plan: dict | None, max_words: int = 75) -> tuple[str, list[str]]:
    """(profile, findings): drop claim sentences over unbacked keywords and list
    those keywords in one honest skills sentence instead (keyword coverage kept)."""
    from engine.verification.keyword_gate import kb_backing

    findings = claim_violations(profile, kb, plan)
    if not findings:
        return profile, []
    # only technical terms move to the skills sentence; a domain phrase ("industry
    # trends") reads oddly as a skill and is printed in the Skills rows anyway
    technical = set(kb_backing(plan, kb)["prep_terms"]) if plan else set()
    moved = [t for t in violating_terms(profile, kb, plan) if t in technical]
    bad = {sentence for sentence, _hits in claim_sentences(profile, kb, plan)}
    kept = [s for s in sentences(profile) if s not in bad]
    backed = kb_backing(plan, kb)["kb_backed"][:6] if plan else []
    work = (", ".join(backed[:-1]) + " and " + backed[-1]) if len(backed) > 1 else (backed[0] if backed else
            "Python APIs, data pipelines, machine learning models and AI agent workflows")
    lead = ("MSc Artificial Intelligence student at BTU Cottbus-Senftenberg and former Software Engineer "
            f"with hands-on work in {work}.")
    if not kept or not kept[0].lower().startswith(("msc", "master")):
        kept.insert(0, lead)
    text = " ".join(kept)
    listed = [t for t in moved if not _term_re(t).search(text)]
    if listed:
        tail = listed[-1] if len(listed) == 1 else ", ".join(listed[:-1]) + " and " + listed[-1]
        text += f" Role-relevant skills: {tail}."
    words = text.split()
    if len(words) > max_words and len(kept) > 1:
        # drop middle LLM sentences first; the lead and the skills sentence carry the facts + keywords
        while len(text.split()) > max_words and len(kept) > 1:
            kept.pop(-1)
            text = " ".join(kept) + (f" Role-relevant skills: {tail}." if listed else "")
    return text, findings
