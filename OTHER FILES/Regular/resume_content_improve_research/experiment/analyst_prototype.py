"""Prototype the V2/V5 JD-analyst call: structured requirement extraction from real JDs.

Tests on one English and one German job from the current run, measures JSON validity,
schema compliance, and latency. Uses the same Ollama endpoint as the pipeline.

Run: python resume_content_improve_research/experiment/analyst_prototype.py
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
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = "https://ollama.com"
MODEL = "gpt-oss:120b"

def load_key() -> str:
    for name in ("active_ollama_keys.json", "ollama_keys.json"):
        path = ROOT / "sub_program_files" / name
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            keys = data.get("keys", []) if isinstance(data, dict) else data
            if keys:
                return str(keys[0]).strip()
    raise SystemExit("no key")

PROMPT = """You are a precise job-description analyst. Extract structured data from the job posting below.
Return ONLY valid JSON matching exactly this schema, no markdown, no explanation:
{
  "title_core": "cleaned job title without (m/f/d) suffixes",
  "language": "en|de",
  "required": ["hard requirements/must-have skills, verbatim terms"],
  "preferred": ["nice-to-have skills, verbatim terms"],
  "tools": ["named tools/technologies/frameworks"],
  "languages_required": [{"language": "English|German", "level": "e.g. B2|fluent|native or null"}],
  "years_experience": "number or null",
  "domain": "one-phrase domain label",
  "responsibilities": ["top 5 responsibilities, verbatim key terms only"]
}

JOB POSTING:
Title: {{TITLE}}
Description: {{DESCRIPTION}}"""

def analyze(job: dict, token: str) -> dict:
    prompt = (PROMPT
        .replace("{{TITLE}}", job.get("title", ""))
        .replace("{{DESCRIPTION}}", job.get("job_description", "")[:6000]))
    start = time.time()
    resp = requests.post(
        f"{HOST}/v1/chat/completions",
        json={"model": MODEL, "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.1},
        headers={"Authorization": f"Bearer {token}"},
        timeout=180,
    )
    resp.raise_for_status()
    latency = time.time() - start
    raw = resp.json()["choices"][0]["message"]["content"]
    # robust JSON extraction
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    ok, data, err = False, None, ""
    if not match:
        err = "no JSON object in response"
    else:
        try:
            data = json.loads(match.group(0))
            ok = True
        except json.JSONDecodeError as exc:
            err = f"JSON parse: {exc}"
    schema_ok = False
    if ok:
        required_keys = {"title_core", "language", "required", "preferred", "tools",
                         "languages_required", "years_experience", "domain", "responsibilities"}
        schema_ok = required_keys.issubset(data.keys())
    return {"latency_s": round(latency, 1), "json_ok": ok, "schema_ok": schema_ok,
            "error": err, "data": data, "raw_len": len(raw)}

def main() -> int:
    rows = list(csv.DictReader(open(ROOT / "program_files" / "output" / "2_filted_jobs.csv", encoding="utf-8")))
    # one English JD and one German JD (by umlaut/und signal)
    en = next((r for r in rows if not re.search(r"[äöüÄÖÜ]", r.get("job_description", "")[:2000])), rows[0])
    de = next((r for r in rows if re.search(r"[äöüÄÖÜ]|(und|für|mit) ", r.get("job_description", "")[:2000])), None)
    token = load_key()
    out = {}
    for label, job in (("english_jd", en), ("german_jd", de)):
        if not job:
            continue
        print(f"analyzing {label}: {job['title'][:50]}...")
        result = analyze(job, token)
        out[label] = {"title": job["title"], **result}
        print(f"  latency={result['latency_s']}s json_ok={result['json_ok']} schema_ok={result['schema_ok']} {result['error']}")
        if result["data"]:
            d = result["data"]
            print(f"  title_core: {d.get('title_core')}")
            print(f"  required({len(d.get('required', []))}): {d.get('required', [])[:5]}")
            print(f"  preferred({len(d.get('preferred', []))}): {d.get('preferred', [])[:4]}")
            print(f"  tools: {d.get('tools', [])[:8]}")
            print(f"  languages: {d.get('languages_required')}")
            print(f"  years: {d.get('years_experience')} | domain: {d.get('domain')}")
    Path(__file__).with_name("analyst_results.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nsaved -> analyst_results.json")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
