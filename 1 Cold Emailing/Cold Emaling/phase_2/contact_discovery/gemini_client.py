"""Gemini client wrapper (Interactions API) + a deterministic fake client
for tests and --dry-run.

The wrapper is deliberately thin: it builds the request and returns the
raw output text. All parsing/validation lives in parsing.py, so the
client is easy to replace or mock.

Model fallback: a chain of models is tried in order. When the primary
model hits a rate limit / quota / transient outage (retryable errors),
the next model in the chain is used automatically. Hard errors (bad
request, blocked content, invalid key) fail fast — they will not help by
switching models.
"""
from __future__ import annotations

import json
import os
import re
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
                "phase": "phase2",
                "model": model,
                "ok": True,
            }) + "\n")
    except Exception:
        pass

from .parsing import SENTINEL_NO_NEW

# HTTP codes that mean "try another model" — rate limits, quota,
# timeouts and transient server/overload conditions.
_RETRYABLE_CODES = frozenset({408, 429, 500, 502, 503, 504, 529})

# gRPC status strings that mean the same thing, when the HTTP code alone
# is not conclusive.
_RETRYABLE_STATUSES = frozenset({
    "RESOURCE_EXHAUSTED", "RATE_LIMIT_EXCEEDED", "UNAVAILABLE",
    "DEADLINE_EXCEEDED", "ABORTED", "INTERNAL",
})


def is_retryable(exc: Exception) -> bool:
    """True when the error is a transient/limit condition worth retrying on
    another model; False for hard failures.

    Handles both SDK error shapes: the genai ``errors.APIError`` exposes
    ``.code`` while the GAOS compat ``APIError`` exposes ``.status_code``.
    """
    code = getattr(exc, "code", None)
    if code is None:
        code = getattr(exc, "status_code", None)
    status = getattr(exc, "status", None)
    if code in _RETRYABLE_CODES:
        return True
    if status and str(status).upper() in _RETRYABLE_STATUSES:
        return True
    return False


def discover_with_fallback(call_model, models: list[str], temperature: float) -> str:
    """Try each model in order; fall through only on retryable errors.

    ``call_model(model)`` performs one API call and returns the raw text.
    Raises the last error when every model fails, and propagates hard
    errors immediately.
    """
    last_error: Exception | None = None
    for index, model in enumerate(models):
        try:
            return call_model(model)
        except Exception as exc:
            last_error = exc
            if not is_retryable(exc) or index == len(models) - 1:
                raise
    raise last_error  # pragma: no cover — loop above always raises or returns


class DiscoveryClient(Protocol):
    """Anything with a discover() method returning raw model text."""

    def discover(self, system_instruction: str, user_content: str, temperature: float = 0.2) -> str: ...


class GeminiClient:
    """Real client using the current recommended Interactions API.

    Uses stateless mode (store=False): the application owns all state via
    the CSVs, so nothing is retained server-side. The output is plain
    text (Name | Email lines), not JSON.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.7-flash",
        fallback_models: tuple[str, ...] = ("gemini-3.6-flash", "gemini-3.5-flash"),
    ):
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set — export it before running.")
        from google import genai  # lazy import: only needed for live runs

        self._client = genai.Client(api_key=api_key)
        self._models = [model, *fallback_models]
        self.last_model: str | None = None  # which model actually served the last call

    def _call(self, model: str, system_instruction: str, user_content: str, temperature: float) -> str:
        interaction = self._client.interactions.create(
            model=model,
            system_instruction=system_instruction,
            input=user_content,
            store=False,
            generation_config={"temperature": temperature},
        )
        _record_usage(model)
        return interaction.output_text

    def discover(self, system_instruction: str, user_content: str, temperature: float = 0.2) -> str:
        used: list[str] = []

        def call_model(model: str) -> str:
            text = self._call(model, system_instruction, user_content, temperature)
            used.append(model)  # only reached on success
            return text

        text = discover_with_fallback(call_model, self._models, temperature)
        self.last_model = used[-1] if used else None
        return text


# Matches "Company: <name>" / "same company: <name>" in either prompt,
# so the fake client can echo the company it is being asked about.
_COMPANY_RE = re.compile(r"company:\s*\n\s*`?([^`\n]+)`?", flags=re.IGNORECASE)


class FakeGeminiClient:
    """Deterministic stand-in that simulates Gemini for tests and dry runs.

    For every company it serves the same research arc:
    iteration 1 -> HR + Recruiting emails
    iteration 2 -> CTO email (new)
    iteration 3 -> NO_NEW_PUBLIC_EMAIL_FOUND (saturation signal)
    """

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def discover(self, system_instruction: str, user_content: str, temperature: float = 0.2) -> str:
        self.calls.append((system_instruction, user_content))
        company = _COMPANY_RE.search(system_instruction)
        name = company.group(1).strip() if company else "example"
        slug = re.sub(r"[^a-z0-9]+", "", name.lower()) or "example"
        if "REPEAT EMAIL DISCOVERY" in system_instruction:
            # Iteration 2: one new contact; iteration 3: saturation.
            if "cto@" in system_instruction.lower():
                return SENTINEL_NO_NEW
            return f"CTO | cto@{slug}.de"
        # Iteration 1: the two strongest role emails.
        return f"HR Team | hr@{slug}.de\nRecruiting Team | recruiting@{slug}.de"
