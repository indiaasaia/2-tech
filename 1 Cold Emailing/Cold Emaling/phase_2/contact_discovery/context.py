"""Builds the per-request context sent to Gemini.

Mirrors Phase 1: the context is NOT conversation history. Everything the
model needs is rebuilt from disk before every request:

- Iteration 1 uses the main research prompt with ``{{COMPANY_NAME}}`` filled.
- Iterations 2+ use the repeat prompt with ``{{COMPANY_NAME}}`` and
  ``{{PREVIOUS_EMAILS}}`` (all contacts found so far) filled — the
  per-company exclusion list that forces later passes to dig for NEW
  emails only.
"""
from __future__ import annotations

from pathlib import Path

from .config import Config
from .parsing import Contact

PLACEHOLDER_COMPANY = "{{COMPANY_NAME}}"
PLACEHOLDER_PREVIOUS = "{{PREVIOUS_EMAILS}}"


def load_prompt_template(path: str | Path) -> str:
    template_path = Path(path)
    if not template_path.exists():
        raise FileNotFoundError(f"prompt template not found: {template_path}")
    return template_path.read_text(encoding="utf-8")


def render_main_prompt(template: str, company_name: str) -> str:
    return template.replace(PLACEHOLDER_COMPANY, company_name)


def render_repeat_prompt(template: str, company_name: str, previous_emails: str) -> str:
    return (
        template.replace(PLACEHOLDER_COMPANY, company_name)
        .replace(PLACEHOLDER_PREVIOUS, previous_emails)
    )


def format_previous_emails(contacts: list[Contact]) -> str:
    """The per-company exclusion list: every email found so far, as lines."""
    if not contacts:
        return "None found so far."
    return "\n".join(f"{contact.name} | {contact.email}" for contact in contacts)


def build_context(
    config: Config,
    company: dict,
    iteration: int,
    found: list[Contact],
) -> dict[str, str]:
    """Return {'system_instruction': ..., 'user_content': ...} for one run."""
    company_name = str(company.get("company_name") or "?")
    if iteration <= 1:
        template = load_prompt_template(config.prompt_path)
        system_instruction = render_main_prompt(template, company_name)
        user_content = f"Begin the research described above for {company_name}."
    else:
        template = load_prompt_template(config.repeat_prompt_path)
        previous = format_previous_emails(found)
        system_instruction = render_repeat_prompt(template, company_name, previous)
        user_content = f"Continue research for {company_name}, finding only NEW emails."
    return {"system_instruction": system_instruction, "user_content": user_content}
