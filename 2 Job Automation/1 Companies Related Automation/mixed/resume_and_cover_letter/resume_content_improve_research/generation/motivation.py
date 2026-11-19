"""Structured professional-motivation profile (cover-letter personalization).

The CV states what the candidate has done. This profile states what kind of
work interests them, how they prefer to work, and where they want to develop —
each statement traced to KB evidence ids. Selection is deterministic and
zero-LLM: entries score against the analyst's required/preferred/tools/title
vocabulary, so different role families pick different approved material.

Supported conceptual sections (either in `entries` with `category`, or in the
dedicated category lists `professional_interests`, `working_preferences`, and
`career_direction`):
  A. Professional interests (`category = "interest"`):
     `domains`, `problems`, `activities`, `text_de`, `text_en`
  B. Working preferences (`category = "preference"`):
     `responsibilities`, `approach`, `work_environment`, `text_de`, `text_en`
  C. Career direction (`category = "direction"`):
     `target_direction`, `skills_to_develop`, `long_term_objective`, `text_de`, `text_en`
  D. Supporting evidence:
     `evidence` (KB entry ids), `supporting_examples`, `skills` (owned KB skills)
  E. Job relevance:
     `role_families`, `keywords`

Truthfulness contract:
  - The profile is OPTIONAL. A KB without it behaves exactly as before
    (honest generic fallback, no invented motivation).
  - An entry is selectable ONLY if: profile is not marked DRAFT_PENDING_REVIEW
    or UNAPPROVED, `approved` is not False, `id` is unique, `category` is known,
    body text in the letter language is present (and free of TODO/GUESS
    placeholders), `evidence` is non-empty and resolvable against
    `kb_loader.evidence_ids(kb)`, owned `skills` belong to the KB and are not
    forbidden on the cited evidence entries, and no digits appear in texts.
  - Job requirements guide SELECTION only. They never become evidence of
    motivation: an interest not in the approved profile can never be emitted.
"""
from __future__ import annotations

import re

CATEGORIES = ("interest", "preference", "direction")
SECTION_CATEGORY_MAP = (
    ("professional_interests", "interest"),
    ("working_preferences", "preference"),
    ("career_direction", "direction"),
)
UNAPPROVED_STATUSES = {"DRAFT_PENDING_REVIEW", "UNAPPROVED", "REJECTED"}

_DIGIT_RE = re.compile(r"\d")
_PLACEHOLDER_RE = re.compile(r"(?i)\b(TODO_CANDIDATE|GUESS|PLACEHOLDER_ONLY)\b")


def get_profile(kb: dict) -> dict:
    """Return the raw motivation_profile dict ({} when absent — backward compat)."""
    profile = (kb or {}).get("motivation_profile")
    return profile if isinstance(profile, dict) else {}


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v or "").strip()]
    return []


def entries(kb: dict) -> list[dict]:
    """All raw entries across `entries` and the category subsections (order preserved)."""
    profile = get_profile(kb)
    if not profile:
        return []
    collected: list[dict] = []
    for section_key, default_category in SECTION_CATEGORY_MAP:
        section_items = profile.get(section_key)
        if isinstance(section_items, list):
            for item in section_items:
                if isinstance(item, dict):
                    normalized = dict(item)
                    normalized.setdefault("category", default_category)
                    collected.append(normalized)
    raw = profile.get("entries")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                collected.append(dict(item))
    return collected


def needs_candidate_input(kb: dict) -> bool:
    """True when the profile is missing/empty or explicitly flagged."""
    profile = get_profile(kb)
    if not profile or not entries(kb):
        return True
    if str(profile.get("status") or "").upper() in ("NEEDS_CANDIDATE_INPUT", "DRAFT_PENDING_REVIEW"):
        return True
    return bool(profile.get("needs_candidate_input", False))


def _evidence_ids(kb: dict) -> set[str]:
    from resume_content_improve_research.generation import kb_loader

    try:
        return set(kb_loader.evidence_ids(kb))
    except Exception:  # noqa: BLE001 - never crash selection on KB read issues
        return {"master_cv"}


def _kb_ownable_and_forbidden(kb: dict | None) -> tuple[set[str], dict[str, set[str]]]:
    """Return (ownable_skill_keys, forbidden_by_evidence_id) from `kb`."""
    if not isinstance(kb, dict):
        return set(), {}
    from resume_content_improve_research.generation.normalize import normalize_skill

    ownable: set[str] = set()
    for skill in kb.get("skills", []) or []:
        if isinstance(skill, dict) and skill.get("name"):
            ownable.add(normalize_skill(str(skill["name"])).casefold())
            for alias in skill.get("aliases", []) or []:
                ownable.add(normalize_skill(str(alias)).casefold())
    forbidden_by_id: dict[str, set[str]] = {}
    for section in ("experience", "projects"):
        for item in kb.get(section, []) or []:
            if not isinstance(item, dict):
                continue
            eid = str(item.get("id") or "")
            for allowed in item.get("skills_allowed", []) or []:
                ownable.add(normalize_skill(str(allowed)).casefold())
            if eid:
                forbidden_by_id[eid] = {
                    normalize_skill(str(f)).casefold()
                    for f in (item.get("skills_forbidden") or [])
                    if str(f or "").strip()
                }
    return ownable, forbidden_by_id


