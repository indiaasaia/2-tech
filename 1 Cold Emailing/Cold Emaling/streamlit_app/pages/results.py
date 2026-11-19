"""Results page: browse every pipeline CSV, auto-refreshing."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from core import paths, results


def _candidates() -> list[tuple[str, str, Path]]:
    """(label, description, path) for every viewable CSV."""
    return [
        ("Phase 1 · Discovered companies", "startup discovery output", paths.PHASE2_COMPANIES),
        ("Phase 2 · Contacts", "one row per discovered email", paths.PHASE2_RESULTS),
        ("Phase 2 · Outcomes", "per-company progress tracker", paths.PHASE2_OUTCOMES),
        ("Phase 3 · Verified Queue (contacts_to_send)", "clean deduplicated queue with MX checks", paths.PHASE3_QUEUED_CSV),
        ("Phase 3 · Sent history", "every send attempt (if any)", paths.PHASE3_HISTORY),
        ("Campaign · Tracking (tracking.csv)", "company application tracker", paths.PHASE3_TRACKING_CSV),
        ("Campaign · Rounds log (campaign_log.csv)", "round-by-round engine logs", paths.PHASE3_CAMPAIGN_LOG),
        ("Demo · Dry-run companies", "simulated dry-run output", paths.DEMO_COMPANIES),
        ("Demo · Dry-run contacts", "simulated dry-run contacts", paths.DEMO_RESULTS),
        ("Demo · Dry-run outcomes", "simulated dry-run outcomes", paths.DEMO_OUTCOMES),
    ]


def render() -> None:
    st.title("📂 Results")
    st.caption(
        "CSVs are the source of truth — the phases write them after every batch/company, "
        "so what you see here is always current. Auto-refresh keeps it live during a run."
    )

    options = {label: (desc, path) for label, desc, path in _candidates()}
    label = st.selectbox("Dataset", list(options))
    desc, path = options[label]

    st.caption(f"{desc} · `{path}`")

    auto = st.checkbox("🔁 Auto-refresh every 5 s", key="results_auto")
    _render_table(path, auto)


@st.fragment(run_every=5.0)
def _render_table(path: Path, auto: bool) -> None:
    frame = results.load_csv(path)
    if frame is None or frame.empty:
        st.info("No data yet — run the phase that produces this file, or do a dry run.")
        return
    st.caption(f"**{len(frame)}** row(s) × **{len(frame.columns)}** column(s)")
    st.dataframe(frame, width="stretch", hide_index=True)
    st.download_button(
        "⬇ Download CSV",
        data=frame.to_csv(index=False),
        file_name=path.name,
        mime="text/csv",
    )
    if auto:
        st.caption("🟢 Auto-refreshing — data updates in place.")
    else:
        st.button("Refresh now")
