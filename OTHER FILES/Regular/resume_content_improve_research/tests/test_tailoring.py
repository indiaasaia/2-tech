"""Regression tests for the per-job tailoring pass (generation/tailoring.py).

Core invariants (policy v3, 2026-10-17):
- without a keyword plan only KB material is added (dormant KB skills);
- with a plan, EVERY job-ad keyword lands in the Skills rows (job-ad spelling),
  but an experience/project row or description only carries keywords its KB
  evidence supports (v1's fabrication mechanism was tools in entry rows);
- gap phrases ("Working toward hands-on X") are never added and are removed;
- the pass is idempotent and gates stay clean;
- newly picked projects use verbatim KB titles + evidence-only descriptions.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from resume_content_improve_research.generation import kb_loader
from resume_content_improve_research.generation.claimable_set import build_claimable_set
from resume_content_improve_research.generation.keyword_injector import is_printed
from resume_content_improve_research.generation.keywords import build_keyword_plan
from resume_content_improve_research.generation.tailoring import tailor_components
from resume_content_improve_research.run_step4 import intent_text_for
from resume_content_improve_research.verification.gates import run_prebuild_gates

KB = kb_loader.load_kb()


def make_cset(analysis: dict):
    return build_claimable_set(analysis, KB)


def base_components() -> dict:
    """Draft that uses hft + resume_gen and ignores the vehicle_sharing pool."""
    return {
        "objective": "AI graduate seeking a working student role in applied machine learning.",
        "skills_section": {
            "languages": ["Python", "SQL"],
            "specialized_areas": ["Machine Learning", "Data Analytics"],
            "areas": [
                {"label": "Backend Development", "skills": ["Python", "Django", "FastAPI"]},
                {"label": "AI & Data Modeling", "skills": ["Machine Learning", "Deep Learning"]},
            ],
        },
        "experiences": [
            {"id": "soham", "role": "Software Engineer", "company": "Soham Infotech",
             "location": "Gujarat, India", "dates": "Dec 2023 - Jan 2025",
             "description": "Built backend components and quant models for trading operations.",
             "skills": ["Python", "Quantitative Modeling", "Data Analytics"]},
            {"id": "pantechelearning", "role": "Machine Learning Intern", "company": "Pantechelearning",
             "location": "Chennai, India", "dates": "Dec 2021 - Feb 2022",
             "description": "Implemented machine learning models for text-to-speech applications.",
             "skills": ["Machine Learning", "Data Preprocessing"]},
        ],
        "projects": [
            {"id": "hft", "title": "High Frequency Trading Platform",
             "description": "Developed end-to-end real-time data scraping and analysis system.",
             "skills": ["Python", "Machine Learning", "Data Analytics"]},
            {"id": "resume_gen", "title": "Automated Resume Generation",
             "description": "Built a complete system with structured datasets using an open sourced LLM.",
             "skills": ["Python", "Streamlit", "Large Language Models"]},
        ],
    }


def analysis(**over) -> dict:
    data = {
        "title_core": "Working Student AI",
        "language": "en",
        "required": ["python", "machine learning"],
        "preferred": ["deep learning"],
        "tools": ["Docker"],
        "languages_required": [],
        "domain": "ai",
        "knockouts": [],
    }
    data.update(over)
    return data


def test_dormant_licensed_skill_is_woven_into_a_pool_row():
    # Django is KB-licensed (master_cv) but absent from the draft; JD requires it
    a = analysis(required=["python", "django web development"])
    cset = make_cset(a)
    tailored, report = tailor_components(base_components(), a, cset, KB)
    flat_rows = [s.lower() for e in tailored["experiences"] for s in e["skills"]] + \
                [s.lower() for p in tailored["projects"] for s in p["skills"]] + \
                [s.lower() for area in tailored["skills_section"]["areas"] for s in area["skills"]]
    assert "django" in flat_rows
    assert sum(len(v) for v in report["dormant_added"].values()) >= 1
    # every added skill must be ownable
    ownable = cset.ownable()
    for placed, skills in report["dormant_added"].items():
        for skill in skills:
            assert skill.lower() in ownable, f"{skill} is not ownable"


JOB = {"title": "Working Student Data Science (m/f/d)", "company": "Muster GmbH",
       "job_description": "Analyse data with Python and build REST APIs.",
       "requirements": "pandas, NumPy, scikit-learn, Tableau dashboards; Docker and Figma are a plus."}


def make_plan(a: dict, job: dict | None = None) -> dict:
    return build_keyword_plan(job or JOB, a).to_dict()


def _entry_text(tailored: dict) -> str:
    return json.dumps({
        "exp": [[e["skills"], e["description"]] for e in tailored["experiences"]],
        "proj": [[p["skills"], p["description"]] for p in tailored["projects"]],
    }, ensure_ascii=False).lower()


def _skills_rows(tailored: dict) -> list[str]:
    section = tailored["skills_section"]
    return section["languages"] + section["specialized_areas"] + [
        s for area in section["areas"] for s in area["skills"]]


def test_without_plan_job_tools_never_land_anywhere():
    a = analysis(required=["python", "dashboarding in Tableau"], tools=["Tableau", "Figma"])
    tailored, _ = tailor_components(base_components(), a, make_cset(a), KB)
    flat = json.dumps(tailored, ensure_ascii=False).lower()
    assert "tableau" not in flat and "figma" not in flat


def test_plan_puts_every_keyword_in_skills_but_untrue_ones_never_in_entries():
    a = analysis(required=["pandas library", "python"], tools=["Tableau", "Figma", "Docker"])
    plan = make_plan(a)
    cset = build_claimable_set(a, KB, keywords=plan["targets"])
    tailored, report = tailor_components(base_components(), a, cset, KB, plan=plan)
    rows = _skills_rows(tailored)
    for term in ("pandas", "NumPy", "scikit-learn", "Tableau", "Docker", "Figma", "Python", "REST APIs"):
        assert is_printed(term, rows), f"{term} missing from Skills rows {rows}"
    entries = _entry_text(tailored)
    for tool in ("tableau", "figma", "docker", "numpy"):      # no KB evidence for these
        assert tool not in entries
    assert report["keywords_in_skills"] == sum(1 for k in plan["keywords"] if k["category"] != "education_field")


def test_truthful_keywords_lead_entry_rows():
    a = analysis(required=["python", "REST APIs"])
    plan = make_plan(a)
    cset = build_claimable_set(a, KB, keywords=plan["targets"])
    tailored, report = tailor_components(base_components(), a, cset, KB, plan=plan)
    soham = tailored["experiences"][0]
    assert soham["skills"][:2] == ["Python", "REST APIs"]
    assert "experience:soham" in report["entry_keywords_added"]


def test_job_spelling_is_never_recased():
    a = analysis(required=["pandas library", "python"])
    plan = make_plan(a)
    cset = build_claimable_set(a, KB, keywords=plan["targets"])
    once, _ = tailor_components(base_components(), a, cset, KB, plan=plan)
    twice, _ = tailor_components(once, a, cset, KB, plan=plan)
    assert "pandas" in _skills_rows(twice) and "Pandas" not in _skills_rows(twice)


def test_gap_phrase_is_removed_and_never_added():
    a = analysis(required=["python", "tableau dashboards"], tools=["Tableau"])
    comp = base_components()
    comp["objective"] += " Working toward hands-on Tableau experience."
    plan = make_plan(a)
    cset = build_claimable_set(a, KB, keywords=plan["targets"])
    tailored, report = tailor_components(comp, a, cset, KB, plan=plan)
    assert "working toward" not in tailored["objective"].lower()
    assert report["gap_phrases_removed"] == 1


def test_pass_is_idempotent():
    a = analysis(required=["python", "sql", "dashboarding in Tableau"], tools=["Tableau"])
    cset = make_cset(a)
    once, _ = tailor_components(base_components(), a, cset, KB)
    frozen = copy.deepcopy(once)
    twice, report2 = tailor_components(once, a, cset, KB)
    assert twice == frozen
    assert report2 == {"applied": True, "dormant_added": {}, "project_repick": [],
                       "gate_findings": [], "rows_reordered": 0, "skills_recased": 0,
                       "gap_phrases_removed": 0, "keywords_in_skills": 0, "entry_keywords_added": {},
                       "summary": "dormant_added=0 reorder=0 recased=0 repicked=False "
                                  "gap_removed=0 keywords_in_skills=0 entry_keywords=0"}


def test_plan_pass_is_idempotent():
    a = analysis(required=["pandas library", "python", "REST APIs"], tools=["Tableau", "Docker"])
    plan = make_plan(a)
    cset = build_claimable_set(a, KB, keywords=plan["targets"])
    once, _ = tailor_components(base_components(), a, cset, KB, plan=plan)
    twice, report2 = tailor_components(copy.deepcopy(once), a, cset, KB, plan=plan)
    assert twice == once
    assert report2["entry_keywords_added"] == {} and report2["dormant_added"] == {}


def test_gates_pass_with_plan_including_numbered_keywords():
    job = {"title": "Security Intern", "job_description": "Know the OWASP Top 10, Python and Burp Suite."}
    a = analysis(required=["python"], tools=["Burp Suite"])
    plan = make_plan(a, job)
    cset = build_claimable_set(a, KB, keywords=plan["targets"])
    tailored, _ = tailor_components(base_components(), a, cset, KB, plan=plan)
    assert "OWASP Top 10" in _skills_rows(tailored)
    findings = [f for r in run_prebuild_gates(intent_text_for(tailored), tailored["experiences"], cset,
                                              kb_loader.licensed_digits(KB)) for f in r.findings]
    assert findings == []


def test_gates_pass_on_tailored_output():
    a = analysis(required=["python", "sql", "quant models", "dashboarding in Tableau"],
                 tools=["Tableau"])
    cset = make_cset(a)
    licensed = kb_loader.licensed_digits(KB)
    for draft in (base_components(), tailor_components(base_components(), a, cset, KB)[0]):
        intent = intent_text_for(draft)
        findings = [f for r in run_prebuild_gates(intent, draft["experiences"], cset, licensed)
                    for f in r.findings]
        assert findings == []


def test_repick_uses_kb_title_and_evidence_description():
    # vehicle_sharing's pool matches the JD; the draft does not use it
    a = analysis(required=["python", "javascript", "ui development"])
    cset = make_cset(a)
    tailored, report = tailor_components(base_components(), a, cset, KB)
    assert "vehicle_sharing" in report["project_repick"]
    picked = next(p for p in tailored["projects"] if p["id"] == "vehicle_sharing")
    assert picked["title"] == "Vehicle Sharing Application"
    assert "40+" not in picked["description"] and "24+" not in picked["description"]
    assert picked["description"].split()[0] == "Developed"
    # row stays inside the project's skill pool
    pool = {s.lower() for s in cset.per_project["vehicle_sharing"]}
    assert {s.lower() for s in picked["skills"]} <= pool


def test_area_labels_are_category_names_not_skill_names():
    """Regression: labels built from skill names printed 'Python: Python, HTML, C++'."""
    a = analysis(required=["sql", "data analytics", "python"], tools=["Docker", "Jira"])
    plan = make_plan(a, {"title": "Intern", "job_description": "SQL, Python, Docker and Jira."})
    cset = build_claimable_set(a, KB, keywords=plan["targets"])
    tailored, _ = tailor_components(base_components(), a, cset, KB, plan=plan)
    labels = [area["label"] for area in tailored["skills_section"]["areas"]]
    assert labels[0] in ("Software & Cloud", "Security", "Software, Cloud & Security")
    assert labels[1] in ("Tools & Methods", "Tools, Methods & Soft Skills")


def test_reorder_is_stable_and_idempotent():
    a = analysis(required=["sql", "python"], preferred=["deep learning"])
    cset = make_cset(a)
    comp = base_components()
    comp["experiences"][0]["skills"] = ["Data Analytics", "SQL", "Python"]
    once, r1 = tailor_components(comp, a, cset, KB)
    # JD order wins: the analysis lists sql before python
    assert once["experiences"][0]["skills"] == ["SQL", "Python", "Data Analytics"]
    assert r1["rows_reordered"] >= 1
    twice, r2 = tailor_components(once, a, cset, KB)
    assert twice == once and r2["rows_reordered"] == 0


def test_pool_only_skills_get_display_casing():
    # vehicle_sharing pool ships lowercase 'crud'/'ui development' in the KB;
    # placed rows must show display casing, never raw lowercase
    a = analysis(required=["python", "javascript", "ui development"])
    cset = make_cset(a)
    tailored, _ = tailor_components(base_components(), a, cset, KB)
    picked = next(p for p in tailored["projects"] if p["id"] == "vehicle_sharing")
    assert "CRUD" in picked["skills"] and "UI Development" in picked["skills"]
    assert not any(s == s.lower() and len(s) > 3 for s in picked["skills"]), picked["skills"]


def test_generator_lowercase_skills_get_recased():
    # the generator's normalizer can ship 'django' lowercase; the pass sweeps it
    a = analysis(required=["python", "django web development"])
    cset = make_cset(a)
    comp = base_components()
    comp["experiences"][1]["skills"] = ["Machine Learning", "django", "Data Preprocessing"]
    tailored, report = tailor_components(comp, a, cset, KB)
    assert "Django" in tailored["experiences"][1]["skills"]
    assert "django" not in tailored["experiences"][1]["skills"]
    assert report["skills_recased"] >= 1


def test_without_plan_unlicensed_terms_are_not_added():
    a = analysis(required=["kraken trading api", "python"], tools=["Snowflake"])
    cset = make_cset(a)
    tailored, _ = tailor_components(base_components(), a, cset, KB)
    flat = json.dumps(tailored, ensure_ascii=False).lower()
    assert "kraken" not in flat
    assert "snowflake" not in flat


_COMPONENTS_PATH = PROJECT_ROOT / "program_files" / "output_v2" / "components_v2.json"
if _COMPONENTS_PATH.exists():
    _RECORDS_TO_TEST = json.loads(_COMPONENTS_PATH.read_text(encoding="utf-8"))[:5]
else:
    _RECORDS_TO_TEST = [
        {
            "title": "Working Student Software Engineer (Synthetic)",
            "status": "gated_ok",
            "analysis": analysis(required=["python", "machine learning"], preferred=["deep learning"]),
            "components": base_components(),
        }
    ]


@pytest.mark.parametrize("record", _RECORDS_TO_TEST, ids=lambda r: str(r.get("title"))[:30])
def test_real_records_tailor_clean(record):
    """First 5 real jobs: tailoring keeps G2/G3 clean (same check retailor applies)."""
    if record.get("status") != "gated_ok" or not record.get("components"):
        pytest.skip("job not gated_ok")
    a = record["analysis"]
    cset = make_cset(a)
    licensed = kb_loader.licensed_digits(KB)
    tailored, report = tailor_components(record["components"], a, cset, KB)
    findings = [f for r in run_prebuild_gates(
        intent_text_for(tailored), tailored["experiences"], cset, licensed) for f in r.findings]
    assert findings == report["gate_findings"] == []