def _compose_from_structured(entry: dict, language: str) -> str:
    """Deterministic prose synthesis when structured fields are given without text_de/text_en."""
    category = entry.get("category")
    if category == "interest":
        domains = _as_str_list(entry.get("domains"))
        problems = _as_str_list(entry.get("problems"))
        activities = _as_str_list(entry.get("activities"))
        parts = domains + problems + activities
        if not parts:
            return ""
        joined = ", ".join(parts[:3])
        if language == "de":
            return f"Fachlich interessiert mich insbesondere die Arbeit im Bereich {joined}."
        return f"Professionally, I am particularly interested in work involving {joined}."
    if category == "preference":
        resp = _as_str_list(entry.get("responsibilities"))
        approach = _as_str_list(entry.get("approach"))
        env = _as_str_list(entry.get("work_environment"))
        parts = resp + approach + env
        if not parts:
            return ""
        joined = ", ".join(parts[:3])
        if language == "de":
            return f"In meiner Arbeitsweise schätze ich Aufgaben mit Fokus auf {joined}."
        return f"In my work, I value responsibilities focused on {joined}."
    if category == "direction":
        target = _as_str_list(entry.get("target_direction"))
        dev = _as_str_list(entry.get("skills_to_develop"))
        obj = _as_str_list(entry.get("long_term_objective"))
        parts = target + dev + obj
        if not parts:
            return ""
        joined = ", ".join(parts[:3])
        if language == "de":
            return f"Langfristig möchte ich meine Kenntnisse in Richtung {joined} gezielt vertiefen."
        return f"Long term, I want to deepen my capabilities toward {joined}."
    return ""


def entry_text(entry: dict, language: str) -> str:
    """Body text for the letter language ('' when not provided)."""
    key = "text_de" if language == "de" else "text_en"
    alt_key = "statement_de" if language == "de" else "statement_en"
    text = str(entry.get(key) or entry.get(alt_key) or "").strip()
    if text:
        return text
    return _compose_from_structured(entry, language)


def entry_valid(entry: dict, evidence: set[str], kb: dict | None = None) -> list[str]:
    """Structural and truthfulness problems with one entry (empty = valid)."""
    problems: list[str] = []
    eid_label = entry.get("id")
    if not str(eid_label or "").strip():
        problems.append("motivation entry without 'id'")
    if entry.get("approved") is False:
        problems.append(f"motivation entry {eid_label!r}: explicitly marked approved=False")
    cat = str(entry.get("category") or "")
    if cat == "working_preference":
        cat = "preference"
    elif cat == "career_direction":
        cat = "direction"
    if cat not in CATEGORIES:
        problems.append(
            f"motivation entry {eid_label!r}: category must be one of {CATEGORIES}"
        )
    text_de = entry_text(entry, "de")
    text_en = entry_text(entry, "en")
    if not text_de and not text_en:
        problems.append(f"motivation entry {eid_label!r}: text_de/text_en both empty")
    ev = entry.get("evidence") or entry.get("evidence_ids") or []
    if not isinstance(ev, list) or not ev:
        problems.append(f"motivation entry {eid_label!r}: empty evidence")
        ev = []
    for eid in ev:
        base = str(eid).split()[0] if str(eid).strip() else ""
        if base not in evidence:
            problems.append(
                f"motivation entry {eid_label!r}: unknown evidence id {eid!r}"
            )
    for key in ("text_de", "text_en"):
        val = str(entry.get(key) or "")
        if _DIGIT_RE.search(val):
            problems.append(
                f"motivation entry {eid_label!r}: {key} contains digits "
                "(letter body allows zero digits)"
            )
        if _PLACEHOLDER_RE.search(val):
            problems.append(
                f"motivation entry {eid_label!r}: {key} contains unconfirmed placeholder/GUESS text"
            )
    for ex in _as_str_list(entry.get("supporting_examples")):
        if _DIGIT_RE.search(ex):
            problems.append(
                f"motivation entry {eid_label!r}: supporting_examples contains digits"
            )
        if _PLACEHOLDER_RE.search(ex):
            problems.append(
                f"motivation entry {eid_label!r}: supporting_examples contains placeholder/GUESS text"
            )
    if _PLACEHOLDER_RE.search(str(eid_label or "")):
        problems.append(
            f"motivation entry {eid_label!r}: id contains unconfirmed placeholder/GUESS marker"
        )

    # Traceability check between entry['skills'] (owned skills) and KB / cited evidence
    ownable, forbidden_by_id = _kb_ownable_and_forbidden(kb)
    skill_list = _as_str_list(entry.get("skills") or entry.get("related_skills"))
    if ownable and skill_list:
        from resume_content_improve_research.generation.normalize import normalize_skill

        for skill in skill_list:
            norm_skill = normalize_skill(skill).casefold()
            if norm_skill not in ownable:
                problems.append(
                    f"motivation entry {eid_label!r}: skill {skill!r} is not in KB ownable skills "
                    "(use 'skills_to_develop' for learning targets)"
                )
            for ref_id in ev:
                base = str(ref_id).split()[0] if str(ref_id).strip() else ""
                if norm_skill in forbidden_by_id.get(base, set()):
                    problems.append(
                        f"motivation entry {eid_label!r}: skill {skill!r} is in "
                        f"skills_forbidden of cited evidence {base!r}"
                    )
    return problems


