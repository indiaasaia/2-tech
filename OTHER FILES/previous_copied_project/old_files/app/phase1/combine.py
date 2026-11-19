"""Combine source frames into the stable Phase 1 CSV schema."""
from __future__ import annotations

import pandas as pd

from app.core import config


def normalize(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in config.COMMON_COLUMNS:
        if column not in output.columns:
            output[column] = ""
    output = output[config.COMMON_COLUMNS]
    for column in ("job_url", "title", "company", "location", "source"):
        output[column] = output[column].fillna("").astype(str).str.strip()
    return output


def combine(*frames: pd.DataFrame) -> pd.DataFrame:
    nonempty = [normalize(frame) for frame in frames if frame is not None and not frame.empty]
    if not nonempty:
        return pd.DataFrame(columns=config.COMMON_COLUMNS)
    output = pd.concat(nonempty, ignore_index=True)
    output["_priority"] = output["source"].map({"stepstone": 0, "workingstudentjobs.de": 1}).fillna(2)
    output = output.sort_values("_priority", kind="stable").drop(columns="_priority")
    output = output.drop_duplicates(subset=["job_url"], keep="first")
    output = output[output["job_url"].ne("")].reset_index(drop=True)
    return output


def save(frame: pd.DataFrame) -> None:
    normalized = normalize(frame)
    normalized.to_csv(config.COMBINED_CSV, index=False, encoding="utf-8")
    # Keep a descriptive alias for compatibility with the Phase 1 terminology.
    normalized.to_csv(config.PHASE1_COMBINED_CSV, index=False, encoding="utf-8")
    print(f"[COMBINE] saved {len(normalized)} jobs -> {config.COMBINED_CSV}")
