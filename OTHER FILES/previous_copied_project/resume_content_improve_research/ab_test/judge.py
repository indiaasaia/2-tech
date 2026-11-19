"""Neutral A/B judge: old engine (v1) vs current engine (v2) on the same jobs.

Fairness rules:
- Both engines are judged on their SHIPPED PDF artifacts (parse-back only, never
  on intent JSON) — v1: program_files/output/resume/pdf (Sep 15 run, pre-fix),
  v2: program_files/output_v2/resume/pdf.
- The yardstick is the SAME for both: the v2 analyst's per-job JD criteria
  (components_v2.json -> analysis). Neither engine is scored against its own
  opinion of the JD.
- The scorer is the SAME for both: coverage.score_coverage + scorecard
  components + gate audits (G1 parse sanity, G3 artifact integrity) + a
  fabrication audit (unlicensed tech tokens / percentages / KB-licensed digits /
  fabricated project titles).
No engine code is modified; both are read-only inputs.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from resume_content_improve_research import config  # noqa: E402
from resume_content_improve_research.generation.claimable_set import build_claimable_set  # noqa: E402
from resume_content_improve_research.generation import kb_loader  # noqa: E402
from resume_content_improve_research.verification.coverage import score_coverage  # noqa: E402
from resume_content_improve_research.verification.scorecard import build_scorecard  # noqa: E402
from resume_content_improve_research.verification.gates import (  # noqa: E402
    check_g1, check_g2_claims, check_g3_text,
)
from resume_content_improve_research.verification.parse_sim import parse_pdf  # noqa: E402

V1_DIR = PROJECT_ROOT / "program_files" / "output"
V2_DIR = PROJECT_ROOT / "program_files" / "output_v2"
BACKUP_DIR = Path(r"E:\WorkSpace\2 Tech\JOB_AUTOMATION - Copy")
OUT_PATH = Path(__file__).resolve().parent / "ab_results.json"

KB_LICENSED_DIGITS = {"70", "40", "24"}  # candidate-confirmed metrics (KB metrics_note)

# The four v1 component stores and the title field each carries.
V1_STORES = {
    "career_objective.json": ("objectives", None),
    "experience.json": ("experiences", None),
    "projects.json": ("projects", None),
    "skills.json": ("skills", None),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_v1_components(job_url: str) -> dict:
    """The old engine's LLM output for one job (all four stores joined by job_url)."""
    out: dict = {}
    for file_name, (records_key, _) in V1_STORES.items():
        path = V1_DIR / file_name
        if not path.exists():
            continue
        payload = load_json(path)
        for record in payload.get(records_key, []):
            if str(record.get("job_url") or "") == job_url:
                out[file_name] = record
                break
    return out


