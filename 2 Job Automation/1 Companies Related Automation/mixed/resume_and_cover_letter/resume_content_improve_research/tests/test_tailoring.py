"""Regression tests for the per-job tailoring pass (generation/tailoring.py).

Core invariants:
- only claimable-set material is added (dormant KB skills, mirrorable JD tools);
- mirrorable JD tools NEVER land in rows/descriptions (v1's fabrication mechanism:
  HubSpot/Flask-in-skill-rows produced 32 fabricated claims);
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


def test_mirrorable_tool_never_lands_in_rows_or_descriptions():
    # v1's fabrication mechanism: JD tools written into skill rows / descriptions
    a = analysis(required=["python", "dashboarding in Tableau"], tools=["Tableau", "Figma"])
    cset = make_cset(a)
    tailored, _ = tailor_components(base_components(), a, cset, KB)
    row_desc_text = json.dumps({
        "exp": [[e["skills"], e["description"]] for e in tailored["experiences"]],
        "proj": [[p["skills"], p["description"]] for p in tailored["projects"]],
        "areas": tailored["skills_section"]["areas"],
    }, ensure_ascii=False).lower()
    assert "tableau" not in row_desc_text
    assert "figma" not in row_desc_text
    assert "figma" not in tailored["objective"].lower()  # not in required/preferred -> not mirrored


def test_mirror_target_goes_to_objective_when_listed_as_required():
    a = analysis(required=["python", "tableau dashboards"], tools=["Tableau"])
    cset = make_cset(a)
    tailored, report = tailor_components(base_components(), a, cset, KB)
    assert tailored["objective"].lower().count("tableau") == 1
    assert report["mirror_targets"] == ["Tableau"]
    assert len(tailored["objective"].split()) <= 75


def test_pass_is_idempotent():
    a = analysis(required=["python", "sql", "dashboarding in Tableau"], tools=["Tableau"])
    cset = make_cset(a)
    once, _ = tailor_components(base_components(), a, cset, KB)
    frozen = copy.deepcopy(once)
    twice, report2 = tailor_components(once, a, cset, KB)
    assert twice == frozen
    assert report2 == {"applied": True, "mirror_targets": [], "dormant_added": {},
                       "desc_insertions": [], "area_labels": {}, "project_repick": [],
                       "gate_findings": [], "rows_reordered": 0, "skills_recased": 0,
                       "summary": "mirror=0 dormant_added=0 desc_insertions=0 labels=0 "
                                  "reorder=0 recased=0 repicked=False"}


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


def test_area_label_derived_from_required_matches():
    a = analysis(required=["sql", "data analytics", "python"])
    cset = make_cset(a)
    comp = base_components()
    # labels derive from the area's OWN skills: give one area a SQL-anchored row
    comp["skills_section"]["areas"][0]["skills"] = ["Python", "SQL", "Data Analytics"]
    tailored, report = tailor_components(comp, a, cset, KB)
    labels = [area["label"] for area in tailored["skills_section"]["areas"]]
    assert any("SQL" in label for label in labels)
    assert all(len(label.split()) <= 4 for label in labels)
    assert report["area_labels"], "label change must be reported"


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


def test_honest_gaps_are_not_filled():
    a = analysis(required=["kraken trading api", "python"], tools=["Snowflake"])
    cset = make_cset(a)
    tailored, report = tailor_components(base_components(), a, cset, KB)
    assert "Snowflake" not in tailored["objective"]
    assert report["mirror_targets"] == []
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