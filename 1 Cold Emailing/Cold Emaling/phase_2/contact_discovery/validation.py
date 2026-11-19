"""Email sanity checks for Phase 2.

The research prompts carry the hard accuracy rules (never guess, public
evidence only). This module only enforces what is mechanically checkable:
an email must look like a real address and a name must be non-empty.
"""
from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def is_valid_email(email: str) -> bool:
    """Basic structural check: exactly one @, no whitespace, plausible domain."""
    value = (email or "").strip()
    if not value:
        return False
    if " " in value or "|" in value:
        return False
    if value.count("@") != 1:
        return False
    return bool(_EMAIL_RE.match(value))


def is_plausible_name(name: str) -> bool:
    """A contact needs a readable label (person name or role team name)."""
    value = (name or "").strip()
    if not value:
        return False
    if value.lower() in {"name", "email", "n/a", "none", "-"}:
        return False
    # A name made of punctuation/separators only is not useful.
    return any(ch.isalnum() for ch in value)
