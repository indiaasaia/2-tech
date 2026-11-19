"""Send one prompt to the Ollama chat endpoint and return the response text.

Shared by the resume-section generators: pass a prompt and an API token,
get the model's reply back. Configure the endpoint and model via the
OLLAMA_HOST / OLLAMA_MODEL environment variables.

Self-test (uses the first key from active_ollama_keys.json, falling back to
ollama_keys.json): python ollama_request_response.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

HOST = os.getenv("OLLAMA_HOST", "https://ollama.com").rstrip("/")
MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:120b")
TIMEOUT_SECONDS = 120
TEST_QUESTION = "Who is the prime minister of India?"

# Transient network failures are retried automatically so one dropped
# connection never poisons a whole pipeline run.
RETRY_ATTEMPTS = 4
RETRY_BASE_DELAY = 3  # seconds; delay = base * attempt (3, 6, 9)


def _post_once(prompt: str, token: str) -> str:
    """One POST to the chat endpoint; raises on any failure."""
    response = requests.post(
        f"{HOST}/v1/chat/completions",
        json={"model": MODEL, "messages": [{"role": "user", "content": prompt}]},
        headers={"Authorization": f"Bearer {token}"},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def send_prompt(prompt: str, token: str) -> str:
    """Send one prompt with the given API token and return the model's reply.

    Transient transport errors (connection reset, timeout, 5xx) are retried
    with linear backoff. Permanent errors (4xx) raise immediately.
    """
    last_error: Exception | None = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return _post_once(prompt, token)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status < 500:  # bad key / bad request: retrying cannot help
                raise
            last_error = exc
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = exc
        if attempt < RETRY_ATTEMPTS:
            delay = RETRY_BASE_DELAY * attempt
            print(f"[OLLAMA] transient error ({type(last_error).__name__}), "
                  f"retry {attempt}/{RETRY_ATTEMPTS - 1} in {delay}s ...", flush=True)
            time.sleep(delay)
    assert last_error is not None
    raise last_error


def load_first_key() -> str:
    """Return the first key from active_ollama_keys.json (or ollama_keys.json), or ''."""
    for name in ("active_ollama_keys.json", "ollama_keys.json"):
        path = Path(__file__).resolve().parent / name
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        keys = data.get("keys", []) if isinstance(data, dict) else data
        if keys:
            return str(keys[0]).strip()
    return ""


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    key = load_first_key()
    if not key:
        raise SystemExit("[OLLAMA] no usable key found")
    print(f"[OLLAMA] question: {TEST_QUESTION}")
    print(f"[OLLAMA] response:\n{send_prompt(TEST_QUESTION, key)}")
