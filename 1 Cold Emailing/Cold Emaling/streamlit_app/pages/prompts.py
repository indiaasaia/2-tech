"""Prompts page: edit every prompt template from the UI.

Each file is loaded into a text area; saving writes it back to disk with a
``.bak`` backup of the previous content, so nothing is ever lost.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from core import paths

# (label, path, hint)
PROMPT_FILES: list[tuple[str, Path, str]] = [
    (
        "Phase 1 · Startup discovery prompt",
        paths.PHASE1_PROMPT,
        "Uses `{{CITIES}}` (filled from Settings → Cities), `{target_count}` and `{total_cap}`.",
    ),
    (
        "Phase 2 · Contact discovery prompt (iteration 1)",
        paths.PHASE2_PROMPT,
        "Uses `{{COMPANY_NAME}}`. One company per research pass.",
    ),
    (
        "Phase 2 · Contact discovery prompt (iterations 2+)",
        paths.PHASE2_REPEAT_PROMPT,
        "Uses `{{COMPANY_NAME}}` and `{{PREVIOUS_EMAILS}}` (the exclusion list).",
    ),
    (
        "Phase 3 · Email text (email_text.py)",
        paths.PHASE3_EMAIL_TEXT,
        "⚠️ This is Python source, not a prompt — keep the `def subject(facts)` / "
        "`plain_body` / `html_body` structure intact.",
    ),
]


def render() -> None:
    st.title("✏️ Prompts")
    st.caption(
        "Edit the research prompts and the outreach email text. Every save creates a `.bak` "
        "backup next to the file. Changes apply to the **next** run."
    )

    loaded = _load_all()

    if st.button("↻ Reload from disk"):
        for key in [f"pf_{i}" for i in range(len(PROMPT_FILES))]:
            st.session_state.pop(key, None)
        st.rerun()

    for i, (label, path, hint) in enumerate(PROMPT_FILES):
        if f"pf_{i}" not in st.session_state:
            st.session_state[f"pf_{i}"] = loaded[i]
        with st.container(border=True):
            st.markdown(f"**{label}**")
            st.caption(hint)
            st.text_area(
                "content",
                height=420,
                key=f"pf_{i}",
                label_visibility="collapsed",
            )

    st.button("💾 Save all prompts", type="primary", on_click=_save_all)

    st.divider()
    st.markdown("### Placeholders you can use")
    st.code(
        "{{CITIES}}         → replaced with the city list from Settings (Phase 1)\n"
        "{target_count}     → batch size (Phase 1)\n"
        "{total_cap}        → total company cap (Phase 1)\n"
        "{{COMPANY_NAME}}   → current company (Phase 2)\n"
        "{{PREVIOUS_EMAILS}}→ emails already found for this company (Phase 2)"
    )


def _load_all() -> list[str]:
    contents = []
    for _, path, _ in PROMPT_FILES:
        try:
            contents.append(path.read_text(encoding="utf-8"))
        except OSError:
            contents.append("")
    return contents


def _save_all() -> None:
    saved = []
    for i, (label, path, _) in enumerate(PROMPT_FILES):
        content = st.session_state.get(f"pf_{i}", "")
        if not isinstance(content, str) or not content.strip():
            continue
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            backup = path.with_suffix(path.suffix + ".bak")
            if path.exists():
                backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            path.write_text(content, encoding="utf-8")
            saved.append(label)
        except OSError as exc:
            st.error(f"Could not save {label}: {exc}")
    if saved:
        st.success(f"Saved {len(saved)} file(s): {', '.join(saved)}")
