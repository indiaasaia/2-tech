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
from pathlib import Path

import requests

HOST = os.getenv("OLLAMA_HOST", "https://ollama.com").rstrip("/")
MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:120b")
TIMEOUT_SECONDS = 120
TEST_QUESTION = "Who is the prime minister of India?"


def send_prompt(prompt: str, token: str) -> str:
    """Send one prompt with the given API token and return the model's reply.

    Raises requests.HTTPError (or a JSON/KeyError) on bad keys or bad responses,
    so callers can decide how to handle failures.
    """
    response = requests.post(
        f"{HOST}/v1/chat/completions",
        json={"model": MODEL, "messages": [{"role": "user", "content": prompt}]},
        headers={"Authorization": f"Bearer {token}"},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


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
