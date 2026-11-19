import pytest

from startup_discovery.config import Config
from startup_discovery.context import (
    build_context,
    build_exclusion_list,
    build_task_block,
    load_prompt_template,
    render_prompt,
)


@pytest.fixture
def config(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text(
        "Return exactly {target_count} companies. Campaign cap: {total_cap}.",
        encoding="utf-8",
    )
    return Config(
        prompt_path=str(prompt),
        batch_size=5,
        total_cap=50,
        csv_path=str(tmp_path / "c.csv"),
    )


def test_render_prompt_fills_placeholders(config):
    template = load_prompt_template(config.prompt_path)
    rendered = render_prompt(template, batch_size=5, total_cap=50)
    assert "Return exactly 5 companies" in rendered
    assert "{target_count}" not in rendered
    assert "{total_cap}" not in rendered


def test_missing_template_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_prompt_template(tmp_path / "missing.md")


def test_exclusion_list_formats_records():
    records = [
        {"company_name": "Acme GmbH", "website": "https://acme.com"},
        {"company_name": "Beta", "website": "https://beta.de"},
    ]
    text = build_exclusion_list(records)
    assert "Acme GmbH (https://acme.com)" in text
    assert "Beta (https://beta.de)" in text


def test_exclusion_list_empty_first_batch():
    assert "first batch" in build_exclusion_list([])


def test_exclusion_list_respects_max_entries():
    records = [{"company_name": f"Co {i}", "website": f"https://co{i}.com"} for i in range(5)]
    text = build_exclusion_list(records, max_entries=3)
    assert "Co 0" in text
    assert "Co 2" in text
    assert "Co 3" not in text
    assert "2 more" in text


def test_task_block_first_batch():
    text = build_task_block(batch_number=1, records=[], batch_size=5, total_cap=50, max_exclusion_entries=None)
    assert "batch 1" in text
    assert "first batch" in text


def test_task_block_repeat_batch_lists_exclusions():
    records = [{"company_name": "Acme GmbH", "website": "https://acme.com"}]
    text = build_task_block(batch_number=3, records=records, batch_size=5, total_cap=50, max_exclusion_entries=None)
    assert "batch 3" in text
    assert "Companies discovered so far: 1" in text
    assert "49 still needed" in text
    assert "Acme GmbH (https://acme.com)" in text
    assert "Do not duplicate" in text


def test_build_context_first_batch(config):
    ctx = build_context(config, batch_number=1, records=[])
    assert "Return exactly 5 companies" in ctx["system_instruction"]
    assert "batch 1" in ctx["user_content"]
    assert "first batch" in ctx["user_content"]


def test_build_context_repeat_batch(config):
    records = [{"company_name": "Acme GmbH", "website": "https://acme.com"}]
    ctx = build_context(config, batch_number=2, records=records)
    assert "batch 2" in ctx["user_content"]
    assert "Acme GmbH (https://acme.com)" in ctx["user_content"]
    assert "Companies discovered so far: 1" in ctx["user_content"]
