"""Miniature end-to-end prototype: analyst -> claimable set -> constrained generation -> gates.

Answers empirically: does constraining the generator to KB+JD-licensed tools eliminate
fabrication (the V6 systemic finding), and at what coverage cost? Run on 2 real jobs
(one English, one German), then re-run the V6 gate checks on the new output vs the
current output.

Run: python resume_content_improve_research/experiment/mini_pipeline.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
EXP = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = "https://ollama.com"
MODEL = "gpt-oss:120b"

# ---- minimal KB (same as verify_all.py) ----
KB_SKILLS = {
    "backend engineering", "software engineering", "backend systems", "server-side systems",
    "system integration", "database management", "data management", "data storage",
    "latency optimization", "performance optimization", "cross-functional collaboration",
    "backend development", "backend infrastructure", "web application development",
    "mysql", "django", "flask", "machine learning workflow support",
    "python", "api integration", "data fetching", "automation", "market data",
    "nlp", "llm", "llms", "large language models", "transformers", "research", "sql",
}
TECH_RE = re.compile(
    r"\b(python|java|javascript|typescript|c\+\+|c#|sql|mysql|postgres(?:ql)?|mongodb|redis|"
    r"docker|kubernetes|k8s|aws|azure|gcp|git|jenkins|react|angular|vue|node\.?js|spring|"
    r"fastapi|django|flask|tensorflow|pytorch|pandas|numpy|spark|hadoop|kafka|airflow|tableau|"
    r"power\s?bi|excel|sap|salesforce|hubspot|jira|confluence|linux|bash|etl|erp|crm|hris|plc|"
    r"scada|rexx|rest|graphql|api|apis|nlp|llm|llms|transformers|agile|scrum|kanban|latex|matlab|vba)\b",
    re.IGNORECASE,
)
SPELL = {"zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,
         "nine":9,"ten":10,"fifteen":15,"twenty":20,"thirty":30,"forty":40,"fifty":50}
KB_DIGITS = {"40", "24"}

def load_key() -> str:
    for name in ("active_ollama_keys.json", "ollama_keys.json"):
        p = ROOT / "sub_program_files" / name
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            keys = data.get("keys", []) if isinstance(data, dict) else data
            if keys:
                return str(keys[0]).strip()
    raise SystemExit("no key")

def call_llm(prompt: str, token: str, temperature: float = 0.2) -> str:
    resp = requests.post(
        f"{HOST}/v1/chat/completions",
        json={"model": MODEL, "temperature": temperature,
              "messages": [{"role": "user", "content": prompt}]},
        headers={"Authorization": f"Bearer {token}"}, timeout=180)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]

def extract_json(raw: str):
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    return json.loads(m.group(0)) if m else None

# ---- stage 1: analyst (patched per V6: language example, tier rules, short items) ----
ANALYST_PROMPT = """You are a precise job-description analyst. Extract structured data from the posting below.
Return ONLY valid JSON, exactly this schema, no markdown:
{"title_core": "...", "language": "en|de",
 "required": ["verbatim hard requirement terms, max 4 words each, max 10 items"],
 "preferred": ["verbatim nice-to-have terms, max 4 words each, max 8 items"],
 "tools": ["named tools/technologies/software, verbatim, max 12 items"],
 "languages_required": [{"language": "English or German", "level": "e.g. B2, C1, fluent, business, native, or null"}],
 "years_experience": null, "domain": "..."}
Rules: copy tool names EXACTLY as the posting writes them. If the posting mentions any language
requirement (English OR German, any level incl. "basic", "fluency", "business"), it MUST appear in
languages_required. Distinguish required (must-have section) from preferred ("nice to have",
"ideally", "bonus", "plus").

JOB POSTING:
Title: {{TITLE}}
Description: {{DESCRIPTION}}"""

# ---- stage 2: claimable set ----
def claimable_set(analysis: dict) -> dict:
    tools = [t for t in analysis.get("tools", []) if t and len(t) <= 25]
    return {
        "kb_skills": sorted(KB_SKILLS),
        "jd_tools": tools,                      # MIRRORABLE ONLY, never as candidate-owned skills
        "required": analysis.get("required", [])[:10],
        "preferred": analysis.get("preferred", [])[:8],
    }

# ---- stage 3: constrained generation (objective + skills in ONE call; projects GROUNDED) ----
GEN_PROMPT = """You are an expert ATS resume writer. Generate a career objective, skills section and
two projects for ONE job using ONLY the licensed material below.

### LICENSED TOOLS (the ONLY technologies you may mention anywhere):
{{TOOLS}}

### CANDIDATE FACTS (the ONLY experiences/projects you may use):
- ~1 year backend engineering (Soham Infotech): integrated backend systems, servers, databases to
  improve latency, data management, performance; cross-functional team
- 3-month internship (Pantechelearning): MySQL for data management/storage supporting ML workflows;
  backend infrastructure with Django and Flask
- Real project 1 "TradingView Data Fetch": market-data fetching tool, open source, 40+ GitHub stars,
  built with Python
- Real project 2: ongoing MSc research on LLMs for sarcasm detection in low-resourced Indic languages
- MSc AI student at BTU Cottbus-Senftenberg, Germany (Apr 2025-present); BE Computer Eng. GTU 2020-2024

