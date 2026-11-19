"""Regression tests for the real-world hardening fixes (post-21-job-run round).

Covers:
  - v1 placeholder-order bug (archived 5_create_resume.py): PROJECT-* before bare tokens
  - coverage matcher phrase-reality: "Python programming" vs "Python: ..." lines
  - parse_sim strict section titles (no 'experience.' prose false positives)
  - triage tiering + shortlist payload shape
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from resume_content_improve_research.verification.coverage import score_coverage
from resume_content_improve_research.verification.parse_sim import _is_section_title
from resume_content_improve_research.verification.triage import build_shortlist, tier_for


# ---------------------------------------------------------------------------
# v1 filler replacement-order regression (the shipped 21/21 PDF bug)
# ---------------------------------------------------------------------------
def _load_v1_fill_template():
    target = PROJECT_ROOT / "program_files" / "5_create_resume.py"
    if not target.exists():
        target = PROJECT_ROOT / "old_files" / "v1_resume_pipeline" / "5_create_resume.py"
    if not target.exists():
        pytest.skip("v1 create_resume.py not found")
    spec = importlib.util.spec_from_file_location("v1_create_resume", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestV1PlaceholderOrder:
    def test_project_skills_filled_before_skills(self):
        """The exact V4 bug: SKILLS-1 must not consume PROJECT-SKILLS-1."""
        module = _load_v1_fill_template()
        template = "row SKILLS-1 and PROJECT-SKILLS-1 end"
        components = {
            "objective": {"career_objective": "obj"},
            "experience": {
                "experience_1": {"role": "R1", "description": "D1", "skills": ["A"]},
                "experience_2": {"role": "R2", "description": "D2", "skills": ["B"]},
            },
            "projects": {
                "project_1": {"project": "P1", "description": "PD1", "skills": ["C"]},
                "project_2": {"project": "P2", "description": "PD2", "skills": ["D"]},
            },
            "skills": {"skills_section": {
                "languages": [], "specialized_areas": [],
                "skills_area_1": {"label": "L1", "skills": []},
                "skills_area_2": {"label": "L2", "skills": []},
            }},
        }
        filled = module.fill_template(template, components, {})
        assert "PROJECT-SKILLS-1" not in filled
        assert "C" in filled and "A" in filled  # both values survive
        assert "PROJECT-" not in filled

    def test_leaked_prefix_raises(self):
        """A generated value carrying PROJECT- fails the build (V4 killer assert)."""
        module = _load_v1_fill_template()
        template = "x DESCRIPTION-1 y"
        components = {
            "objective": {"career_objective": "obj"},
            "experience": {
                "experience_1": {"role": "R1", "description": "PROJECT-leak", "skills": []},
                "experience_2": {"role": "R2", "description": "D2", "skills": []},
            },
            "projects": {
                "project_1": {"project": "P1", "description": "PD1", "skills": []},
                "project_2": {"project": "P2", "description": "PD2", "skills": []},
            },
            "skills": {"skills_section": {
                "languages": [], "specialized_areas": [],
                "skills_area_1": {"label": "L1", "skills": []},
                "skills_area_2": {"label": "L2", "skills": []},
            }},
        }
        with pytest.raises(RuntimeError):
            module.fill_template(template, components, {})


# ---------------------------------------------------------------------------
# coverage phrase-reality
# ---------------------------------------------------------------------------
class TestCoveragePhraseReality:
    ARTIFACT = (
        "RAVAL MEETKUMAR\nravalmeett@gmail.com\nCareer Objective\n"
        "Backend developer with Python and REST API experience.\n"
        "Skills\n"
        "Programming Languages: Python, C++, SQL\n"
        "Tools: Docker, Git, Excel\n"
        "Languages\n"
        "English, Hindi, German (A2)\n"
    )

    def test_head_noun_stripped_match(self):
        """'Python programming' must match the 'Programming Languages: Python' line."""
        result = score_coverage(self.ARTIFACT, {"required": ["Python programming"]})
        assert result.required_score == 1.0
        assert result.matched["Python programming"] in ("alias", "fuzzy")

    def test_bare_skill_match(self):
        result = score_coverage(self.ARTIFACT, {"required": ["Docker", "Excel"]})
        assert result.required_score == 1.0

    def test_genuinely_missing_stays_missing(self):
        result = score_coverage(self.ARTIFACT, {"required": ["Kubernetes cluster design"]})
        assert result.required_score == 0.0
        assert result.required_missing == ["Kubernetes cluster design"]

    def test_connector_split_either_or(self):
        """'English and/or German' is either-or: English present -> covered."""
        result = score_coverage(self.ARTIFACT, {"required": ["English and/or German"]})
        assert result.required_score == 1.0

    def test_connector_split_no_language_present(self):
        """Neither side of the either-or present -> honestly missing."""
        result = score_coverage(
            "Skills\nProgramming Languages: Python\n",
            {"required": ["English and/or German"]})
        assert result.required_score == 0.0

    def test_soft_trait_is_ineligible(self):
        result = score_coverage(self.ARTIFACT, {"required": ["fast learner", "Docker"]})
        assert result.required_score == 1.0
        assert result.ineligible == ["fast learner"]

    def test_real_miss_is_not_rescued_by_filler_strip(self):
        """Stripping must never fabricate: 'database schema design' vs SQL stays missing."""
        result = score_coverage(self.ARTIFACT, {"required": ["database schema design"]})
        assert result.required_score == 0.0


# ---------------------------------------------------------------------------
# parse_sim strict section titles
# ---------------------------------------------------------------------------
class TestSectionTitles:
    @pytest.mark.parametrize("line,expected", [
        ("Experience", True),
        ("EXPERIENCE", True),
        ("Main Projects", True),
        ("MAIN PROJECTS", True),
        ("Career Objective", True),
        ("Research and Publications", True),
        ("Additional Projects", True),
        ("Skills and experience.", False),
        ("data-driven experience.", False),
        ("experience.", False),
        ("Tools: Airflow, Excel", False),
        ("Skills: Python, SQL, quant models", False),
        ("Built scalable data pipelines for the analytics platform", False),
        ("Languages", True),
    ])
    def test_classification(self, line, expected):
        assert _is_section_title(line) is expected


# ---------------------------------------------------------------------------
# triage
# ---------------------------------------------------------------------------
class TestTriage:
    def _record(self, score, status="verified"):
        return {
            "status": status, "score": score, "title": f"Job {score}",
            "company": "C", "job_url": f"u{score}", "required_coverage": 1.0,
            "preferred_coverage": 0.5, "gap_report": {"missing_required": ["X"], "missing_preferred": []},
            "pdf": "p.pdf", "docx": "d.docx",
        }

    def test_tiers(self):
        assert tier_for(90) == "strong"
        assert tier_for(80) == "strong"
        assert tier_for(70) == "good"
        assert tier_for(50) == "weak"
        assert tier_for(28) == "poor"
        assert tier_for(None) == "poor"

    def test_shortlist_sorts_and_excludes_unverified(self):
        payload = build_shortlist([self._record(40), self._record(93), self._record(None, status="parked")])
        assert [j["score"] for j in payload["jobs"]] == [93, 40]
        assert payload["counts"]["strong"] == 1
        assert payload["counts"]["poor"] == 1
        assert payload["jobs"][0]["top_gaps"] == ["X"]

    def test_empty(self):
        payload = build_shortlist([])
        assert payload["jobs"] == [] and payload["counts"]["verified"] == 0
