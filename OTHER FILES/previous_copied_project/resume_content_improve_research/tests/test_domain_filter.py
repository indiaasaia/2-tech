"""Regression tests for the two-stage domain gate (generation/domain_filter.py
+ generation/scored_filter.py).

Invariants:
- stage 1: every family the user named keeps its jobs (software, AI/data,
  automation, hardware/IoT, finance incl. banking/trading/investment,
  tech-angle business);
- business roles survive ONLY with a tech/AI/software angle;
- stage 2 (scored): a family-less job is kept when >= 60% of its demanded
  skills are candidate-claimable, eliminated when clearly below;
- truly alien jobs (mechanical, health, hospitality, pure retail...) are
  eliminated at one stage or the other;
- JD boilerplate must not save an out-of-domain title;
- allowlist forces a keep; decisions carry a human-readable reason.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from resume_content_improve_research.generation import domain_filter as df
from resume_content_improve_research.generation.domain_filter import classify_job, load_filter_config

BUCKETS = load_filter_config()


def job(**over) -> dict:
    data = {
        "title": "Working Student",
        "company": "ACME",
        "job_url": "https://x/y",
        "job_description": "",
        "requirements": "",
        "your_tasks": "",
        "applicant_profile": "",
        "what_they_offer": "",
    }
    data.update(over)
    return data


def dec(**kw) -> dict:
    return classify_job(job(**kw), BUCKETS)


# ---------- families that must be KEPT ----------

def test_software_job_kept():
    r = dec(title="Software Engineering Intern / Working Student",
            your_tasks="Build web applications with Python and React.")
    assert r["decision"] == "keep"
    assert "software" in r["families_matched"]


def test_ai_job_kept():
    r = dec(title="Working Student: AI Engineer, Agentic Systems (m/f/d)",
            your_tasks="Develop LLM-based agents and machine learning pipelines.")
    assert r["decision"] == "keep"
    assert "ai_data" in r["families_matched"]


def test_automation_job_kept():
    r = dec(title="Working student automation (m/f/d) for ERS Europe",
            your_tasks="Support building automation and control systems.")
    assert r["decision"] == "keep"
    assert "automation" in r["families_matched"]


def test_hardware_iot_job_kept():
    r = dec(title="Internship - System Interaction with Eye Tracking and Robotics",
            your_tasks="Work with embedded sensors and robotics hardware.")
    assert r["decision"] == "keep"
    assert "hardware_iot" in r["families_matched"]


def test_finance_job_kept():
    r = dec(title="Finance Intern / Working Student",
            your_tasks="Support accounting, controlling and financial analysis.")
    assert r["decision"] == "keep"
    assert "finance" in r["families_matched"]


def test_trading_job_kept():
    r = dec(title="Working Student Trading & Markets",
            your_tasks="Analyze stock market data and support the trading desk.")
    assert r["decision"] == "keep"
    assert "finance" in r["families_matched"]


def test_business_with_ai_angle_kept():
    r = dec(title="Werkstudent Projektmanagement mit Schwerpunkt KI",
            your_tasks="Coordinate AI projects and support project management.")
    assert r["decision"] == "keep"
    assert "tech_business" in r["families_matched"]


def test_business_development_at_tech_company_kept():
    r = dec(title="Working Student / Intern - Business Development",
            job_description="We are a tech startup with a B2B SaaS product. "
                            "Support our sales operations and partnerships.")
    assert r["decision"] == "keep"


# ---------- jobs that must be ELIMINATED (stage 1 or stage 2) ----------

def test_mechanical_engineering_eliminated():
    r = dec(title="Internship Mechanical Engineering (m/f/d)",
            your_tasks="Support mechanical design and CAD construction of production machines "
                       "using SolidWorks, AutoCAD and MATLAB simulations.")
    assert r["decision"] == "eliminate"


def test_coating_chemistry_eliminated():
    r = dec(title="Internship coating development (f/m/x)",
            your_tasks="Develop coatings and paints in the laboratory; process automation support.")
    # one stray 'automation' word cannot save an other-domain title
    assert r["decision"] == "eliminate"


def test_healthcare_eliminated():
    r = dec(title="Nurse (m/f/d) for our hospital ward",
            your_tasks="Patient care, documentation.")
    assert r["decision"] == "eliminate"


def test_hospitality_eliminated():
    r = dec(title="Chef de Partie (m/w/d)",
            your_tasks="Leading a kitchen section, menu planning.")
    assert r["decision"] == "eliminate"


def test_pure_business_admin_eliminated():
    r = dec(title="Working Student Business Administration",
            your_tasks="Office organization, event planning, invoice processing, "
                       "filing and document management, phone support.")
    assert r["decision"] == "eliminate"


def test_boilerplate_cannot_save_out_of_domain_title():
    # 'startup', 'agile', 'feedback culture' boilerplate in the offer column
    r = dec(title="Praktikum Maschinenbau",
            what_they_offer="A modern startup environment, agile team, flat hierarchies.")
    assert r["decision"] == "eliminate"


# ---------- stage 2: scored skill alignment (the loose 60% net) ----------

def test_familyless_high_overlap_job_rescued_by_score():
    # no family keyword anywhere (no 'python', 'api', 'analytics', 'software'...),
    # but most demanded skills are candidate-claimable -> stage 2 rescues it
    r = dec(title="Working Student Technical Operations",
            requirements="You bring: mathematics, streamlit, css and "
                         "data preprocessing basics, plus ms office.")
    assert r["decision"] == "keep"
    assert r["score"] is not None
    assert r["score"]["alignment_ratio"] >= 0.60
    assert "alignment" in r["reason"]


def test_familyless_low_overlap_job_eliminated_by_score():
    # no family keyword, demands mostly unclaimable tools
    r = dec(title="Working Student Facility Management",
            requirements="You bring: HVAC basics, plumbing experience, autocad, "
                         "sharepoint and MS office.")
    assert r["decision"] == "eliminate"
    assert r["score"] is not None
    assert r["score"]["alignment_ratio"] < 0.60
    assert r["score"]["claimable"] == []


def test_scored_stage_reusable_directly():
    from resume_content_improve_research.generation.scored_filter import classify_scored
    verdict = classify_scored(job(
        title="Junior Consultant",
        requirements="Skills required: python programming, sql databases, "
                     "power bi dashboards, matlab."))
    assert verdict["decision"] == "keep"
    assert verdict["score"]["claimable"]


def test_few_demands_defaults_to_keep():
    # below min_denominator detectable demands: the loose net keeps the job
    verdict = df._load_scored_filter().classify_scored(
        job(title="Event Helper", your_tasks="Set up chairs and greet guests."))
    assert verdict["decision"] == "keep"


def test_industry_bonus_helps_but_never_decides_alone():
    # zero claimable skills: bonus caps at industry_cap and cannot reach 0.60
    r = dec(title="Working Student Office Management",
            company="Some Innovative Tech GmbH",
            job_description="We are a platform vendor with an app for our customers.",
            requirements="MS office, sharepoint, phone etiquette.")
    assert r["decision"] == "eliminate"
    assert r["score"]["industry_hits"]
    assert r["score"]["alignment_ratio"] < 0.60


def test_loose_mode_skips_scoring():
    r = classify_job(job(title="Working Student Facility Management",
                         requirements="HVAC, plumbing, autocad, sharepoint, ms office."),
                     BUCKETS, scored=False)
    assert r["decision"] == "eliminate"
    assert r["score"] is None


# ---------- edge behavior ----------

def test_needs_tech_business_alone_is_not_enough():
    # no direct tech term ('crm', 'erp', 'saas'...) and no claimable demand:
    # neither stage 1 (needs-tech) nor stage 2 (score) saves it
    r = dec(title="Working Student Sales (m/f/d)",
            your_tasks="Support key account management and customer success, "
                       "prepare offer letters and maintain spreadsheets.")
    assert r["decision"] == "eliminate"


def test_allowlist_forces_keep(monkeypatch):
    monkeypatch.setattr(df, "load_allowlist", lambda: ["special-case-url"])
    r = dec(title="Completely unrelated role", job_url="https://x/special-case-url-123")
    assert r["decision"] == "keep"
    assert r["reason"] == "allowlist match"


def test_reason_present_on_every_decision():
    for r in (dec(title="Data Analyst Working Student",
                  your_tasks="Build dashboards and analytics."),
              dec(title="Warehouse Worker", your_tasks="Load trucks.")):
        assert r["decision"] in ("keep", "eliminate")
        assert r["reason"]
