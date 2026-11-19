"""Thin Ollama Cloud client for the v2 engine (gpt-oss:120b, 1 request at a time).

The free tier runs one request at a time (V2 C3) — the engine stays serial by
design and retries transient failures with short backoff before parking a job.
"""
from __future__ import annotations

import json
import re
import time

import requests

from resume_content_improve_research import config


class LLMError(RuntimeError):
    """Raised when no key exists or the endpoint keeps failing."""


def load_all_keys() -> list[str]:
    """All keys from active_ollama_keys.json (fallback ollama_keys.json), deduped, in order."""
    ordered: list[str] = []
    for name in ("active_ollama_keys.json", "ollama_keys.json"):
        path = config.PROJECT_ROOT / "sub_program_files" / name
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        keys = data.get("keys", []) if isinstance(data, dict) else data
        for key in keys or []:
            value = str(key).strip()
            if value and value not in ordered:
                ordered.append(value)
    return ordered


def load_first_key() -> str:
    """First key from active_ollama_keys.json (fallback ollama_keys.json), or ''."""
    keys = load_all_keys()
    return keys[0] if keys else ""


# Keys that returned a hard rate limit during THIS process. Free-tier quotas
# are per key, so once a key is exhausted mid-run every later call skips it
# instantly instead of burning three timeouts on it again.
_EXHAUSTED_KEYS: set[str] = set()


def call_llm(
    prompt: str,
    token: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 2000,
    attempts: int = 3,
) -> str:
    """One chat completion with short backoff; raises LLMError after all attempts.

    Key rotation: if `token` is None every configured key is tried in turn;
    if a token is passed it is tried first, then the remaining configured keys.
    A key answered with a rate limit (429) is parked in _EXHAUSTED_KEYS for the
    rest of the process — free-tier quota is per key, so retrying it in-run is
    wasted time (measured 2026-09-22: one dead key stalled the whole hub run).
    """
    requested = (token or "").strip()
    key_pool = [k for k in load_all_keys() if k not in _EXHAUSTED_KEYS]
    if requested and requested not in _EXHAUSTED_KEYS:
        key_pool = [requested] + [k for k in key_pool if k != requested]
    if not key_pool:
        raise LLMError("no usable Ollama key (all configured keys are rate-limited or missing)")

    last_error = ""
    for key in key_pool:
        for attempt in range(1, attempts + 1):
            try:
                response = requests.post(
                    f"{config.OLLAMA_HOST}/v1/chat/completions",
                    json={
                        "model": config.OLLAMA_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=180,
                )
                response.raise_for_status()
                return str(response.json()["choices"][0]["message"]["content"])
            except Exception as exc:  # noqa: BLE001 - transient errors are retried
                last_error = f"{type(exc).__name__}: {exc}"
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status == 429 or "429" in last_error:
                    _EXHAUSTED_KEYS.add(key)
                    print(f"[LLM] key ...{key[-6:]} rate-limited (429) -> rotating to the next key")
                    break  # next key immediately; retrying a 429 never helps in-run
                if attempt < attempts:
                    time.sleep(3 * attempt)
    raise LLMError(f"LLM call failed on all {len(key_pool)} key(s): {last_error}")


def extract_json(raw: str) -> dict | None:
    """Pull the first balanced JSON object out of a model reply, None on failure."""
    if not raw:
        return None
    # fast path: the reply is pure JSON
    stripped = raw.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{", raw)
    if not match:
        return None
    depth = 0
    start = match.start()
    in_string = False
    escape = False
    for index in range(start, len(raw)):
        character = raw[index]
        if in_string:
            if escape:
                escape = False
            elif character == "\\":
                escape = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start:index + 1])
                except json.JSONDecodeError:
                    return None
    return None
