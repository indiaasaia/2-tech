"""Gemini client wrapper (Interactions API) + a deterministic fake client
for tests and --dry-run.

The wrapper is deliberately thin: it builds the request and returns the
raw output text. All parsing/validation lives in validation.py, so the
client is easy to replace or mock.
"""
from __future__ import annotations

import json
import os
from typing import Protocol


def _record_usage(model: str) -> None:
    """Append one usage record when GEMINI_USAGE_FILE is set (campaign quota
    tracking). Never raises: tracking must never break a live run."""
    path = os.environ.get("GEMINI_USAGE_FILE")
    if not path:
        return
    from datetime import datetime, timezone

    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "phase": "phase1",
                "model": model,
                "ok": True,
            }) + "\n")
    except Exception:
        pass

from .schema import DiscoveryResponse


class DiscoveryClient(Protocol):
    """Anything with a discover() method returning raw model text."""

    def discover(self, system_instruction: str, user_content: str, temperature: float = 0.2) -> str: ...


class GeminiClient:
    """Real client using the current recommended Interactions API.

    Uses stateless mode (store=False): the application owns all state via
    the CSV, so nothing is retained server-side.
    """

    def __init__(self, api_key: str, model: str = "gemini-3.6-flash"):
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set — export it before running.")
        from google import genai  # lazy import: only needed for live runs

        self._client = genai.Client(api_key=api_key)
        self._model = model

    def discover(self, system_instruction: str, user_content: str, temperature: float = 0.2) -> str:
        interaction = self._client.interactions.create(
            model=self._model,
            system_instruction=system_instruction,
            input=user_content,
            store=False,
            generation_config={"temperature": temperature},
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": DiscoveryResponse.model_json_schema(),
            },
        )
        _record_usage(self._model)
        return interaction.output_text


class FakeGeminiClient:
    """Deterministic stand-in that simulates Gemini for tests and dry runs.

    Serves companies from a fixed pool in slices of `batch_size`. From the
    second batch on, the first slot is replaced with a near-duplicate of a
    previously served company (same website, slightly different name) so
    the dedup path is exercised. When the pool is exhausted, it returns an
    empty list.
    """

    def __init__(self, pool: list[dict], batch_size: int):
        self._pool = list(pool)
        self._batch_size = batch_size
        self._index = 0
        self._served: list[dict] = []

    def discover(self, system_instruction: str, user_content: str, temperature: float = 0.2) -> str:
        chunk = self._pool[self._index : self._index + self._batch_size]
        self._index += self._batch_size
        companies = []
        for i, entry in enumerate(chunk):
            candidate = dict(entry)
            if i == 0 and self._served:
                prev = self._served[-1]
                candidate["company_name"] = f"{prev['company_name']} Technologies"
                candidate["website"] = prev["website"]
            companies.append(candidate)
        self._served.extend(companies)
        return json.dumps({"companies": companies, "notes": "simulated response (dry run)"})
