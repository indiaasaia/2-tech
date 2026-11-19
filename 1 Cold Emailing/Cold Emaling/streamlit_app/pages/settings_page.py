"""Settings page: API keys, target cities, pipeline knobs, Phase 3 .env."""
from __future__ import annotations

from typing import Any

import streamlit as st

from core import paths, settings as settings_mod


def render() -> None:
    st.title("⚙️ Settings")
    # Re-entering this page reloads the form from disk (unsaved edits are
    # drafts only and must not survive navigation).
    if st.session_state.get("_page_changed"):
        for key in ("keys_draft", "keys_ver", "cities_input", "env_text"):
            st.session_state.pop(key, None)
    cfg = settings_mod.load()

    st.subheader("API keys")
    st.caption(
        "Keys are tried in order; on any failure the next enabled key takes over automatically. "
        "Live runs need a Gemini key (starts with `AIza`)."
    )
    _keys_editor(cfg)

    st.divider()
    st.subheader("Target cities")
    _cities_editor(cfg)

    st.divider()
    st.subheader("Pipeline knobs")
    _knobs_editor(cfg)

    st.divider()
    st.subheader("Phase 3 — email sender (.env)")
    _env_editor()

    st.divider()
    st.caption(f"Stored in `{paths.SETTINGS_PATH}` (git-ignored).")


# --------------------------------------------------------------------------
# API keys
# --------------------------------------------------------------------------

def _keys_editor(cfg: dict[str, Any]) -> None:
    if "keys_draft" not in st.session_state:
        st.session_state["keys_draft"] = [dict(k) for k in cfg["api_keys"]]
        st.session_state["keys_ver"] = 0

    keys: list[dict] = st.session_state["keys_draft"]
    ver: int = st.session_state["keys_ver"]
    remove: int | None = None

    for i, key in enumerate(keys):
        c1, c2, c3, c4 = st.columns([2, 4, 1, 1])
        c1.text_input(
            "Label", key.get("label", ""), key=f"kl_{ver}_{i}", label_visibility="collapsed",
            placeholder="Label (e.g. Primary Gemini)"
        )
        c2.text_input(
            "Key value", key.get("value", ""), key=f"kv_{ver}_{i}", label_visibility="collapsed",
            type="password", placeholder="AIza… / AQ…"
        )
        c3.checkbox("On", bool(key.get("enabled", True)), key=f"ke_{ver}_{i}")
        if c4.button("🗑", key=f"kx_{ver}_{i}"):
            remove = i
        c5, c6 = st.columns([1, 1])
        c5.selectbox(
            "Provider", settings_mod.PROVIDERS,
            index=settings_mod.PROVIDERS.index(key.get("provider", "gemini") if key.get("provider") in settings_mod.PROVIDERS else "gemini"),
            key=f"kp_{ver}_{i}", label_visibility="collapsed",
        )
        c6.text_input(
            "Folder id (Yandex only)", key.get("folder_id", ""), key=f"kf_{ver}_{i}",
            label_visibility="collapsed", placeholder="Yandex folder id (required for AQ… keys)"
        )

    c1, c2, c3 = st.columns([1, 1, 3])
    if c1.button("➕ Add key"):
        _sync_keys_draft(keys, ver)
        keys.append({"label": "", "value": "", "provider": "gemini", "folder_id": "", "enabled": True})
        st.session_state["keys_ver"] += 1
        st.rerun()
    if remove is not None:
        _sync_keys_draft(keys, ver)
        keys.pop(remove)
        st.session_state["keys_ver"] += 1
        st.rerun()
    if c2.button("Save keys"):
        _sync_keys_draft(keys, ver)
        cfg["api_keys"] = keys
        settings_mod.save(cfg)
        st.session_state.pop("keys_draft", None)
        st.session_state.pop("keys_ver", None)
        st.success("API keys saved.")

    missing_folder = [
        str(k.get("label")) for k in keys
        if k.get("provider") == "yandex" and not str(k.get("folder_id") or "").strip()
    ]
    if missing_folder:
        st.warning(
            f"Yandex keys **{', '.join(missing_folder)}** need a **folder id** to authenticate "
            "(Yandex Cloud → folder → ID). Add it above or these keys will fail and be skipped."
        )


def _sync_keys_draft(keys: list[dict], ver: int) -> None:
    """Copy the current widget values back into the draft before rows change."""
    for i, key in enumerate(keys):
        provider = str(st.session_state.get(f"kp_{ver}_{i}", key.get("provider", "gemini")))
        key["label"] = str(st.session_state.get(f"kl_{ver}_{i}", key.get("label", ""))).strip() or f"Key {i + 1}"
        key["value"] = str(st.session_state.get(f"kv_{ver}_{i}", key.get("value", ""))).strip()
        key["provider"] = provider if provider in settings_mod.PROVIDERS else "gemini"
        key["folder_id"] = str(st.session_state.get(f"kf_{ver}_{i}", key.get("folder_id", ""))).strip()
        key["enabled"] = bool(st.session_state.get(f"ke_{ver}_{i}", key.get("enabled", True)))


# --------------------------------------------------------------------------
# Cities
# --------------------------------------------------------------------------

