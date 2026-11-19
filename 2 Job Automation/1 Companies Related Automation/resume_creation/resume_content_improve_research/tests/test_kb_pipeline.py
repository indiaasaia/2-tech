"""Unit tests for KB loading, the claimable set, and coverage scoring (no LLM)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from resume_content_improve_research.generation import kb_loader
from resume_content_improve_research.generation.claimable_set import build_claimable_set
from resume_content_improve_research.generation.normalize import normalize_all, normalize_skill
from resume_content_improve_research.verification.coverage import score_coverage


@pytest.fixture(scope="module")
def kb() -> dict:
    return kb_loader.load_kb()


class TestKB:
    def test_loads_and_is_approved(self, kb):
        assert kb["status"] == "APPROVED"

    def test_25_global_skills(self, kb):
        assert len(kb_loader.global_skill_names(kb)) == 25

    def test_main_projects_are_the_three_real_ones(self, kb):
        titles = {p["title"] for p in kb_loader.main_projects(kb)}
        assert titles == {"High Frequency Trading Platform", "Automated Resume Generation",
                          "Vehicle Sharing Application"}

    def test_licensed_digits_include_confirmed_metrics(self, kb):
        digits = kb_loader.licensed_digits(kb)
        assert "70" in digits and "40" in digits and "24" in digits
        assert "35" not in digits


class TestNormalize:
    def test_alias_resolution(self):
        assert normalize_skill("k8s") == "Kubernetes"
        assert normalize_skill("py") == "Python"

    def test_normalize_all_dedupes(self):
        assert normalize_all(["Python", "python3", "py"]) == ["Python"]


class TestClaimableSet:
    def test_mirrorable_tools_exclude_kb_skills(self, kb):
        analysis = {"tools": ["Python", "Kubernetes", "Tableau"], "required": [], "preferred": []}
        cset = build_claimable_set(analysis, kb)
        assert "Python" not in cset.jd_tools      # KB skill -> ownable
        assert "Kubernetes" in cset.jd_tools      # mirrorable only
        assert "python" in cset.ownable()
        assert "kubernetes" in cset.mentionable()

    def test_per_entry_pools(self, kb):
        analysis = {"tools": [], "required": [], "preferred": []}
        cset = build_claimable_set(analysis, kb)
        assert "python" in {s.lower() for s in cset.per_experience["soham"]}
        assert "mysql" not in {s.lower() for s in cset.per_experience["soham"]}  # forbidden there


class TestCoverage:
    def test_exact_and_fuzzy(self):
        text = "Experienced in Python, SQL and django. Targeting Kubernetes exposure."
        analysis = {"required": ["Python", "Django", "Kubernetes"], "preferred": ["Airflow"]}
        result = score_coverage(text, analysis)
        assert result.required_score == 1.0
        assert "Airflow" in result.preferred_missing

    def test_alias_matching(self):
        result = score_coverage("built with py and mongo", {"required": ["Python", "MongoDB"]})
        assert result.required_score == 1.0
        assert set(result.matched.values()) <= {"exact", "alias", "fuzzy"}

    def test_empty_requirements_scores_full(self):
        result = score_coverage("anything", {"required": [], "preferred": []})
        assert result.required_score == 1.0
