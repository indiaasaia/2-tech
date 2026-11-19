"""Live Dashboard: Real-time pipeline monitoring, step tracking, live results & historical records."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from core import paths, results, settings as settings_mod
from core.runners import RunHandle, make_handle

# 8 canonical steps of the campaign pipeline
PIPELINE_STEPS = [
    {"num": 1, "title": "Send Queued", "desc": "Send already-queued companies", "phase": "Phase 3"},
    {"num": 2, "title": "Phase 2 (Pending)", "desc": "Contact discovery for pending", "phase": "Phase 2"},
    {"num": 3, "title": "Phase 1 (Deficit)", "desc": "Startup discovery for deficit", "phase": "Phase 1"},
    {"num": 4, "title": "Phase 2 (New)", "desc": "Contact discovery for new", "phase": "Phase 2"},
    {"num": 5, "title": "Build & MX", "desc": "Rebuild list & verify MX records", "phase": "Phase 3"},
    {"num": 6, "title": "Gemini Hooks", "desc": "Generate technical hooks", "phase": "Phase 3"},
    {"num": 7, "title": "Audit Gate", "desc": "Verify 100% personalization pass", "phase": "Phase 3"},
    {"num": 8, "title": "Send New", "desc": "Dispatch newly queued emails", "phase": "Phase 3"},
]


def _load_live_status() -> dict:
    """Read phase_3/data/live_status.json or fallback to defaults."""
    status_file = paths.PHASE3_LIVE_STATUS
    if status_file.exists():
        try:
            with open(status_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # Fallback default when no file exists yet
    return {
        "step": 0,
        "total_steps": 8,
        "step_name": "Pipeline Idle",
        "status": "idle",
        "detail": "Campaign is waiting to be launched.",
        "round_id": "-",
        "current_batch": [],
        "step_result": "",
        "updated_at": datetime.now().isoformat(),
        "metrics": {
            "today_sent": results.row_count(paths.PHASE3_HISTORY),
            "max_per_day": 120,
            "agencies_today": 0,
            "max_agencies_per_day": 20,
            "researched_count": results.row_count(paths.PHASE1_CSV),
            "contacts_count": results.row_count(paths.PHASE2_RESULTS),
            "queued_count": results.row_count(paths.PHASE3_QUEUED_CSV),
            "hooks_count": results.row_count(paths.PHASE3_HOOKS_CSV),
        },
    }


def _load_recent_logs(max_lines: int = 150) -> list[str]:
    """Read the latest log lines from live_process.log or handle buffer."""
    handle: RunHandle | None = st.session_state.get("campaign_handle")
    if handle and handle.running:
        snap = handle.log.snapshot()
        if snap:
            return snap[-max_lines:]

    log_file = paths.PHASE3_LIVE_LOG
    if log_file.exists():
        try:
            with open(log_file, encoding="utf-8", errors="replace") as f:
                lines = [line.rstrip() for line in f]
                return lines[-max_lines:]
        except Exception:
            pass
    return ["(No active process log yet. Launch campaign to see live logs)"]


def _start_campaign(loop: bool = True, dry_run: bool = False, batch_size: int = 10) -> None:
    handle = make_handle(
        "campaign",
        dry_run=dry_run,
        overrides={"loop": loop, "batch": batch_size},
    )
    st.session_state["campaign_handle"] = handle
    st.toast("Campaign launched! Real-time progress is now live.")
    st.rerun()


def _start_send_leftovers() -> None:
    handle = make_handle(
        "phase3",
        dry_run=False,
        phase3_mode="all",
    )
    st.session_state["campaign_handle"] = handle
    st.toast("Dispatching leftover emails! Live progress is streaming.")
    st.rerun()


def _stop_campaign() -> None:
    handle: RunHandle | None = st.session_state.get("campaign_handle")
    if handle and handle.running:
        handle.request_stop()
        st.toast("Stop signal delivered to campaign process.")


def render() -> None:
    st.markdown(
        """
        <style>
        .metric-card {
            background-color: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 8px;
            padding: 12px 16px;
            text-align: center;
        }
        .status-badge-running {
            background-color: #d4edda;
            color: #155724;
            padding: 4px 12px;
            border-radius: 12px;
            font-weight: bold;
            display: inline-block;
        }
        .status-badge-idle {
            background-color: #e2e3e5;
            color: #383d41;
            padding: 4px 12px;
            border-radius: 12px;
            font-weight: bold;
            display: inline-block;
        }
        .status-badge-sleeping {
            background-color: #fff3cd;
            color: #856404;
            padding: 4px 12px;
            border-radius: 12px;
            font-weight: bold;
            display: inline-block;
        }
        .status-badge-cap {
            background-color: #f8d7da;
            color: #721c24;
            padding: 4px 12px;
            border-radius: 12px;
            font-weight: bold;
            display: inline-block;
        }
        .step-box-completed {
            background-color: #e8f5e9;
            border: 2px solid #4caf50;
            border-radius: 6px;
            padding: 8px 4px;
            text-align: center;
            font-size: 11px;
            min-height: 80px;
        }
        .step-box-active {
            background-color: #e3f2fd;
            border: 2px solid #1976d2;
            border-radius: 6px;
            padding: 8px 4px;
            text-align: center;
            font-size: 11px;
            box-shadow: 0 0 10px rgba(25, 118, 210, 0.5);
            font-weight: bold;
            min-height: 80px;
        }
        .step-box-pending {
            background-color: #f5f5f5;
            border: 1px dashed #bdbdbd;
            border-radius: 6px;
            padding: 8px 4px;
            text-align: center;
            font-size: 11px;
            color: #757575;
            min-height: 80px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Top title and controls
    header_col, ctrl_col = st.columns([3, 2])
    with header_col:
        st.title("🚀 Real-Time Outreach Dashboard")
        st.caption("Live German Software Startup Campaign — Process Stepper, Current Results & Historical Archive")
    with ctrl_col:
        handle: RunHandle | None = st.session_state.get("campaign_handle")
        is_running = bool(handle and handle.running)
        c1, c2, c3, c4 = st.columns([1.2, 1.2, 0.9, 0.7])
        with c1:
            st.button("📬 Send Leftovers", type="primary", disabled=is_running, on_click=_start_send_leftovers, help="Send emails to all discovered contacts without discovering new companies")
        with c2:
            st.button("🚀 Full Loop", disabled=is_running, on_click=_start_campaign, args=(True, False), help="Run automated 8-step loop including new discovery")
        with c3:
            st.button("🧪 Dry-Run", disabled=is_running, on_click=_start_campaign, args=(False, True))
        with c4:
            st.button("⏹ Stop", disabled=not is_running, on_click=_stop_campaign)

    # Render auto-refreshing live block
    _render_live_section()

    # Historical records at the end of the page
    _render_historical_section()


@st.fragment(run_every=2.0)
def _render_live_section() -> None:
    live = _load_live_status()
    current_step = live.get("step", 0)
    status_str = str(live.get("status", "idle")).lower()
    step_name = live.get("step_name", "Idle")
    detail = live.get("detail", "")
    metrics = live.get("metrics", {})

    # =========================================================================
    # SECTION 1: STARTING WITH WHAT STEP IT IS DOING
    # =========================================================================
    st.markdown("---")
    st.markdown("### 1️⃣ Current Process & Pipeline Stepper")

    badge_html = {
        "running": f'<span class="status-badge-running">🟢 ACTIVE & RUNNING</span>',
        "sleeping": f'<span class="status-badge-sleeping">🟡 COOLDOWN / SLEEPING</span>',
        "cap_reached": f'<span class="status-badge-cap">🔒 DAILY CAP REACHED</span>',
        "completed": f'<span class="status-badge-running">✅ ROUND COMPLETED</span>',
    }.get(status_str, '<span class="status-badge-idle">⚪ IDLE</span>')

    status_cols = st.columns([2, 3, 2])
    with status_cols[0]:
        st.markdown(f"**Process State:** {badge_html}", unsafe_allow_html=True)
    with status_cols[1]:
        st.markdown(f"**Current Action:** `{step_name}`")
    with status_cols[2]:
        round_id = live.get("round_id") or "-"
        st.caption(f"Round ID: `{round_id}` | Updated: `{live.get('updated_at', '')[:19]}`")

    if detail:
        st.info(f"ℹ️ **Current Step Activity:** {detail}")

    # Visual 8-step pipeline stepper
    step_cols = st.columns(8)
    for i, step_info in enumerate(PIPELINE_STEPS, start=1):
        with step_cols[i - 1]:
            if current_step > i or (current_step == 8 and status_str == "completed"):
                box_class = "step-box-completed"
                badge = "✅ DONE"
            elif current_step == i and status_str == "running":
                box_class = "step-box-active"
                badge = "⚡ ACTIVE"
            else:
                box_class = "step-box-pending"
                badge = "⏳ PENDING"

            st.markdown(
                f"""
                <div class="{box_class}">
                    <div style="font-weight:bold; margin-bottom:2px;">Step {i}</div>
                    <div style="font-size:10px; color:#555;">{step_info['title']}</div>
                    <div style="margin-top:6px; font-size:9px;">{badge}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    progress_val = min(1.0, max(0.0, current_step / 8.0))
    st.progress(progress_val, text=f"Pipeline Progress: Step {current_step} of 8 ({int(progress_val * 100)}%)")

    # =========================================================================
    # SECTION 2: IN THE MIDDLE, CURRENT STEP RESULTS AND LIVE STATUS OF PROCESS
    # =========================================================================
    st.markdown("---")
    st.markdown("### 2️⃣ Current Step Results & Live Process KPIs")

    # 6 Real-time KPI Metric cards
    kpi_cols = st.columns(6)
    today_sent = metrics.get("today_sent", 0)
    max_day = metrics.get("max_per_day", 120)
    agencies_today = metrics.get("agencies_today", 0)
    max_agencies = metrics.get("max_agencies_per_day", 20)

    with kpi_cols[0]:
        st.metric("📧 Emails Sent Today", f"{today_sent} / {max_day}", delta=f"{int(today_sent/max(1, max_day)*100)}% cap")
    with kpi_cols[1]:
        st.metric("🏢 Companies Today", f"{agencies_today} / {max_agencies}", delta=f"{agencies_today} processed")
    with kpi_cols[2]:
        st.metric("🎯 Tech Startups", metrics.get("researched_count", 0), help="Total discovered German software startups")
    with kpi_cols[3]:
        st.metric("📬 Decision-Makers", metrics.get("contacts_count", 0), help="CTOs, VP Eng, Tech Leads with contacts")
    with kpi_cols[4]:
        st.metric("🛡️ Deliverable Queue", metrics.get("queued_count", 0), help="Verified clean MX recipients ready to send")
    with kpi_cols[5]:
        st.metric("✨ AI Hooks Ready", metrics.get("hooks_count", 0), help="2-sentence personalized hooks crafted")

    # Live step results view
    res_tab1, res_tab2, res_tab3, res_tab4 = st.tabs([
        "📋 Current Step Data",
        "🎯 Verified Queue (contacts_to_send.csv)",
        "✨ AI Product Hooks (email_hooks.csv)",
        "💻 Live Console Log Stream",
    ])

    with res_tab1:
        current_batch = live.get("current_batch") or []
        step_result_msg = live.get("step_result")
        if step_result_msg:
            st.success(f"**Step Output:** {step_result_msg}")

        if current_batch:
            st.write(f"**Active Batch Startups ({len(current_batch)}):** " + ", ".join(f"`{c}`" for c in current_batch))

        # Dynamically load relevant step dataset
        if current_step in (2, 4):
            # Phase 2 contacts
            p2_df = results.load_csv(paths.PHASE2_RESULTS)
            if p2_df is not None and not p2_df.empty:
                st.caption(f"Latest Contact Discovery Results ({len(p2_df)} total contacts found)")
                st.dataframe(p2_df.tail(15), width="stretch", hide_index=True)
            else:
                st.caption("No contacts discovered yet.")
        elif current_step == 3:
            # Phase 1 companies
            p1_df = results.load_csv(paths.PHASE1_CSV)
            if p1_df is not None and not p1_df.empty:
                cols = [c for c in ["company_name", "website", "location", "hiring_probability_score", "technical_focus"] if c in p1_df.columns]
                st.caption(f"Discovered German Software Startups ({len(p1_df)} total companies)")
                st.dataframe(p1_df[cols].tail(15), width="stretch", hide_index=True)
            else:
                st.caption("No companies discovered yet.")
        else:
            # Phase 3 Queue preview
            q_df = results.load_csv(paths.PHASE3_QUEUED_CSV)
            if q_df is not None and not q_df.empty:
                cols = [c for c in ["company_name", "email", "contact_name", "technical_focus"] if c in q_df.columns]
                st.caption(f"Active Dispatch Queue ({len(q_df)} recipients ready)")
                st.dataframe(q_df[cols].head(15), width="stretch", hide_index=True)
            else:
                st.caption("Queue is empty.")

    with res_tab2:
        q_df = results.load_csv(paths.PHASE3_QUEUED_CSV)
        if q_df is not None and not q_df.empty:
            st.caption(f"Showing all **{len(q_df)}** recipients in `contacts_to_send.csv` with MX verification and blacklists applied.")
            st.dataframe(q_df, width="stretch", hide_index=True)
        else:
            st.info("Queue is empty. Run Step 5 (Build list) or full campaign to generate contacts.")

    with res_tab3:
        hooks_df = results.load_csv(paths.PHASE3_HOOKS_CSV)
        if hooks_df is not None and not hooks_df.empty:
            st.caption(f"Showing **{len(hooks_df)}** personalized AI hooks in `data/email_hooks.csv`.")
            st.dataframe(hooks_df, width="stretch", hide_index=True)
        else:
            st.info("No hooks generated yet. They are created automatically in Step 6.")

    with res_tab4:
        log_lines = _load_recent_logs(max_lines=150)
        st.code("\n".join(log_lines), language="bash")
        st.caption("🟢 Auto-refreshing every 2 seconds. Shows real-time stdout from the campaign engine.")


def _render_historical_section() -> None:
    # =========================================================================
    # SECTION 3: AT THE END OF THE PAGES, HISTORICAL RECORDS
    # =========================================================================
    st.markdown("---")
    st.markdown("### 3️⃣ Historical Outreach Records & Archive")
    st.caption("Complete permanent history of dispatched emails, company applications, and campaign rounds.")

    history_df = results.load_csv(paths.PHASE3_HISTORY)
    tracking_df = results.load_csv(paths.PHASE3_TRACKING_CSV)
    campaign_log_df = results.load_csv(paths.PHASE3_CAMPAIGN_LOG)

    # Analytics banner
    total_sent = 0 if history_df is None else len(history_df)
    unique_companies = 0 if history_df is None or "company" not in history_df.columns else history_df["company"].nunique()
    total_tracked = 0 if tracking_df is None else len(tracking_df)
    total_rounds = 0 if campaign_log_df is None or "round" not in campaign_log_df.columns else campaign_log_df["round"].nunique()

    h_cols = st.columns(4)
    with h_cols[0]:
        st.metric("📬 Total Emails Sent (All-Time)", f"{total_sent:,}")
    with h_cols[1]:
        st.metric("🏢 Unique Companies Contacted", f"{unique_companies:,}")
    with h_cols[2]:
        st.metric("📋 Company Track Rows", f"{total_tracked:,}")
    with h_cols[3]:
        st.metric("🔄 Total Rounds Completed", f"{total_rounds:,}")

    # Search & Filter
    f_col1, f_col2, f_col3 = st.columns([3, 1, 1])
    with f_col1:
        search_query = st.text_input("🔍 Search Historical Records (Company, Email, Subject, or Round)", key="hist_search").strip().lower()
    with f_col2:
        status_filter = st.selectbox("Status Filter", ["All", "sent", "failed"], key="hist_status")
    with f_col3:
        date_filter = st.selectbox("Date Scope", ["All Time", "Today", "Last 7 Days"], key="hist_date")

    tab_sent, tab_tracking, tab_rounds = st.tabs([
        f"📧 Dispatched Emails ({total_sent})",
        f"🏢 Company Tracking ({total_tracked})",
        f"📜 Campaign Rounds Log ({total_rounds})",
    ])

    with tab_sent:
        if history_df is not None and not history_df.empty:
            filtered = history_df.copy()
            if search_query:
                mask = (
                    filtered["company"].astype(str).str.lower().str.contains(search_query, na=False)
                    | filtered["to"].astype(str).str.lower().str.contains(search_query, na=False)
                    | filtered["subject"].astype(str).str.lower().str.contains(search_query, na=False)
                )
                filtered = filtered[mask]

            if status_filter != "All" and "status" in filtered.columns:
                filtered = filtered[filtered["status"].str.lower() == status_filter]

            if date_filter == "Today" and "timestamp" in filtered.columns:
                today_str = datetime.now().strftime("%Y-%m-%d")
                filtered = filtered[filtered["timestamp"].astype(str).str.startswith(today_str)]
            elif date_filter == "Last 7 Days" and "timestamp" in filtered.columns:
                cutoff = (datetime.now() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
                filtered = filtered[filtered["timestamp"].astype(str) >= cutoff]

            st.caption(f"Displaying **{len(filtered)}** of **{len(history_df)}** records.")

            display_cols = [c for c in ["timestamp", "company", "to", "subject", "status", "error"] if c in filtered.columns]
            st.dataframe(filtered[display_cols].sort_values(by="timestamp", ascending=False), width="stretch", hide_index=True)

            with st.expander("🔍 Inspect Email Body Content (Select an email)", expanded=False):
                options = {
                    f"#{idx + 1} | {str(r.get('timestamp', ''))[:19]} | {r.get('company', '')} -> {r.get('to', '')}": r.get("body", "")
                    for idx, r in filtered.head(50).reset_index(drop=True).iterrows()
                }
                if options:
                    selected_key = st.selectbox("Select email to view body preview:", list(options.keys()))
                    st.text_area("Email Content (as dispatched)", options[selected_key], height=240, disabled=True)

            st.download_button(
                "⬇ Download Sent History (CSV)",
                data=history_df.to_csv(index=False),
                file_name="sent_history_export.csv",
                mime="text/csv",
                key="dl_sent_history",
            )
        else:
            st.info("No sent history records found in `sent_history.csv`.")

    with tab_tracking:
        if tracking_df is not None and not tracking_df.empty:
            track_filtered = tracking_df.copy()
            if search_query:
                mask = (
                    track_filtered["company"].astype(str).str.lower().str.contains(search_query, na=False)
                    | track_filtered["contact_emails"].astype(str).str.lower().str.contains(search_query, na=False)
                    | track_filtered["round"].astype(str).str.lower().str.contains(search_query, na=False)
                )
                track_filtered = track_filtered[mask]

            st.caption(f"Displaying **{len(track_filtered)}** companies tracked in `data/tracking.csv`.")
            st.dataframe(track_filtered.sort_values(by="date_applied", ascending=False), width="stretch", hide_index=True)

            st.download_button(
                "⬇ Download Tracking Archive (CSV)",
                data=tracking_df.to_csv(index=False),
                file_name="tracking_export.csv",
                mime="text/csv",
                key="dl_tracking",
            )
        else:
            st.info("No company tracking records found in `data/tracking.csv`.")

    with tab_rounds:
        if campaign_log_df is not None and not campaign_log_df.empty:
            rounds_filtered = campaign_log_df.copy()
            if search_query:
                mask = (
                    rounds_filtered["round"].astype(str).str.lower().str.contains(search_query, na=False)
                    | rounds_filtered["action"].astype(str).str.lower().str.contains(search_query, na=False)
                    | rounds_filtered["detail"].astype(str).str.lower().str.contains(search_query, na=False)
                )
                rounds_filtered = rounds_filtered[mask]

            st.caption(f"Displaying **{len(rounds_filtered)}** round actions in `data/campaign_log.csv`.")
            st.dataframe(rounds_filtered.sort_values(by="timestamp", ascending=False), width="stretch", hide_index=True)

            st.download_button(
                "⬇ Download Campaign Logs (CSV)",
                data=campaign_log_df.to_csv(index=False),
                file_name="campaign_log_export.csv",
                mime="text/csv",
                key="dl_campaign_log",
            )
        else:
            st.info("No campaign logs found in `data/campaign_log.csv`.")
