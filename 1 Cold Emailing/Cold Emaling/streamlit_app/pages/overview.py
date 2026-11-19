"""Overview dashboard: pipeline status at a glance."""
from __future__ import annotations

import streamlit as st

from core import paths, results, settings as settings_mod


def render() -> None:
    st.title("📊 Overview")
    st.caption("Cold-outreach pipeline: discover companies → find contacts → send emails.")

    cfg = settings_mod.load()

    # --- Key health banner ---
    keys = settings_mod.enabled_keys(cfg)
    missing_folder = [k for k in keys if not settings_mod.provider_ready(k)]
    if not keys:
        st.error(
            "No enabled API keys. Go to **Settings → API keys** and add a Gemini key "
            "(starts with `AIza`) or a Yandex key (`AQ…` + folder id). Live runs need one."
        )
    elif missing_folder:
        st.warning(
            f"⚠️ {len(missing_folder)} enabled Yandex key(s) are missing a **folder id** "
            f"({', '.join(str(k.get('label')) for k in missing_folder)}) — they will be skipped "
            "until you add it in Settings → API keys."
        )
    else:
        providers = sorted({str(k.get("provider", "gemini")) for k in keys})
        st.success(f"{len(keys)} enabled API key(s) — providers: {', '.join(providers)}.")

    # --- Pipeline map ---
    col_a, arrow1, col_b, arrow2, col_c = st.columns([3, 1, 3, 1, 3])
    cities = settings_mod.cities(cfg)
    with col_a:
        st.markdown("#### 1️⃣ Startup discovery")
        st.write("AI finds startups in the target cities, filtered by hiring probability.")
        st.metric("Companies stored", results.summarize(cfg)["companies"])
        st.write("**Target cities:** " + (", ".join(cities) if cities else "—"))
    with arrow1:
        st.markdown("### ➜")
    with col_b:
        st.markdown("#### 2️⃣ Contact discovery")
        st.write("For each company: research publicly available professional emails.")
        summary = results.summarize(cfg)
        st.metric("Companies researched", summary["companies_done"])
        st.metric("Contacts found", summary["contacts"])
    with arrow2:
        st.markdown("### ➜")
    with col_c:
        st.markdown("#### 3️⃣ Email sender")
        st.write("Personalised outreach via Gmail SMTP (preview/test from this app).")
        st.metric("Emails sent", summary["sent"])

    # --- Outcomes breakdown ---
    if summary["outcomes"]:
        st.markdown("### Phase 2 outcomes")
        st.write(" | ".join(f"**{k}**: {v}" for k, v in summary["outcomes"].items()))

    # --- Quick start ---
    with st.expander("How to run your first campaign", expanded=False):
        st.markdown(
            f"""
1. **Settings → API keys** — the two `AQ.` keys supplied earlier are Yandex Cloud keys:
   set provider **yandex** and add their **folder id**. For Gemini, add an `AIza…` key.
2. **Settings → Cities** — target cities are `{", ".join(cities)}`.
3. **Prompts** — review/edit the discovery prompts; the Phase 1 prompt uses the
   `{{{{CITIES}}}}` placeholder which is filled from your city list automatically.
4. **Run** — start Phase 1, watch the live log; then Phase 2. Use **DRY RUN** first
   to test without spending API quota.
5. **Results** — inspect the CSVs in real time; Phase 3's history is there too.
            """
        )

    st.caption(
        f"Settings file: `{paths.SETTINGS_PATH}` · "
        f"Results CSVs live under `phase_1/data` and `phase_2/data`."
    )
