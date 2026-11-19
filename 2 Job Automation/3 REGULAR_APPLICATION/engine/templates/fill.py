"""LaTeX escaping + collision-proof template filling for the v2 engine.

The filler replaces @@TOKENS@@ longest-first by construction (every token is a
full @@...@@ name, no token is a substring of another) and then asserts none
survive — V4's `assert "PROJECT-" not in text` generalized to the whole token set.
"""
from __future__ import annotations

import re

from engine import config

_UNITYPE_FIXES = {
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-",
    "\u00a0": " ", "\u2007": " ", "\u202f": " ",
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
    "\ufb05": "st", "\ufb06": "st",
}

# Character PAIRS that the NoCommon font still ligates across tokens when the model
# emits doubled letters (measured on the 21-job run: "eﬀiciently" -> 'ﬀ' survived as
# a single glyph from 'ff'). Collapsing 'ff' would corrupt spelling, so instead the
# double-f pairs get a zero-width break: LaTeX-safe via 'f{}f'.
_DOUBLE_F_FIX = re.compile(r"ff", re.IGNORECASE)


def clean_text(text: object) -> str:
    """Normalize unicode punctuation and flatten whitespace for LaTeX output."""
    result = " ".join(str(text or "").split())
    for character, fix in _UNITYPE_FIXES.items():
        result = result.replace(character, fix)
    return result.strip()


def escape_latex(text: object) -> str:
    """Escape every LaTeX-special character in a generated value.

    Also breaks 'ff' pairs with f{}f: even with Ligatures=NoCommon the XeTeX
    shaper formed an 'ﬀ' glyph for doubled f (V4 measured 18->6, not 0); the
    brace break is invisible in print but blocks glyph merging in extraction.
    """
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    result = clean_text(text)
    for character, token in replacements.items():
        result = result.replace(character, token)
    # The ff-break must run AFTER the brace escaping: run before it, the inserted
    # '{}' was escaped to '\{\}' and printed literally ("Traf{}fic Management",
    # measured 2026-10-17 on the v3 run; every 'ff' keyword was unmatchable).
    result = _DOUBLE_F_FIX.sub(lambda m: m.group(0)[0] + "{}" + m.group(0)[1], result)
    return result


def join_items(items: list[str]) -> str:
    """Escape and join a skill list into one template line."""
    return ", ".join(escape_latex(item) for item in items if clean_text(item))


_UNESCAPED_SPECIAL = re.compile(r"(?<!\\)[&%$#_]")
_TOKEN_SPAN = re.compile(r"@@[^@]*@@")


def fill_template(template: str, values: dict[str, object], tokens: tuple[str, ...] | None = None) -> str:
    r"""Fill every @@TOKEN@@ with its value; assert none survive.

    CONTRACT: values are FINAL LaTeX fragments — they MUST already be escaped
    (escape_latex / join_items). The filler deliberately does NOT escape again:
    escape_latex is not idempotent (R&D -> R\&D -> R\textbackslash{}\&D), so a
    re-escape here corrupted every value containing & % $ # _ (measured: the
    E2E letter build, and several shipped resume .tex artifacts carry the
    '\textbackslash' signature). The unescaped-specials guard below fails loud
    instead of shipping corrupted output.

    Tokens are replaced longest-first so no token name can ever be a prefix of
    another (the V4 collision class), and the result is asserted token-free.
    `tokens` selects the template's token namespace: the resume set (default)
    or the cover-letter set (config.CL_ALL_TOKENS).
    """
    token_set = tuple(tokens) if tokens is not None else config.ALL_TOKENS
    text = template
    for token in sorted(token_set, key=len, reverse=True):
        value = values.get(token)
        if value is None:
            raise RuntimeError(f"template token {token} has no value")
        escaped = str(value)
        # @@...@@ spans inside a value are template cross-references (handled by
        # the resurrection loop below), not content: exempt them from the scan.
        if _UNESCAPED_SPECIAL.search(_TOKEN_SPAN.sub("", escaped)):
            raise RuntimeError(
                f"value for {token} contains unescaped LaTeX specials — "
                "pass escape_latex()/join_items() output (filler never escapes)"
            )
        text = text.replace(token, escaped)
        # a value that itself contained a @@TOKEN@@ string would resurrect a
        # token after later replacements; loop until stable (idempotent for
        # clean values), then the final leftover assert still holds.
        for _ in range(4):
            if "@@" not in text:
                break
            changed = False
            for inner in sorted(token_set, key=len, reverse=True):
                if inner in text:
                    text = text.replace(inner, escaped if inner == token else values.get(inner, ""))
                    changed = True
            if not changed:
                break
    leftover = [token for token in token_set if token in text]
    if leftover:
        raise RuntimeError(f"unfilled template tokens remain: {leftover}")
    if "@@" in text:
        raise RuntimeError("stray '@@' remains after filling (unknown or resurrected token)")
    # V4's killer assert, verbatim (V4 §2): a literal PROJECT- in the filled text
    # was the shipped-bug signature in 21/21 PDFs. DESCRIPTION-/ROLE- etc. with a
    # digit are the same collision family. Case-sensitive on purpose.
    if "PROJECT-" in text or re.search(r"\b(SKILLS|DESCRIPTION|ROLE|CAREER)-\d", text):
        raise RuntimeError("legacy placeholder prefix leaked into the artifact (V4 collision class)")
    return text
