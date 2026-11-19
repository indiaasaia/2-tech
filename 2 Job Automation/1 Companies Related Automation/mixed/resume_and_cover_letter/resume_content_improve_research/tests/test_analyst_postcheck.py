"""Unit tests for the deterministic analyst post-check (no LLM)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from resume_content_improve_research.generation.analyst import JDAnalysis
from resume_content_improve_research.generation.analyst_postcheck import postcheck


class TestLanguageSweep:
    def test_missed_german_is_force_inserted(self):
        analysis = JDAnalysis(languages_required=[])
        jd = "We seek a developer with Python skills. Ideally english and german."
        fixes = postcheck(analysis, jd)
        languages = {e.language for e in analysis.languages_required}
        assert "German" in languages, fixes
        assert any("German" in f for f in fixes)

    def test_explicit_level_is_parsed(self):
        analysis = JDAnalysis(languages_required=[])
        postcheck(analysis, "German at B2 level is required for this role")
        german = next(e for e in analysis.languages_required if e.language == "German")
        assert german.level == "B2"

    def test_no_language_mention_no_insertion(self):
        analysis = JDAnalysis(languages_required=[])
        postcheck(analysis, "Pure Python backend work with docker")
        assert analysis.languages_required == []

    def test_existing_language_not_duplicated(self):
        from resume_content_improve_research.generation.analyst import LanguageRequirement

        analysis = JDAnalysis(languages_required=[LanguageRequirement(language="German", level="B2")])
        postcheck(analysis, "German fluent required")
        assert len([e for e in analysis.languages_required if e.language == "German"]) == 1


class TestGermanDetection:
    def test_german_jd_detected_by_heuristic(self):
        analysis = JDAnalysis(language="en")
        postcheck(analysis, "Wir suchen einen Entwickler für Backend-Systeme mit Python und Docker")
        assert analysis.language == "de"


class TestTierEnforcement:
    def test_overlong_required_item_dropped(self):
        analysis = JDAnalysis(
            required=["experience in building scalable distributed backend systems with python"],
            tools=["python"],
        )
        fixes = postcheck(analysis, "python backend role")
        assert analysis.required == []
        assert any("over-long" in f for f in fixes)

    def test_duplicates_removed(self):
        analysis = JDAnalysis(required=["python", "Python "], tools=[])
        fixes = postcheck(analysis, "python")
        assert len(analysis.required) == 1

    def test_single_tool_in_required_collapses_into_tools(self):
        analysis = JDAnalysis(required=["docker"], tools=["docker"])
        fixes = postcheck(analysis, "docker role")
        assert "docker" not in [r.lower() for r in analysis.required]
