"""Prototype the V5 verification gates and run them against all 21 current jobs.

Implements the minimal candidate KB (from the prompt-embedded facts), a compact
alias map, and the deterministic gates:
  G1: parse artifact, word-count sanity, name/contact/sections intact
  G2: tech tokens ⊆ KB-allowed; digits ∈ KB evidence (digit rule)
  G3: no collided/leftover placeholders in the artifact

Measures per job: what is caught, what is missed, false positives.
Run: python resume_content_improve_research/experiment/verify_all.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "program_files" / "output"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------- KB (minimal, from prompt facts)
KB = {
    "skills_allowed": {
        # stint 1 (Soham Infotech) — from experience_1_prompt.md
        "backend engineering", "software engineering", "backend systems", "server-side systems",
        "system integration", "database management", "data management", "data storage",
        "latency optimization", "performance optimization", "cross-functional collaboration",
        "backend development", "backend infrastructure", "web application development",
        "server-side development", "process efficiency",
        # stint 2 (Pantechelearning) — explicitly established
        "mysql", "django", "flask", "database-related work", "machine learning workflow support",
        # real projects
        "python", "api integration", "data fetching", "automation", "market data",
        # research (sarcasm study)
        "nlp", "llm", "llms", "large language models", "transformers", "research",
        # languages/tools honestly implied by projects/prompts
        "sql",
    },
    "digits": {
        # all numbers allowed anywhere: dates and the GitHub stats of the real project
        "2020", "2021", "2022", "2023", "2024", "2025", "2026",
        "40", "24", "40+", "24+",
    },
    "tech_token_re": re.compile(
        r"\b(python|java|javascript|typescript|c\+\+|c#|sql|mysql|postgres(?:ql)?|mongodb|redis|"
        r"docker|kubernetes|k8s|aws|azure|gcp|git|jenkins|react|angular|vue|node\.?js|spring|"
        r"fastapi|django|flask|tensorflow|pytorch|sklearn|scikit-learn|pandas|numpy|spark|hadoop|"
        r"kafka|airflow|tableau|power\s?bi|excel|sap|salesforce|hubspot|jira|confluence|linux|bash|"
        r"etl|erp|crm|hris|plc|scada|siemens|tIA|rest|graphql|api|apis|nlp|llm|llms|transformers|"
        r"agile|scrum|kanban|ci|cd|ci/cd|latex|matlab|vba|powerapps|servicenow|autoCADE|autocad)\b",
        re.IGNORECASE,
    ),
}

ALIAS = {  # term → canonical (used by the scorer, listed here for reference/suggestion)
    "k8s": "kubernetes", "ml": "machine learning", "ci/cd": "ci",
    "postgres": "postgresql", "js": "javascript", "golang": "go",
}

SECTION_KEYWORDS = [
    "career objective", "experience", "education", "projects", "research", "achievements",
    "skills", "certifications", "languages", "declaration", "publications",
]

def load_component_maps():
    def load(name, key):
        data = json.load(open(OUT_DIR / name, encoding="utf-8"))
        return {r["job_url"]: r for r in data[key]}
    return {
        "objective": load("career_objective.json", "objectives"),
        "experience": load("experience.json", "experiences"),
        "projects": load("projects.json", "projects"),
        "skills": load("skills.json", "skills"),
    }

def collect_claims(map_key: str, record: dict) -> str:
    if map_key == "objective":
        return record.get("career_objective", "")
    if map_key == "experience":
        parts = []
        for slot in ("experience_1", "experience_2"):
            entry = record.get(slot, {})
            parts += [entry.get("role", ""), entry.get("description", ""), ",".join(entry.get("skills", []))]
        return " ".join(parts)
    if map_key == "projects":
        parts = []
        for slot in ("project_1", "project_2"):
            entry = record.get(slot, {})
            parts += [entry.get("project", ""), entry.get("description", ""), ",".join(entry.get("skills", []))]
        return " ".join(parts)
    if map_key == "skills":
        sec = record.get("skills_section", {})
        parts = list(sec.get("languages", [])) + list(sec.get("specialized_areas", []))
        for key in ("skills_area_1", "skills_area_2"):
            area = sec.get(key, {})
            parts += [area.get("label", ""), ",".join(area.get("skills", []))]
        return " ".join(parts)
    return ""

def run():
    maps = load_component_maps()
    report = json.load(open(OUT_DIR / "resume_report.json", encoding="utf-8"))["results"]
    rows = {r["job_url"]: r for r in csv.DictReader(open(OUT_DIR / "2_filted_jobs.csv", encoding="utf-8"))}

    findings = []
    for res in report:
        url = res["job_url"]
        pdf_path = res.get("pdf")
        if not pdf_path or not Path(pdf_path).exists():
            findings.append({"job": url[-30:], "gate": "G1", "issue": "no pdf"})
            continue
        with pdfplumber.open(pdf_path) as pdf:
            pages = pdf.pages
            text = "\n".join(p.extract_text() or "" for p in pages)
            word_count = sum(len(p.extract_words() or []) for p in pages)
        job = {"job": rows.get(url, {}).get("title", url)[-32:], "url": url, "issues": []}

        # ---- G1: parse sanity
        if word_count < 200 or word_count > 900:
            job["issues"].append(f"G1: word count {word_count} outside 200-900 (segmentation/corruption?)")
        if "RAVAL" not in text:
            job["issues"].append("G1: name not extractable")
        if not re.search(r"\S+@\S+\.\S+", text):
            job["issues"].append("G1: email not extractable")
        found_sections = [kw for kw in SECTION_KEYWORDS if kw in text.lower()]
        if len(found_sections) < 6:
            job["issues"].append(f"G1: only {len(found_sections)} sections detectable")

        # ---- G2: KB checks on the INTENT (component JSONs)
        for map_key in ("objective", "experience", "projects", "skills"):
            claims = collect_claims(map_key, maps[map_key][url])
            for m in KB["tech_token_re"].finditer(claims):
                token = m.group(0).lower()
                if token not in KB["skills_allowed"]:
                    job["issues"].append(f"G2: tech token {token!r} not KB-licensed ({map_key})")
            for m in re.finditer(r"\d+(?:\.\d+)?%?|\d+\+", claims):
                token = m.group(0).lstrip("0").rstrip(".") or m.group(0)
                if token not in KB["digits"] and not re.match(r"^(19|20)\d{2}", token):
                    job["issues"].append(f"G2: digit {m.group(0)!r} not in KB evidence ({map_key})")

        # ---- G3: artifact placeholder/collision check
        if "PROJECT-" in text:
            job["issues"].append("G3: literal 'PROJECT-' in artifact (replacement-order collision)")
        for bad in ("AREER BJECTIVE", "E XPERIENCE", "E DUCATION", "KILLS"):
            if bad in text:
                job["issues"].append(f"G3: corrupted section title {bad!r} in artifact")
        if re.search(r"[A-Z][a-z]{2}[’']\d{2}", text):
            job["issues"].append("G3: apostrophe-year dates present (parser-invisible)")

        # ---- cross-artifact fidelity: keywords in intent must be in artifact
        intent = " ".join(collect_claims(k, maps[k][url]) for k in ("objective", "experience", "projects", "skills")).lower()
        for token in set(re.findall(r"[a-z][a-z+#.-]{3,}", intent)):
            if re.fullmatch(KB["tech_token_re"].pattern, token, re.IGNORECASE) and token in intent and token not in text.lower():
                job["issues"].append(f"G3: KB skill {token!r} in intent but MISSING from artifact")

        findings.append(job)

    # ---------------- summary
    from collections import Counter
    all_issues = [i for f in findings for i in f["issues"]]
    gate_counts = Counter(i.split(":")[0] for i in all_issues)
    print("=== V5-GATE BAKE-OFF ON 21 CURRENT JOBS ===")
    print("jobs run:", len(findings), "| jobs with 0 issues:", sum(1 for f in findings if not f["issues"]))
    print("issues by gate:", dict(gate_counts))
    print("\nissue frequency:")
    for issue, count in Counter(i.split("(", 1)[0] for i in all_issues).most_common(12):
        print(f"  [{count}] {issue}")
    print("\nper-job issue count:")
    for f in findings:
        print(f"  {f['job']:34} {len(f['issues'])}")
    Path(__file__).with_name("verify_results.json").write_text(
        json.dumps(findings, indent=2, ensure_ascii=False), encoding="utf-8")

if __name__ == "__main__":
    run()