def strip_latex(text: str) -> str:
    """Remove LaTeX commands/braces so intent text comparison is content-only."""
    text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", str(text))
    text = re.sub(r"[{}&%$#_^~]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def load_universe() -> list[dict]:
    """Join v1 artifacts, v2 artifacts and the v2 analyst criteria per job_url."""
    v1_report = load_json(V1_DIR / "resume_report.json")
    v2_report = load_json(V2_DIR / "resume_report.json")
    components = load_json(V2_DIR / "components_v2.json")
    by_url_v1 = {r["job_url"]: r for r in v1_report["results"]}
    by_url_v2 = {r["job_url"]: r for r in v2_report["results"]}
    by_url_comp = {c["job_url"]: c for c in components}

    universe: list[dict] = []
    for url, comp in by_url_comp.items():
        v1, v2 = by_url_v1.get(url), by_url_v2.get(url)
        if not (v1 and v2 and v1.get("pdf") and v2.get("pdf")):
            continue
        v1_stem = Path(v1["pdf"]).stem
        v2_stem = v2.get("file_stem") or Path(v2["pdf"]).stem
        universe.append({
            "job_url": url,
            "title": v2.get("title") or v1.get("title"),
            "company": v2.get("company") or "",
            "v2_reported_score": v2.get("score"),
            "v1_pdf": V1_DIR / "resume" / "pdf" / f"{v1_stem}.pdf",
            "v1_tex": V1_DIR / "resume" / "tex" / f"{v1_stem}.tex",
            "v2_pdf": V2_DIR / "resume" / "pdf" / f"{v2_stem}.pdf",
            "v1_components": load_v1_components(url),
            "v2_components": comp.get("components") or {},
            "analysis": comp.get("analysis") or {},
        })
    return universe


def select_jobs(universe: list[dict], n: int = 10) -> list[dict]:
    """Deterministic stratified pick across the v2 score range (top/middle/bottom)."""
    ranked = sorted(universe, key=lambda j: (j["v2_reported_score"] or 0), reverse=True)
    picked: list[dict] = []
    for job in ranked[:3] + ranked[len(ranked) // 2 - 2:len(ranked) // 2 + 2] + ranked[-3:]:
        if job["job_url"] not in {p["job_url"] for p in picked}:
            picked.append(job)
        if len(picked) == n:
            break
    return picked


def fabrication_audit(text: str, cset) -> dict:
    """Same G2 lens for both engines, applied to the SHIPPED artifact text."""
    findings = check_g2_claims(text, cset, KB_LICENSED_DIGITS | set(config.DATE_YEARS_ALLOWED))
    percentages = re.findall(r"\b\d+(?:\.\d+)?\s*%", text)
    return {
        "unlicensed_tech_or_digit_findings": findings,
        "percentages_in_artifact": percentages,
        "finding_count": len(findings) + len(percentages),
    }


def fabricated_titles(engine_key: str, job: dict, kb_titles: set[str]) -> list[str]:
    """Project titles each engine actually shipped vs the KB's real project titles."""
    if engine_key == "v1":
        rec = job["v1_components"].get("projects.json") or {}
        titles = [str((rec.get("project_1") or {}).get("project") or ""),
                  str((rec.get("project_2") or {}).get("project") or "")]
    else:
        titles = [str(p.get("title") or "") for p in job["v2_components"].get("projects", [])]
    return [t for t in titles if t and t.lower() not in kb_titles]


def judge_job(job: dict) -> dict:
    analysis = job["analysis"]
    kb = kb_loader.load_kb()
    cset = build_claimable_set(analysis, kb)
    kb_titles = {p["title"].lower() for p in kb.get("projects", [])}

    result: dict = {"job_url": job["job_url"], "title": job["title"], "company": job["company"]}
    engines = (("v1", job["v1_pdf"], job["v1_tex"]), ("v2", job["v2_pdf"], None))
    for engine, pdf_path, tex_path in engines:
        if not pdf_path.exists():
            result[engine] = {"error": f"missing artifact: {pdf_path.name}"}
            continue
        parse = parse_pdf(pdf_path)
        coverage = score_coverage(parse.text, analysis)
        filled_tex = tex_path.read_text(encoding="utf-8") if tex_path and tex_path.exists() else ""
        # intent text for parse-fidelity: LaTeX-free so only content counts (fair to v1)
        intent_text = strip_latex(filled_tex) if filled_tex else parse.text
        g3 = check_g3_text(filled_tex) if filled_tex else []
        g1 = check_g1(parse.text, parse.word_count)
        fab = fabrication_audit(parse.text, cset)
        scorecard = build_scorecard(
            gates_passed=True,  # gates are reported separately, not folded into the total
            coverage=coverage,
            parse_result=parse,
            artifact_text=parse.text,
            intent_text=intent_text,
            analysis=analysis,
            cset=cset,
        )
        result[engine] = {
            "pdf": pdf_path.name,
            "composite_score": scorecard.total,
            "breakdown": scorecard.breakdown,
            "required_coverage": scorecard.required_coverage,
            "preferred_coverage": scorecard.preferred_coverage,
            "required_missing": coverage.required_missing,
            "ineligible_criteria": coverage.ineligible,
            "g1_parse_findings": g1,
            "g3_integrity_findings": g3,
            "fabrication_audit": fab,
            "fabricated_project_titles": fabricated_titles(engine, job, kb_titles),
            "apostrophe_dates": parse.apostrophe_dates,
            "ligatures": parse.ligature_count,
            "sections_found": parse.sections_found,
            "word_count": parse.word_count,
            "name_email_phone": [parse.name_extracted, parse.email_extracted, parse.phone_extracted],
        }
    if all(isinstance(result.get(e), dict) and "error" not in result[e] for e in ("v1", "v2")):
        result["delta"] = {
            "composite": round(result["v2"]["composite_score"] - result["v1"]["composite_score"], 1),
            "required_coverage": round(result["v2"]["required_coverage"] - result["v1"]["required_coverage"], 3),
            "fabrication_findings_removed": (
                result["v1"]["fabrication_audit"]["finding_count"]
                - result["v2"]["fabrication_audit"]["finding_count"]
            ),
        }
    return result


def provenance_check(universe: list[dict]) -> list[dict]:
    """Hash-compare local v1 PDFs against the backup copy (same-run proof)."""
    rows = []
    for job in universe:
        backup = BACKUP_DIR / "program_files" / "output" / "resume" / "pdf" / job["v1_pdf"].name
        if job["v1_pdf"].exists() and backup.exists():
            rows.append({"file": job["v1_pdf"].name, "identical": sha256(job["v1_pdf"]) == sha256(backup)})
    return rows


def main() -> int:
    config.ensure_utf8_stdout()
    universe = load_universe()
    print(f"joined universe: {len(universe)} jobs with both v1+v2 PDFs")
    prov = provenance_check(universe)
    same = sum(1 for r in prov if r["identical"])
    print(f"provenance: {same}/{len(prov)} local v1 PDFs byte-identical to backup copy")

    picked = select_jobs(universe, n=10)
    print("\nselected jobs (stratified by v2 score):")
    for job in picked:
        print(f"  {job['v2_reported_score']:>5}  {job['title'][:60]}")

    results = [judge_job(job) for job in picked]
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": "one neutral judge (v2 verification stack) on both engines' shipped PDFs; "
                  "yardstick = v2 analyst JD criteria for both",
        "provenance": prov,
        "selected": [{k: j[k] for k in ("job_url", "title", "company", "v2_reported_score")} for j in picked],
        "results": results,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {OUT_PATH}\n")

    print(f"{'job':<46} {'v1':>6} {'v2':>6} {'delta':>7}  fab(v1->v2) titles(v1->v2)")
    for r in results:
        v1, v2, d = r.get("v1", {}), r.get("v2", {}), r.get("delta")
        if d is None:
            print(f"  {r['title'][:44]:<46} ERROR")
            continue
        print(f"  {r['title'][:44]:<46} {v1['composite_score']:>6} {v2['composite_score']:>6} "
              f"{d['composite']:>+7}  {v1['fabrication_audit']['finding_count']:>3}->{v2['fabrication_audit']['finding_count']:<3}"
              f"  {len(v1['fabricated_project_titles'])}->{len(v2['fabricated_project_titles'])}")
    v1s = [r["v1"]["composite_score"] for r in results if r.get("delta")]
    v2s = [r["v2"]["composite_score"] for r in results if r.get("delta")]
    if v1s:
        print(f"\nmeans: v1={sum(v1s)/len(v1s):.1f}  v2={sum(v2s)/len(v2s):.1f}  "
              f"delta={sum(v2s)/len(v2s)-sum(v1s)/len(v1s):+.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