def validate_profile(kb: dict) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for the optional motivation_profile section."""
    errors: list[str] = []
    warnings: list[str] = []
    profile = (kb or {}).get("motivation_profile")
    if profile is None:
        return errors, warnings  # absent = valid (backward compatible)
    if not isinstance(profile, dict):
        return ["motivation_profile must be an object"], warnings

    status = str(profile.get("status") or "").strip().upper()
    if status in UNAPPROVED_STATUSES:
        warnings.append(
            f"motivation_profile.status is {status!r} — entries will not be used "
            "until status is APPROVED"
        )

    raw_entries = profile.get("entries", [])
    if raw_entries is not None and not isinstance(raw_entries, list):
        return ["motivation_profile.entries must be a list"], warnings
    for section_key, _cat in SECTION_CATEGORY_MAP:
        sec = profile.get(section_key)
        if sec is not None and not isinstance(sec, list):
            errors.append(f"motivation_profile.{section_key} must be a list")

    all_entries = entries(kb)
    if not all_entries:
        warnings.append(
            "motivation_profile.entries is empty — letters use the honest "
            "generic fallback until candidate-approved entries are added "
            "(see knowledge_base/motivation_input_guide.json)"
        )
        return errors, warnings

    evidence = _evidence_ids(kb)
    seen: set[str] = set()
    for entry in all_entries:
        if not isinstance(entry, dict):
            errors.append("motivation_profile entries must contain objects")
            continue
        eid = str(entry.get("id") or "")
        if eid in seen:
            errors.append(f"motivation entry id duplicated: {eid!r}")
        seen.add(eid)
        errors.extend(f"motivation_profile: {p}" for p in entry_valid(entry, evidence, kb=kb))
    if profile.get("needs_candidate_input"):
        warnings.append(
            "motivation_profile.needs_candidate_input is set — entries present "
            "are usable, but the candidate has more to add"
        )
    return errors, warnings


def _norm_terms(values: object) -> set[str]:
    from resume_content_improve_research.generation.normalize import normalize_skill

    out: set[str] = set()
    if isinstance(values, str):
        values = [values]
    for value in values or []:
        if isinstance(value, dict):  # languages_required entries
            value = str(value.get("language") or "")
        raw_str = str(value or "").strip()
        if not raw_str:
            continue
        norm = normalize_skill(raw_str).casefold().strip()
        if norm:
            out.add(norm)
        raw_low = raw_str.casefold()
        if raw_low:
            out.add(raw_low)
    return out


def _entry_vocabulary(entry: dict) -> set[str]:
    """Collect normalized matching terms across relevance and structured content fields.

    Note: `skills_to_develop` is intentionally excluded from selection matching so
    a mirrorable JD tool alone never triggers motivation selection without an
    overlap in core keywords, owned skills, role families, or domains.
    """
    vocab: set[str] = set()
    for field_name in (
        "keywords",
        "skills",
        "role_families",
        "domains",
        "problems",
        "activities",
        "responsibilities",
        "approach",
        "work_environment",
        "target_direction",
    ):
        vocab |= _norm_terms(entry.get(field_name) or [])
    return vocab


def _vocab_overlap(entry_vocab: set[str], job_vocab: set[str]) -> int:
    """Count entry terms matched in job_vocab (exact or whole-word boundary in phrase)."""
    matched: set[str] = set()
    for term in entry_vocab:
        if not term:
            continue
        if term in job_vocab:
            matched.add(term)
            continue
        if len(term) >= 4:
            pattern = re.compile(rf"(?<![\w+#.\-]){re.escape(term)}(?![\w+#.\-])")
            if any(pattern.search(jterm) for jterm in job_vocab if len(jterm) > len(term)):
                matched.add(term)
    return len(matched)


def selectable_entries(kb: dict, language: str) -> list[dict]:
    """Valid, approved entries with a body text in the letter language (stable order)."""
    profile = get_profile(kb)
    status = str(profile.get("status") or "").strip().upper()
    if status in UNAPPROVED_STATUSES:
        return []
    evidence = _evidence_ids(kb)
    valid: list[dict] = []
    seen_ids: set[str] = set()
    for entry in entries(kb):
        eid = str(entry.get("id") or "")
        if eid in seen_ids:
            continue
        if entry_valid(entry, evidence, kb=kb):
            continue
        if not entry_text(entry, language).strip():
            continue
        seen_ids.add(eid)
        valid.append(entry)
    return valid


def select_motivation_entries(
    analysis_dict: dict,
    kb: dict,
    language: str = "de",
    limit: int = 2,
    job: dict | None = None,
) -> tuple[list[dict], dict]:
    """Deterministically pick the most job-relevant approved entries.

    Score = weighted overlap between the entry's structured vocabulary and the
    job's (required ∪ preferred ∪ tools ∪ domain ∪ title words) vocabulary.
    Ties break by entry id so identical inputs always select identically
    (zero LLM, reproducible).

    Returns (selected, meta) where meta records source ids, backing evidence ids,
    matched development targets, and fallback reason for the letters report.
    Empty selection is NOT an error — the generator uses the honest generic
    fallback instead of inventing motivation.
    """
    analysis_dict = analysis_dict or {}
    candidates = selectable_entries(kb, language)
    meta: dict = {
        "motivation_source": "none",
        "motivation_entry_ids": [],
        "motivation_evidence_ids": [],
        "development_targets": [],
        "motivation_fallback_reason": "",
    }
    if not candidates:
        meta["motivation_source"] = "fallback_no_profile"
        if not entries(kb):
            meta["motivation_fallback_reason"] = (
                "no motivation_profile.entries — generic fallback, no interests inferred"
            )
        else:
            meta["motivation_fallback_reason"] = (
                "no selectable entries for this language/evidence — generic fallback"
            )
        return [], meta

    job_vocab = (
        _norm_terms((analysis_dict.get("required") or []))
        | _norm_terms((analysis_dict.get("preferred") or []))
        | _norm_terms((analysis_dict.get("tools") or []))
        | _norm_terms((analysis_dict.get("domain") or []))
    )
    title = str(analysis_dict.get("title_core") or analysis_dict.get("title") or "")
    job_vocab |= _norm_terms(re.findall(r"[A-Za-zÄÖÜäöüß+#.\-]{2,}", title))

    scored: list[tuple[int, int, str, dict]] = []
    for entry in candidates:
        entry_vocab = _entry_vocabulary(entry)
        overlap = _vocab_overlap(entry_vocab, job_vocab)
        # Small category prior so career-direction entries do not crowd out
        # concrete interests when scores tie; interests carry Paragraph 3.
        # The prior never creates a match: zero overlap always falls back.
        prior = {"interest": 2, "preference": 1, "direction": 0}.get(
            entry.get("category"), 0
        )
        scored.append((overlap, overlap * 10 + prior, str(entry.get("id") or ""), entry))

    scored.sort(key=lambda item: (-item[1], item[2]))
    overlapping = [item for item in scored if item[0] > 0]
    if not overlapping:
        meta["motivation_source"] = "fallback_no_overlap"
        meta["motivation_fallback_reason"] = (
            "no approved entry overlaps this posting's vocabulary — "
            "generic fallback, nothing inferred from the JD"
        )
        return [], meta

    max_items = max(1, limit)
    selected: list[dict] = [item[3] for item in overlapping[:max_items]]

    # When limit >= 2 and an overlapping 'direction' entry exists for Paragraph 4
    # but was crowded out by multiple interest/preference entries, reserve the
    # last slot for the highest-scoring overlapping direction entry.
    if max_items >= 2 and not any(e.get("category") == "direction" for e in selected):
        top_direction = next(
            (item[3] for item in overlapping if item[3].get("category") == "direction"),
            None,
        )
        if top_direction is not None:
            selected = selected[: max_items - 1] + [top_direction]

    evidence_ids: list[str] = []
    dev_targets: list[str] = []
    for entry in selected:
        for ev in entry.get("evidence") or entry.get("evidence_ids") or []:
            base = str(ev).split()[0] if str(ev).strip() else ""
            if base and base not in evidence_ids:
                evidence_ids.append(base)
        for target in _as_str_list(entry.get("skills_to_develop")):
            if _vocab_overlap(_norm_terms([target]), job_vocab) > 0 and target not in dev_targets:
                dev_targets.append(target)

    meta["motivation_source"] = "profile"
    meta["motivation_entry_ids"] = [str(e.get("id")) for e in selected]
    meta["motivation_evidence_ids"] = evidence_ids
    meta["development_targets"] = dev_targets
    return selected, meta
