"""Run page: start/stop pipeline phases and watch them live.

Architecture: the phase runs on a daemon thread (core.runners). The log
lines land in a thread-safe buffer; a ``st.fragment(run_every=...)`` block
re-renders itself every couple of seconds, so the log, progress bars and
Stop button stay live while the worker thread does the work.
"""
from __future__ import annotations

import time

import streamlit as st

from core import paths, results, settings as settings_mod
from core.runners import RunHandle, make_handle

PHASE_OPTIONS = {
    "Phase 1 — Startup discovery": "phase1",
    "Phase 2 — Contact discovery": "phase2",
    "Phase 3 — Email sender (preview / test)": "phase3",
}


def _collect_overrides(phase: str) -> dict:
    """Read the run-time override widgets from session_state."""
    overrides: dict = {}
    if phase == "phase1":
        cities_text = str(st.session_state.get("run_p1_cities", ""))
        overrides["cities"] = [c.strip() for c in cities_text.split(",") if c.strip()]
        overrides["batch_size"] = int(st.session_state.get("run_p1_batch", 5))
        overrides["total_cap"] = int(st.session_state.get("run_p1_cap", 50))
        overrides["min_hiring_score"] = int(st.session_state.get("run_p1_score", 55))
        overrides["model"] = str(st.session_state.get("run_p1_model", "")).strip() or None
    elif phase == "phase2":
        overrides["max_iterations"] = int(st.session_state.get("run_p2_iters", 3))
        limit = int(st.session_state.get("run_p2_limit", 0))
        overrides["limit"] = limit or None
        overrides["temperature"] = float(st.session_state.get("run_p2_temp", 0.2))
        overrides["model"] = str(st.session_state.get("run_p2_model", "")).strip() or None
    return {k: v for k, v in overrides.items() if v is not None}


def _start(phase: str, dry_run: bool, phase3_mode: str) -> None:
    overrides = _collect_overrides(phase)
    handle = make_handle(phase, dry_run=dry_run, phase3_mode=phase3_mode, overrides=overrides)
    st.session_state["run_handle"] = handle
    st.toast(f"Started {handle.label}")
    st.rerun()


def _stop() -> None:
    handle = st.session_state.get("run_handle")
    if handle and handle.running:
        handle.request_stop()
        st.toast("Stop requested — finishing current step…")


def render() -> None:
    st.title("▶ Run the pipeline")
    cfg = settings_mod.load()
    handle: RunHandle | None = st.session_state.get("run_handle")

    with st.container(border=True):
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            phase_name = st.selectbox("Stage", list(PHASE_OPTIONS), key="run_stage")
        with col2:
            dry_run = st.checkbox("🧪 DRY RUN (simulated, no API calls)", key="run_dry")
        with col3:
            phase3_mode = st.selectbox(
                "Phase 3 mode",
                ["preview", "test"],
                format_func=lambda m: "Preview plan (dry-run)" if m == "preview" else "Test (1 email to TEST_RECIPIENT)",
                key="run_phase3_mode",
            )

        phase = PHASE_OPTIONS[phase_name]
        with st.expander("Run-time overrides (don't affect saved settings)", expanded=False):
            if phase == "phase1":
                cities_text = st.text_input(
                    "Cities (comma separated)", value=", ".join(settings_mod.cities(cfg)), key="run_p1_cities"
                )
                c1, c2, c3 = st.columns(3)
                batch = c1.number_input("Batch size", 1, 20, int(cfg["phase1"]["batch_size"]), key="run_p1_batch")
                cap = c2.number_input("Total cap", 1, 500, int(cfg["phase1"]["total_cap"]), key="run_p1_cap")
                score = c3.number_input("Min score", 0, 100, int(cfg["phase1"]["min_hiring_score"]), key="run_p1_score")
                model = st.text_input("Model", cfg["phase1"]["model"], key="run_p1_model")
            elif phase == "phase2":
                c1, c2, c3 = st.columns(3)
                iters = c1.number_input("Max iterations / company", 1, 10, int(cfg["phase2"]["max_iterations"]), key="run_p2_iters")
                limit = c2.number_input("Company limit (0 = all)", 0, 500, 0, key="run_p2_limit")
                temp = c3.number_input("Temperature", 0.0, 1.0, float(cfg["phase2"]["temperature"]), step=0.1, key="run_p2_temp")
                model = st.text_input("Model", cfg["phase2"]["model"], key="run_p2_model")
            else:
                st.info(
                    "Phase 3 from this app is intentionally limited to **preview** (dry-run plan) "
                    "and **test** (one email to `TEST_RECIPIENT`). Use the CLI (`phase_3/send_emails.py "
                    "--mode all`) for bulk sending."
                )

        start_col, _, hint_col = st.columns([1, 1, 3])
        with start_col:
            st.button(
                "🚀 Start run",
                type="primary",
                on_click=_start,
                args=(phase, dry_run, phase3_mode),
                disabled=bool(handle and handle.running),
            )
        with hint_col:
            if handle and handle.running:
                st.caption(f"Running now: **{handle.label}** — use the Stop button below.")

    _render_live(handle)


