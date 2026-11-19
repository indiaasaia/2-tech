"""Parsing of Gemini's contact-research output.

The prompts demand a strict line format: ``Name | Email`` (one pair per
line) plus two sentinel tokens:

- ``NO_PUBLIC_EMAIL_FOUND``      — iteration 1: the company has no
  legitimate public email at all.
- ``NO_NEW_PUBLIC_EMAIL_FOUND``  — iterations 2+: nothing new beyond what
  was already found.

Parsing is deliberately strict: lines that do not match the format are
collected as problems (logged, never guessed at), and emails are de-duped
case-insensitively, exactly as the prompts require.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .validation import is_plausible_name, is_valid_email

SENTINEL_NO_PUBLIC = "NO_PUBLIC_EMAIL_FOUND"
SENTINEL_NO_NEW = "NO_NEW_PUBLIC_EMAIL_FOUND"

# A literal "Name | Email" header line the model might echo back.
_HEADER_EMAIL_TOKEN = "email"

_SENTINEL_RE = re.compile(r"NO_(?:NEW_)?PUBLIC_EMAIL_FOUND", flags=re.IGNORECASE)

# Markdown code fences the model might (wrongly) wrap its answer in.
_FENCE_RE = re.compile(r"^\s*```.*$", flags=re.IGNORECASE)


@dataclass(frozen=True)
class Contact:
    name: str
    email: str


@dataclass
class ParsedOutput:
    contacts: list[Contact] = field(default_factory=list)
    sentinel: str | None = None  # one of the two sentinel constants, if present
    problems: list[str] = field(default_factory=list)


def _find_sentinel(text: str) -> str | None:
    """Return the sentinel token present in the text, if any.

    The "no new" sentinel is checked first because it is the more specific
    outcome and both tokens could theoretically appear in one response.
    """
    if SENTINEL_NO_NEW in text.upper():
        return SENTINEL_NO_NEW
    if SENTINEL_NO_PUBLIC in text.upper():
        return SENTINEL_NO_PUBLIC
    return None


def parse_contact_output(text: str) -> ParsedOutput:
    """Parse raw model output into contacts + sentinel + problems."""
    result = ParsedOutput()
    if not text or not text.strip():
        result.problems.append("empty model output")
        return result

    result.sentinel = _find_sentinel(text)

    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _SENTINEL_RE.search(line) or _FENCE_RE.match(line):
            continue  # sentinel or code-fence line, not a contact
        if "|" not in line:
            result.problems.append(f"skipped line without '|': {line[:60]!r}")
            continue

        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 2:
            result.problems.append(f"skipped malformed line: {line[:60]!r}")
            continue

        name, email = parts
        if email.lower() == _HEADER_EMAIL_TOKEN:
            continue  # literal "Name | Email" header, not a real contact
        if not is_valid_email(email):
            result.problems.append(f"skipped invalid email {email!r}")
            continue
        if not is_plausible_name(name):
            result.problems.append(f"skipped empty/placeholder name {name!r}")
            continue

        key = email.lower()
        if key in seen:
            result.problems.append(f"duplicate email {email!r} skipped")
            continue
        seen.add(key)
        result.contacts.append(Contact(name=name, email=email))

    return result


def dedupe_contacts(contacts: list[Contact]) -> list[Contact]:
    """Case-insensitive dedup across iterations; first occurrence wins."""
    seen: set[str] = set()
    unique: list[Contact] = []
    for contact in contacts:
        key = contact.email.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(contact)
    return unique
