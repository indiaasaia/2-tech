from contact_discovery.config import Config
from contact_discovery.context import (
    build_context,
    format_previous_emails,
    render_main_prompt,
    render_repeat_prompt,
)
from contact_discovery.parsing import Contact


def test_render_main_prompt_fills_company():
    out = render_main_prompt("Research {{COMPANY_NAME}} deeply.", "Acme GmbH")
    assert "{{COMPANY_NAME}}" not in out
    assert out == "Research Acme GmbH deeply."


def test_render_repeat_prompt_fills_both_placeholders():
    out = render_repeat_prompt("{{COMPANY_NAME}}\n{{PREVIOUS_EMAILS}}", "Acme GmbH", "HR | hr@acme.de")
    assert out == "Acme GmbH\nHR | hr@acme.de"


def test_format_previous_emails_empty_and_filled():
    assert format_previous_emails([]) == "None found so far."
    out = format_previous_emails([Contact("HR", "hr@acme.de"), Contact("CTO", "cto@acme.de")])
    assert out == "HR | hr@acme.de\nCTO | cto@acme.de"


def test_build_context_iteration_1_uses_main_prompt(tmp_path):
    config = _config(tmp_path)
    ctx = build_context(config, {"company_name": "Acme GmbH"}, iteration=1, found=[])
    assert "Main prompt" in ctx["system_instruction"]
    assert "Acme GmbH" in ctx["system_instruction"]
    assert "{{COMPANY_NAME}}" not in ctx["system_instruction"]


def test_build_context_iteration_2_uses_repeat_prompt_with_previous_emails(tmp_path):
    config = _config(tmp_path)
    found = [Contact("HR", "hr@acme.de")]
    ctx = build_context(config, {"company_name": "Acme GmbH"}, iteration=2, found=found)
    assert "Repeat prompt" in ctx["system_instruction"]
    assert "hr@acme.de" in ctx["system_instruction"]
    assert "{{PREVIOUS_EMAILS}}" not in ctx["system_instruction"]


def test_missing_prompt_file_raises(tmp_path):
    config = _config(tmp_path)
    config = Config(**{**config.__dict__, "prompt_path": str(tmp_path / "missing.md")})
    try:
        build_context(config, {"company_name": "Acme"}, iteration=1, found=[])
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("expected FileNotFoundError")


def _config(tmp_path) -> Config:
    (tmp_path / "prompt.md").write_text("Main prompt for {{COMPANY_NAME}}", encoding="utf-8")
    (tmp_path / "repeat.md").write_text(
        "Repeat prompt for {{COMPANY_NAME}}\n{{PREVIOUS_EMAILS}}", encoding="utf-8"
    )
    return Config(
        api_key="",
        model="gemini-3.7-flash",
        companies_path=str(tmp_path / "companies.csv"),
        csv_path=str(tmp_path / "contacts.csv"),
        outcomes_path=str(tmp_path / "outcomes.csv"),
        prompt_path=str(tmp_path / "prompt.md"),
        repeat_prompt_path=str(tmp_path / "repeat.md"),
    )