def _cities_editor(cfg: dict[str, Any]) -> None:
    if "cities_input" not in st.session_state:
        st.session_state["cities_input"] = ", ".join(settings_mod.cities(cfg))
    st.text_input("Cities (comma separated)", key="cities_input")
    if st.button("Save cities"):
        cities = [c.strip() for c in str(st.session_state["cities_input"]).split(",") if c.strip()]
        cfg["cities"] = cities
        settings_mod.save(cfg)
        st.success(f"Saved {len(cities)} city/cities. Next Phase 1 run will target: {', '.join(cities)}.")
    st.caption("Filled into the Phase 1 prompt's `{{CITIES}}` placeholder.")


# --------------------------------------------------------------------------
# Pipeline knobs
# --------------------------------------------------------------------------

def _knobs_editor(cfg: dict[str, Any]) -> None:
    with st.expander("Phase 1 — startup discovery", expanded=False):
        p1 = cfg["phase1"]
        c1, c2, c3 = st.columns(3)
        c1.text_input("Model", p1["model"], key="p1_model")
        c2.number_input("Batch size", 1, 20, int(p1["batch_size"]), key="p1_batch")
        c3.number_input("Total cap", 1, 1000, int(p1["total_cap"]), key="p1_cap")
        c4, c5, c6 = st.columns(3)
        c4.number_input("Min hiring score", 0, 100, int(p1["min_hiring_score"]), key="p1_score")
        c5.number_input("Max runs", 1, 200, int(p1["max_runs"]), key="p1_runs")
        c6.number_input("Temperature", 0.0, 1.0, float(p1["temperature"]), step=0.1, key="p1_temp")
        st.text_input("Companies CSV (output)", p1["csv_path"], key="p1_csv")
        st.text_input("Prompt file", p1["prompt_path"], key="p1_prompt")

    with st.expander("Phase 2 — contact discovery", expanded=False):
        p2 = cfg["phase2"]
        c1, c2, c3 = st.columns(3)
        c1.text_input("Model", p2["model"], key="p2_model")
        c2.text_input(
            "Fallback models (comma separated)", ", ".join(p2["fallback_models"]), key="p2_fb"
        )
        c3.number_input("Max iterations / company", 1, 10, int(p2["max_iterations"]), key="p2_iters")
        c4, c5 = st.columns(2)
        c4.number_input("Temperature", 0.0, 1.0, float(p2["temperature"]), step=0.1, key="p2_temp")
        limit_default = int(p2["limit"]) if p2.get("limit") else 0
        c5.number_input("Company limit (0 = all)", 0, 1000, limit_default, key="p2_limit")
        st.text_input("Companies CSV (input)", p2["companies_path"], key="p2_companies")
        c6, c7 = st.columns(2)
        c6.text_input("Contacts CSV (output)", p2["csv_path"], key="p2_csv")
        c7.text_input("Outcomes CSV", p2["outcomes_path"], key="p2_outcomes")
        st.text_input("Prompt file", p2["prompt_path"], key="p2_prompt")
        st.text_input("Repeat prompt file", p2["repeat_prompt_path"], key="p2_repeat")

    if st.button("Save pipeline knobs"):
        cfg["phase1"] = {
            "model": st.session_state["p1_model"],
            "batch_size": int(st.session_state["p1_batch"]),
            "total_cap": int(st.session_state["p1_cap"]),
            "min_hiring_score": int(st.session_state["p1_score"]),
            "max_runs": int(st.session_state["p1_runs"]),
            "temperature": float(st.session_state["p1_temp"]),
            "csv_path": st.session_state["p1_csv"],
            "prompt_path": st.session_state["p1_prompt"],
        }
        fb = [m.strip() for m in st.session_state["p2_fb"].split(",") if m.strip()]
        limit = int(st.session_state["p2_limit"]) or None
        cfg["phase2"] = {
            "model": st.session_state["p2_model"],
            "fallback_models": fb,
            "max_iterations": int(st.session_state["p2_iters"]),
            "temperature": float(st.session_state["p2_temp"]),
            "limit": limit,
            "companies_path": st.session_state["p2_companies"],
            "csv_path": st.session_state["p2_csv"],
            "outcomes_path": st.session_state["p2_outcomes"],
            "prompt_path": st.session_state["p2_prompt"],
            "repeat_prompt_path": st.session_state["p2_repeat"],
        }
        settings_mod.save(cfg)
        st.success("Pipeline knobs saved.")


# --------------------------------------------------------------------------
# Phase 3 .env
# --------------------------------------------------------------------------

def _env_editor() -> None:
    if "env_text" not in st.session_state:
        st.session_state["env_text"] = _read_env()
    st.text_area(
        ".env content (Gmail app password, sender address, personal facts…)",
        height=420,
        key="env_text",
    )
    c1, c2 = st.columns([1, 3])
    if c1.button("Save .env"):
        paths.PHASE3_ENV.write_text(st.session_state["env_text"], encoding="utf-8")
        st.success(f"Saved to {paths.PHASE3_ENV}.")
    with c2:
        st.caption(
            "Used by `phase_3/send_emails.py`. The Gmail App Password lives here — keep this "
            "machine private. Reload by revisiting this page."
        )


def _read_env() -> str:
    if paths.PHASE3_ENV.exists():
        return paths.PHASE3_ENV.read_text(encoding="utf-8")
    if paths.PHASE3_ENV_EXAMPLE.exists():
        return paths.PHASE3_ENV_EXAMPLE.read_text(encoding="utf-8")
    return "# No .env found yet."
