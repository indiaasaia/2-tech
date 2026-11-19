"""ATS-safe typography for generated text.

Measured 2026-10-17: gpt-oss writes non-breaking hyphens (U+2011, "black‑box",
"Python‑based") and narrow no-break spaces. They render like normal characters,
but the DOCX text layer keeps them, so an ATS search for "real-time" misses
"real‑time". Every generated sentence goes through plain_typography().
"""
from __future__ import annotations

_MAP = str.maketrans({
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2212": "-", "\u00ad": "",
    "\u00a0": " ", "\u202f": " ", "\u2007": " ", "\u2009": " ", "\u200b": "",
})


def plain_typography(text: str) -> str:
    return str(text or "").translate(_MAP)