@st.fragment(run_every=2.0)
def _render_live(handle: RunHandle | None) -> None:
    st.divider()
    if handle is None:
        st.info("Nothing running yet. Pick a stage above and press **Start run**.")
        return

    running = handle.running
    elapsed = int(time.time() - handle.started_at)
    state = "🟢 RUNNING" if running else ("🔴 STOPPED" if handle.stop_event.is_set() else "✅ DONE")
    if handle.error:
        state = "❌ FAILED"
    st.markdown(f"### {handle.label} — {state}  ·  {elapsed}s")

    cfg = settings_mod.load()
    if handle.phase == "phase1":
        target = int(handle.overrides.get("total_cap", cfg["phase1"]["total_cap"]))
        csv_path = cfg["phase1"]["csv_path"] if not handle.dry_run else str(paths.DEMO_COMPANIES)
        current = results.row_count(csv_path)
        _progress_bar(current, target, "companies stored")
    elif handle.phase == "phase2":
        companies = results.row_count(
            str(paths.DEMO_COMPANIES) if handle.dry_run else cfg["phase2"]["companies_path"]
        )
        done = results.row_count(
            str(paths.DEMO_OUTCOMES) if handle.dry_run else cfg["phase2"]["outcomes_path"]
        )
        _progress_bar(done, companies, "companies researched")
    elif handle.phase == "phase3":
        st.progress(1.0 if not running else 0.5, text="Phase 3 streams its output into the log below.")

    stop_col, _, clear_col = st.columns([1, 3, 1])
    with stop_col:
        st.button("⏹ Stop", on_click=_stop, disabled=not running)
    with clear_col:
        if st.button("Clear log"):
            handle.log.clear()

    lines = handle.log.snapshot()
    st.code("\n".join(lines[-400:]) or "(waiting for the first log line…)", language=None)

    if handle.error:
        st.error(f"Run failed: {handle.error}")
    elif not running and handle.finished.is_set():
        st.success("Run finished — results are persisted to the CSVs and visible in **Results**.")
        if handle.phase == "phase1":
            _show_frame(results.load_csv(cfg["phase1"]["csv_path"] if not handle.dry_run else str(paths.DEMO_COMPANIES)),
                        cols=["company_name", "website", "location", "hiring_probability_score", "priority"])
        elif handle.phase == "phase2":
            _show_frame(results.load_csv(cfg["phase2"]["outcomes_path"] if not handle.dry_run else str(paths.DEMO_OUTCOMES)),
                        cols=["company_name", "status", "contacts_found", "iterations_run"])


def _progress_bar(current: int, target: int, label: str) -> None:
    target = max(target, 1)
    st.progress(min(current / target, 1.0), text=f"{label}: {current} / {target}")


def _show_frame(frame, cols: list[str]) -> None:
    if frame is None or frame.empty:
        st.caption("No data yet.")
        return
    present = [c for c in cols if c in frame.columns]
    st.dataframe(frame[present], width="stretch", hide_index=True)
