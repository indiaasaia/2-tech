"""Test-suite safety net: no test may reach the real LLM.

A real call would hit the network with the user's own Ollama keys and make the
suite slow and nondeterministic (found 2026-10-17: once the letter path called
the LLM again, an unmocked test made a live request). Every module that imports
`call_llm` gets a stub that fails immediately; a test that needs model output
installs its own fake with monkeypatch, which overrides this autouse stub.
"""
from __future__ import annotations

import pytest

from resume_content_improve_research.generation import analyst, cover_letter, generator, llm


def _blocked(*_args, **_kwargs):
    raise llm.LLMError("live LLM calls are disabled in tests - mock call_llm explicitly")


@pytest.fixture(autouse=True)
def _no_live_llm(monkeypatch):
    for module in (llm, analyst, cover_letter, generator):
        monkeypatch.setattr(module, "call_llm", _blocked)
