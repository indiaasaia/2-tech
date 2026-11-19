"""Profile-relevance pass on top of step 2 (2026-09-27..30 window).

Keeps a job only if ALL of:
1. Role type: title says Working Student / Werkstudent / Intern / Internship /
   Praktikum (thesis-only titles are dropped).
2. Language: strict English — stopword ratio from 2_filter_jobs's sets, EN ratio
   >= 0.6 when signal exists, plus explicit drop of German/Dutch/... -speaking
   requirements (german-speaking, verhandlungssicher, muttersprachler, ...).
3. Relevance to an MSc-AI candidate: AI/ML/data/software/automation/robotics/
   hardware tech token in the TITLE; a negative business token (marketing, hr,
   sales, legal, finance...) cancels the job unless a strong AI/tech token is
   also present. Titles with no tech token can be rescued only by a dense
   AI/tech description signal (>= 6 specific hits).
Plus dedupe on normalized (title, company) preferring the stepstone row.

Writes output/profile_selected_jobs_2026-09-27_to_09-30.csv/.md and prints
per-gate drop samples so every cut is auditable.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
SRC = OUT / "2_filted_jobs.csv"
TAG = "2026-09-27_to_09-30"
CSV_DST = OUT / f"profile_selected_jobs_{TAG}.csv"
MD_DST = OUT / f"profile_selected_jobs_{TAG}.md"

TEXT_COLS = ("title", "job_description", "requirements", "your_tasks",
             "applicant_profile", "snippet")

ROLE_TYPE = re.compile(
    r"(?:working[\s-]?student|werkstudent|\binternship\b|\bintern\b|praktikum|praktikant)", re.I)

STRONG_TECH = [
    r"\bai\b", r"artificial intelligence", r"machine learning", r"\bml\b",
    r"deep learning", r"\bllms?\b", r"gen[- ]?ai", r"generative", r"\bnlp\b",
    r"computer vision", r"\bdata\b", r"\bsoftware\b", r"developer", r"robotic",
    r"automation|automated", r"agentic",
]
MORE_TECH = [
    r"full[- ]?stack", r"backend", r"front[- ]?end", r"devops", r"mlops",
    r"\bcloud\b", r"\bandroid\b", r"\bpython\b", r"\bjava\b", r"\bc\+\+",
    r"\brust\b", r"angular", r"next\.?js", r"embedded", r"electronics",
    r"semiconductor", r"quantum", r"cyber ?security", r"\bsecurity\b",
    r"\bspace\b", r"orbital", r"analytics", r"autonomous", r"\bappsec\b",
    r"\btest automation\b", r"\bin ?car\b",
]
NEGATIVE = [
    r"marketing", r"\bsales\b", r"\bhr\b|human resources|hris",
    r"communication", r"\blegal\b", r"\bevent\b", r"sustainability",
    r"procurement", r"financ|\bbanking\b|\bm&a\b", r"accounting",
    r"supply chain", r"logistics", r"recruiting", r"\btalent\b",
    r"\bpeople\b|culture", r"community", r"\bbrand\b", r"\bux\b|\bdesign\b",
    r"business development", r"office management|workspace|executive support",
    r"\bteacher\b|school|admission", r"localization|translation", r"\bcontent\b",
    r"\bgrowth\b", r"\boutreach\b",
]
# Dense description signal used ONLY to rescue neutral titles.
DESC_SIGNAL = re.compile(
    r"machine learning|artificial intelligence|deep learning|\bllms?\b|gen[- ]?ai"
    r"|computer vision|\bnlp\b|python|pytorch|tensorflow|data science|data analytics"
    r"|large language|robotics|automation|autonomous", re.I)
LANG_MARKERS = re.compile(
    r"german[- ]speaking|native german|fluent german|muttersprachler"
    r"|verhandlungssicher|dutch[- ]speaking|spanish[- ]speaking|french[- ]speaking"
    r"|\(german\)", re.I)


def _load_step2_helpers():
    """Reuse the stopword sets from program_files/2_filter_jobs.py."""
    spec = importlib.util.spec_from_file_location("step2filter", ROOT / "2_filter_jobs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _has(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def strict_english(text: str, step2) -> bool:
    tokens = re.findall(r"[a-zäöüß]+", text.lower())
    en = sum(1 for t in tokens if t in step2._EN_STOPWORDS)
    de = sum(1 for t in tokens if t in step2._DE_STOPWORDS)
    if en + de == 0:
        return step2.is_english(text)  # no signal -> keep as before
    return en >= de and (en / (en + de)) >= 0.6


def norm_title(value: object) -> str:
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", str(value or "").lower())
    t = re.sub(r"[^a-z0-9+ ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def norm_company(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def sort_hours(value: object) -> float:
    text = str(value or "")
    m = re.search(r"(\d+)\s*(minute|hour|day|week)", text.lower())
    if m:
        mult = {"minute": 1 / 60, "hour": 1, "day": 24, "week": 168}[m.group(2)]
        return float(m.group(1)) * mult
    ts = pd.to_datetime(text, errors="coerce", utc=True)
    if pd.notna(ts):
        return (pd.Timestamp.now(tz="UTC") - ts).total_seconds() / 3600
    return 1e9


def posted_display(value: object) -> str:
    text = str(value or "")
    if "T" in text and text.endswith("Z"):
        ts = pd.to_datetime(text, utc=True).tz_convert("Europe/Berlin")
        return ts.strftime("%b %d %H:%M")
    return text


def main() -> None:
    step2 = _load_step2_helpers()
    df = pd.read_csv(SRC)
    n0 = len(df)
    print(f"[PROFILE] input: {n0} jobs from {SRC.name}")

    def row_text(row) -> str:
        return " ".join(str(row.get(c) or "") for c in TEXT_COLS)

    # 1. role type
    role_mask = df["title"].astype(str).str.contains(ROLE_TYPE)
    dropped_role = df.loc[~role_mask, "title"].astype(str).head(6).tolist()
    df = df[role_mask].reset_index(drop=True)
    print(f"[PROFILE] role type: kept {len(df)}/{n0}; sample dropped: {dropped_role}")

    # 2. strict English (+ explicit language markers)
    lang_mask = df.apply(lambda r: strict_english(row_text(r), step2), axis=1) & \
        ~df["title"].astype(str).str.contains(LANG_MARKERS)
    dropped_lang = df.loc[~lang_mask, "title"].astype(str).head(6).tolist()
    before_lang = len(df)
    df = df[lang_mask].reset_index(drop=True)
    print(f"[PROFILE] strict English: kept {len(df)}/{before_lang}; sample dropped: {dropped_lang}")

    # 3. profile relevance
    def relevant(row) -> bool:
        title = str(row.get("title") or "")
        if _has(STRONG_TECH, title):
            return True
        if _has(MORE_TECH, title):
            return not _has(NEGATIVE, title)
        if _has(NEGATIVE, title):
            return False
        return len(DESC_SIGNAL.findall(row_text(row))) >= 6

    rel_mask = df.apply(relevant, axis=1)
    dropped_rel = df.loc[~rel_mask, "title"].astype(str).head(8).tolist()
    df = df[rel_mask].reset_index(drop=True)
    print(f"[PROFILE] relevance: kept {len(df)}; sample dropped: {dropped_rel}")

    # 4. dedupe on (normalized title, normalized company), prefer stepstone rows
    df["_nt"] = df["title"].map(norm_title)
    df["_nc"] = df["company"].map(norm_company)
    df["_pref"] = (df["source"] == "stepstone").astype(int)
    df["_h"] = df["posted_time"].map(sort_hours)
    df = df.sort_values(["_pref", "_h"]).drop_duplicates(subset=["_nt", "_nc"], keep="first")
    df = df.sort_values("_h").reset_index(drop=True)
    print(f"[PROFILE] dedupe: kept {len(df)} unique jobs")

    df["posted_display"] = df["posted_time"].map(posted_display)
    out_cols = ["source", "title", "company", "location", "posted_display", "job_url"]
    sel = df[out_cols].rename(columns={"posted_display": "posted"})
    sel.to_csv(CSV_DST, index=False, encoding="utf-8-sig")
    df.drop(columns=["_nt", "_nc", "_pref", "_h"]).to_csv(
        OUT / "2_filted_jobs.csv", index=False, encoding="utf-8")  # step-4 input = selected set

    src_short = sel["source"].map(lambda s: "Stepstone" if s == "stepstone" else "WSJ.de")
    md = ["# Selected jobs — Working Student / Intern roles, English, AI/tech-relevant",
          f"# Window: 2026-09-27 → 2026-09-30 · {len(sel)} jobs", "",
          "| # | Role | Company | Location | Posted | Source |",
          "|---|------|---------|----------|--------|--------|"]
    for i, r in sel.iterrows():
        md.append(
            f"| {i + 1} | [{r['title']}]({r['job_url']}) | {r['company']} | "
            f"{r['location']} | {r['posted']} | {src_short.iloc[i]} |")
    MD_DST.write_text("\n".join(md), encoding="utf-8")
    print(f"[PROFILE] saved -> {CSV_DST.name}, {MD_DST.name} ({len(sel)} jobs)")


if __name__ == "__main__":
    main()
