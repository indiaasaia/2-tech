"""Unit tests for the collision-proof template filler (V4 regression class)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from resume_content_improve_research import config
from resume_content_improve_research.templates.fill import clean_text, escape_latex, fill_template, join_items


class TestEscapeLatex:
    def test_specials(self):
        assert escape_latex("50% of R&D") == r"50\% of R\&D"
        assert escape_latex("a_b") == r"a\_b"
        assert escape_latex("cost $5") == r"cost \$5"

    def test_unicode_normalization(self):
        assert clean_text("data\u2013driven") == "data-driven"
        assert clean_text("\ufb01ne") == "fine"


class TestFillTemplate:
    def make_values(self) -> dict[str, str]:
        # API contract: keys are the full @@NAME@@ token strings (config.TOKENS
        # maps logical name -> @@NAME@@, and fill_template reads values[token]).
        return {token: escape_latex(f"value for {token.strip('@')}") for token in config.TOKENS.values()}

    def test_all_tokens_filled(self):
        template = " ".join(config.ALL_TOKENS)
        filled = fill_template(template, self.make_values())
        for token in config.ALL_TOKENS:
            assert token not in filled

    def test_missing_value_raises(self):
        template = config.ALL_TOKENS[0]
        with pytest.raises(RuntimeError):
            fill_template(template, {})

    def test_legacy_collision_style_asserted(self):
        """A GENERATED value carrying the legacy PROJECT- prefix must fail the build."""
        values = self.make_values()
        values["@@DESCRIPTION_1@@"] = "PROJECT-something leaked"
        with pytest.raises(RuntimeError):
            fill_template("x @@DESCRIPTION_1@@ y", values)

    def test_legacy_prefix_from_llm_not_escaped_around(self):
        """escape_latex must not hide the legacy prefix from the assert (no _ in it)."""
        values = self.make_values()
        values["@@SKILLS_1@@"] = "PROJECT-fake skill"
        with pytest.raises(RuntimeError):
            fill_template("x @@SKILLS_1@@ y", values)

    def test_prefix_tokens_not_swallowed(self):
        """The exact V4 bug: SKILLS-1 inside PROJECT-SKILLS-1 must not collide."""
        values = self.make_values()
        values["@@SKILLS_1@@"] = "A, B"
        values["@@PROJECT_SKILLS_1@@"] = "C, D"
        template = "row @@SKILLS_1@@ then @@PROJECT_SKILLS_1@@"
        filled = fill_template(template, values)
        assert "A, B" in filled and "C, D" in filled
        assert "@@" not in filled

    def test_unescaped_specials_rejected(self):
        """The filler never escapes: raw '&' must fail loud (double-escape guard)."""
        values = self.make_values()
        values["@@SKILLS_1@@"] = "R&D raw"  # NOT escaped
        with pytest.raises(RuntimeError, match="unescaped LaTeX specials"):
            fill_template("x @@SKILLS_1@@ y", values)

    def test_value_containing_token_string_is_still_filled(self):
        """A value that embeds another token string must not resurrect a token."""
        values = self.make_values()
        values["@@DESCRIPTION_1@@"] = "see @@SKILLS_1@@ inside"
        template = "x @@DESCRIPTION_1@@ y @@SKILLS_1@@ z"
        filled = fill_template(template, values)
        assert "@@" not in filled

    def test_join_items_escapes(self):
        # '+' is LaTeX-safe, so c++ passes through unescaped (LaTeX-mode output)
        assert join_items(["python", "c++", "50%"]) == "python, c++, 50\\%"
