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

    def test_ff_break_is_a_real_group_not_escaped_braces(self):
        """Regression 2026-10-17: the ff-break ran before brace escaping and printed
        'Traf{}fic' / 'MS Of{}fice' literally in the PDF."""
        assert escape_latex("Space Traffic Management") == "Space Traf{}fic Management"
        assert escape_latex("MS Office") == "MS Of{}fice"
        assert escape_latex("{x}") == r"\{x\}"

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
        values["@@EXPERIENCE@@"] = "PROJECT-something leaked"
        with pytest.raises(RuntimeError):
            fill_template("x @@EXPERIENCE@@ y", values)

    def test_legacy_prefix_from_llm_not_escaped_around(self):
        """escape_latex must not hide the legacy prefix from the assert (no _ in it)."""
        values = self.make_values()
        values["@@SKILLS_ROWS@@"] = "PROJECT-fake skill"
        with pytest.raises(RuntimeError):
            fill_template("x @@SKILLS_ROWS@@ y", values)

    def test_prefix_tokens_not_swallowed(self):
        """The V4 bug class: a token name inside a longer one (PROJECTS / ADDITIONAL_PROJECTS)."""
        values = self.make_values()
        values["@@PROJECTS@@"] = "A, B"
        values["@@ADDITIONAL_PROJECTS@@"] = "C, D"
        template = "row @@PROJECTS@@ then @@ADDITIONAL_PROJECTS@@"
        filled = fill_template(template, values)
        assert "A, B" in filled and "C, D" in filled
        assert "@@" not in filled

    def test_unescaped_specials_rejected(self):
        """The filler never escapes: raw '&' must fail loud (double-escape guard)."""
        values = self.make_values()
        values["@@PROFILE@@"] = "R&D raw"  # NOT escaped
        with pytest.raises(RuntimeError, match="unescaped LaTeX specials"):
            fill_template("x @@PROFILE@@ y", values)

    def test_value_containing_token_string_is_still_filled(self):
        """A value that embeds another token string must not resurrect a token."""
        values = self.make_values()
        values["@@EXPERIENCE@@"] = "see @@PROFILE@@ inside"
        template = "x @@EXPERIENCE@@ y @@PROFILE@@ z"
        filled = fill_template(template, values)
        assert "@@" not in filled

    def test_join_items_escapes(self):
        # '+' is LaTeX-safe, so c++ passes through unescaped (LaTeX-mode output)
        assert join_items(["python", "c++", "50%"]) == "python, c++, 50\\%"
