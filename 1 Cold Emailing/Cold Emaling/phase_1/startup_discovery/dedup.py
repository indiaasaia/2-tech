"""Company name/website normalization and duplicate detection.

The CSV is the source of truth. A candidate is a duplicate if its
normalized name OR its normalized website domain matches an existing
record (or another candidate in the same batch).
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

# Legal-form suffixes removed from names before comparison.
_SUFFIX_TOKENS = {
    "gmbh", "ag", "inc", "llc", "ltd", "limited", "se", "plc", "ug",
    "holding", "holdings", "corp", "corporation", "co", "kg", "bv",
    "nv", "sarl", "sas", "sro", "oy", "pte", "sl", "sa", "gbr", "ehf",
    "spa", "ab", "as", "kk", "llp", "lp", "fz", "fzc", "wll", "bhd",
}

# German umlauts -> plain ASCII so "München" and "Munchen" dedupe.
_UMLAUTS = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss"})
_NON_WORD_RE = re.compile(r"[^\w]+")  # \w is Unicode-aware
_URL_SCHEME_RE = re.compile(r"^https?://", flags=re.IGNORECASE)


def _fold(name: str) -> str:
    """Map umlauts to ASCII and strip other accents (NFD decomposition)."""
    name = name.translate(_UMLAUTS)
    decomposed = unicodedata.normalize("NFD", name)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_name(name: str) -> str:
    """Lowercase, drop punctuation and legal-form suffixes."""
    if not name:
        return ""
    tokens = _NON_WORD_RE.sub(" ", _fold(name.lower())).split()
    tokens = [t for t in tokens if t not in _SUFFIX_TOKENS]
    return " ".join(tokens).strip()


def normalize_domain(website: str) -> str:
    """Return the lowercased, www-stripped hostname, or '' if invalid."""
    if not website:
        return ""
    url = website.strip()
    if not _URL_SCHEME_RE.match(url):
        url = "https://" + url
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    if ":" in host:  # strip port, e.g. acme.com:8080
        host = host.split(":", 1)[0]
    if not host or " " in host:  # garbage input -> no usable domain
        return ""
    return host


def is_duplicate(candidate: dict, existing: dict) -> bool:
    """True when `candidate` matches `existing` by normalized name or domain."""
    cand_name = normalize_name(str(candidate.get("company_name") or ""))
    cand_domain = normalize_domain(str(candidate.get("website") or ""))
    if not cand_name and not cand_domain:
        return False
    ex_name = normalize_name(str(existing.get("company_name") or ""))
    ex_domain = normalize_domain(str(existing.get("website") or ""))
    return bool(
        (cand_name and ex_name and cand_name == ex_name)
        or (cand_domain and ex_domain and cand_domain == ex_domain)
    )


def filter_new(candidates: list[dict], existing: list[dict]) -> list[dict]:
    """Return candidates that are new relative to `existing` and to each other."""
    new: list[dict] = []
    for candidate in candidates:
        if any(is_duplicate(candidate, record) for record in existing):
            continue
        if any(is_duplicate(candidate, record) for record in new):
            continue
        new.append(candidate)
    return new