### JOB
Target role: {{TITLE}}
Key requirements: {{REQUIRED}}

### RULES
1. Projects MUST be the two real projects above, re-emphasized toward this job. NEVER invent a new
   project, tool, metric or number. The only numbers allowed: 40+ stars, 24+ forks, the years above.
2. The candidate's professional skills are ONLY the licensed backend/database skills. You may NOT
   claim any licensed tool as the candidate's skill UNLESS it appears in the candidate facts above.
   Tools from the job posting may ONLY appear in the objective as "targeting/familiar with" framing
   if the candidate genuinely used them; otherwise omit them.
3. Never invent technologies, employers, metrics, or achievements. Never use percentages.
4. Output ONLY valid JSON exactly:
{"career_objective": "2-4 sentences, max 60 words",
 "skills": {"programming_languages": ["4-6"], "specialized_areas": ["4-5"],
            "area_1": {"label": "2-5 words", "skills": ["4-8", from candidate facts only]},
            "area_2": {"label": "2-5 words", "skills": ["4-8", from candidate facts only]}},
 "projects": [{"title": "TradingView Data Fetch", "description": "max 40 words, this job's angle",
               "skills": ["4-8"]},
              {"title": "LLM Sarcasm Detection Study", "description": "max 40 words, this job's angle",
               "skills": ["4-8"]}]}}"""

def gate_check(generated: dict) -> list[str]:
    issues = []
    blob = json.dumps(generated).lower()
    # tech tokens: everything must be KB skill OR in the mirrorable JD tools
    for m in TECH_RE.finditer(blob):
        tok = m.group(0).lower()
        if tok not in KB_SKILLS:
            issues.append(f"G2-tech: {tok}")
    # digit rule incl. spelled-out (V6 patch)
    for m in re.finditer(r"\b(\d+(?:\.\d+)?)\s*(?:%|percent|x\b)", blob):
        if m.group(1) not in KB_DIGITS:
            issues.append(f"G2-digit: {m.group(0)}")
    for word, num in SPELL.items():
        if re.search(rf"\b{word}\s+percent", blob):
            issues.append(f"G2-digit: spelled '{word} percent'")
    # invented project check
    for p in generated.get("projects", []):
        if p.get("title", "").lower() not in ("tradingview data fetch", "llm sarcasm detection study"):
            issues.append(f"G2-project: invented title {p.get('title')!r}")
    return issues

def coverage_score(generated: dict, analysis: dict) -> tuple[float, list[str]]:
    text = json.dumps(generated).lower()
    req = analysis.get("required", [])
    tools = [t.lower() for t in analysis.get("tools", [])]
    hits, missing = 0, []
    for term in req + tools:
        t = term.lower()
        if t and (t in text or any(t in s.lower() for s in generated.get("skills", {}).get("specialized_areas", []))):
            hits += 1
        else:
            missing.append(term)
    total = max(1, len(req) + len(tools))
    return round(hits / total, 2), missing

def main() -> int:
    rows = list(csv.DictReader(open(ROOT / "program_files" / "output" / "2_filted_jobs.csv", encoding="utf-8")))
    en = next((r for r in rows if not re.search(r"[äöüÄÖÜ]", r.get("job_description", "")[:2000])), rows[0])
    de = next((r for r in rows if re.search(r"[äöüÄÖÜ]|(und|für|mit) ", r.get("job_description", "")[:2000])), None)
    token = load_key()
    results = {}
    for label, job in (("english_jd", en), ("german_jd", de)):
        if not job:
            continue
        print(f"\n=== {label}: {job['title'][:50]} ===")
        # stage 1
        t0 = time.time()
        analysis = extract_json(call_llm(
            ANALYST_PROMPT.replace("{{TITLE}}", job["title"]).replace("{{DESCRIPTION}}", job["job_description"][:6000]),
            token, temperature=0.1))
        print(f"1. analyst: {time.time()-t0:.1f}s | tools={analysis.get('tools')} | "
              f"languages={analysis.get('languages_required')}")
        # stage 2
        cset = claimable_set(analysis)
        # stage 3
        t0 = time.time()
        gen_raw = call_llm(
            GEN_PROMPT
            .replace("{{TOOLS}}", ", ".join(cset["jd_tools"]) or "(none)")
            .replace("{{TITLE}}", analysis.get("title_core", job["title"]))
            .replace("{{REQUIRED}}", "; ".join(cset["required"] + cset["preferred"]) or job["job_description"][:800]),
            token)
        generated = extract_json(gen_raw)
        print(f"3. generation: {time.time()-t0:.1f}s | json_ok={generated is not None}")
        if generated is None:
            results[label] = {"error": "generation JSON failed"}
            continue
        # stage 4: gates + coverage
        issues = gate_check(generated)
        cov, missing = coverage_score(generated, analysis)
        print(f"4. gates: {len(issues)} issue(s) {issues[:6]}")
        print(f"   coverage={cov} | missing={missing[:8]}")
        print(f"   objective: {generated['career_objective'][:140]}...")
        results[label] = {"analysis": analysis, "generated": generated,
                          "gate_issues": issues, "coverage": cov, "missing": missing}
    EXP.joinpath("mini_pipeline_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nsaved -> mini_pipeline_results.json")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
