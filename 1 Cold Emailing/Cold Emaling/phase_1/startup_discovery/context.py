"""Builds the per-request context sent to Gemini.

The context is deliberately NOT the conversation history. Each run gets:
  1. The research instructions (prompt template with placeholders filled).
  2. A task block: batch number, progress counts, and the compact
     exclusion list (already-discovered companies).

Everything the model needs for the current step is rebuilt from the CSV
before every request, so nothing depends on Gemini's server-side memory.
"""
from __future__ import annotations

from pathlib import Path

from .config import Config


def load_prompt_template(path: str | Path) -> str:
    template_path = Path(path)
    if not template_path.exists():
        raise FileNotFoundError(f"prompt template not found: {template_path}")
    return template_path.read_text(encoding="utf-8")


def format_cities(cities) -> str:
    """Human-readable list: 'Berlin', or 'Berlin, Munich and Hamburg'."""
    cities = [c for c in (cities or ()) if c and str(c).strip()]
    if not cities:
        return "the target cities"
    cities = [str(c).strip() for c in cities]
    if len(cities) == 1:
        return cities[0]
    return ", ".join(cities[:-1]) + " and " + cities[-1]


def render_prompt(template: str, batch_size: int, total_cap: int, cities=("Berlin",)) -> str:
    return (
        template.replace("{target_count}", str(batch_size))
        .replace("{total_cap}", str(total_cap))
        .replace("{{CITIES}}", format_cities(cities))
    )


def build_exclusion_list(records: list[dict], max_entries: int | None = None) -> str:
    if not records:
        return "No companies have been discovered yet — this is the first batch."
    lines = []
    for i, record in enumerate(records[:max_entries], start=1):
        name = str(record.get("company_name") or "?")
        website = str(record.get("website") or "")
        lines.append(f"{i}. {name}{f' ({website})' if website else ''}")
    if max_entries is not None and len(records) > max_entries:
        lines.append(f"... and {len(records) - max_entries} more companies (the full list is maintained by the application).")
    return "\n".join(lines)


def build_task_block(
    batch_number: int,
    records: list[dict],
    batch_size: int,
    total_cap: int,
    max_exclusion_entries: int | None,
) -> str:
    total_found = len(records)
    remaining = max(0, total_cap - total_found)
    if batch_number == 1:
        instruction = (
            f"This is batch 1 of a discovery campaign. Target: {total_cap} companies total, "
            f"{batch_size} per batch. Return up to {batch_size} companies that are NOT already "
            f"in the exclusion list below. Quality over quantity: returning fewer than "
            f"{batch_size} is fine; returning an empty list is fine if no new qualifying "
            f"companies exist."
        )
    else:
        instruction = (
            f"This is batch {batch_number}. Companies discovered so far: {total_found} "
            f"(target: {total_cap}; {remaining} still needed). Research more. Do not make any "
            f"single mistake. Do not duplicate any company from the exclusion list below — check "
            f"exact names, alternative spellings, brand names vs legal names, renamed companies, "
            f"and subsidiaries. Return up to {batch_size} NEW companies. Returning fewer or an "
            f"empty list is acceptable if you cannot find new qualifying companies — never pad "
            f"with duplicates or weak matches."
        )
    exclusion = build_exclusion_list(records, max_entries=max_exclusion_entries)
    return f"{instruction}\n\nALREADY-DISCOVERED COMPANIES (ABSOLUTE EXCLUSION LIST):\n{exclusion}"


def build_context(config: Config, batch_number: int, records: list[dict]) -> dict[str, str]:
    """Return {'system_instruction': ..., 'user_content': ...} for one run."""
    template = load_prompt_template(config.prompt_path)
    system_instruction = render_prompt(template, config.batch_size, config.total_cap, config.cities)
    user_content = build_task_block(
        batch_number,
        records,
        config.batch_size,
        config.total_cap,
        config.max_exclusion_entries,
    )
    return {"system_instruction": system_instruction, "user_content": user_content}
