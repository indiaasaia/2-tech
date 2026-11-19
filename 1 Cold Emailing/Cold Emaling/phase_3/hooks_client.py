"""
hooks_client.py — thin Gemini client for per-company hook generation.

Follows the same contract as the Phase 2 contact-discovery client
(``discover(system_instruction, user_content, temperature) -> str``) and
adds the Streamlit app's key-rotation behaviour: every API key is tried in
order and, on any failure, the next key takes over automatically.

Within one key, the model fallback chain applies (rate limit / quota /
transient outage -> next model); hard errors (bad request, blocked content,
invalid key) fail fast and let the key rotation move on. Standalone on
purpose (no cross-phase imports), so phase_3 scripts stay self-contained.

The fake client exists for --dry-run and tests — it never touches the API.
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
                "phase": "hooks",
                "model": model,
                "ok": True,
            }) + "\n")
    except Exception:
        pass

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
    """True on transient/limit conditions worth retrying on another model;
    False for hard failures (bad request, invalid key, blocked content).

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


def _call_with_fallback(call_model, models: list[str]) -> str:
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


class HookClient(Protocol):
    """Anything with a discover() method returning raw model text."""

    def discover(self, system_instruction: str, user_content: str, temperature: float = 0.7) -> str: ...


# Per-call HTTP timeout (ms): a stalled call fails instead of hanging the run.
_CALL_TIMEOUT_MS = 120_000


class GeminiClient:
    """Real client using the Interactions API (stateless, store=False)."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.7-flash",
        fallback_models: tuple[str, ...] = ("gemini-3.6-flash", "gemini-3.5-flash"),
    ):
        if not api_key:
            raise ValueError("Gemini API key is empty — nothing to call.")
        from google import genai  # lazy import: only needed for live runs

        try:
            self._client = genai.Client(
                api_key=api_key,
                http_options={"timeout": _CALL_TIMEOUT_MS},
            )
        except TypeError:
            # Older google-genai: http_options not supported — rely on defaults.
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

    def discover(self, system_instruction: str, user_content: str, temperature: float = 0.7) -> str:
        used: list[str] = []

        def call_model(model: str) -> str:
            text = self._call(model, system_instruction, user_content, temperature)
            used.append(model)  # only reached on success
            return text

        text = _call_with_fallback(call_model, self._models)
        self.last_model = used[-1] if used else None
        return text


class RotatingGeminiHooks:
    """Tries every key in order; rotates to the next key on ANY failure.

    ``keys`` is a list of records: ``{"label": str, "value": str}``.
    Which key and model served each call is stored on the instance so the
    generator can log it (a run's log doubles as an audit of key usage).
    """

    def __init__(
        self,
        keys: list[dict[str, str]],
        model: str = "gemini-3.7-flash",
        fallback_models: tuple[str, ...] = ("gemini-3.6-flash", "gemini-3.5-flash"),
        log_fn=print,
    ):
        self._keys = keys
        self._model = model
        self._fallback_models = fallback_models
        self._log = log_fn
        self.last_key: str | None = None
        self.last_model: str | None = None

    def discover(self, system_instruction: str, user_content: str, temperature: float = 0.7) -> str:
        if not self._keys:
            raise RuntimeError(
                "No Gemini API keys found. Edit gemini_keys.json at the project root "
                "(or set GEMINI_API_KEYS / GEMINI_API_KEY + GEMINI_API_KEY_2, or add "
                "enabled Gemini keys in streamlit_app/settings.json)."
            )
        last_error: Exception | None = None
        for record in self._keys:
            label = str(record.get("label") or record["value"][:8])
            try:
                client = GeminiClient(
                    api_key=record["value"],
                    model=self._model,
                    fallback_models=self._fallback_models,
                )
                text = client.discover(system_instruction, user_content, temperature)
                self.last_key = label
                self.last_model = client.last_model
                return text
            except Exception as exc:
                last_error = exc
                self._log(
                    f"[keys] '{label}' failed ({type(exc).__name__}: {exc}); "
                    f"trying the next key"
                )
        raise last_error  # type: ignore[misc]  # non-None: keys was non-empty


# Matches "company: <name>" in the user prompt, so the fake client can echo
# the company it is being asked about.
_COMPANY_RE = re.compile(r"company:\s*([^\n]+)", flags=re.IGNORECASE)
_FOCUS_RE = re.compile(r"technical_focus:\s*(.+)", flags=re.IGNORECASE)


class FakeGeminiClient:
    """Deterministic stand-in that simulates Gemini for --dry-run and tests.

    Produces a plausible two-sentence hook that always includes the
    company's first focus term (so the personalization audit stays green).
    """

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def discover(self, system_instruction: str, user_content: str, temperature: float = 0.7) -> str:
        self.calls.append((system_instruction, user_content))
        company = _COMPANY_RE.search(user_content)
        name = company.group(1).strip() if company else "your company"
        focus = _FOCUS_RE.search(user_content)
        focus_term = focus.group(1).strip().split(";")[0].strip() if focus else "AI"
        return (
            f"I have been following {name} closely, and your work in {focus_term} is "
            f"exactly the direction I want my career to take. "
            f"The problems your team is solving are the ones I want to help with."
        )
