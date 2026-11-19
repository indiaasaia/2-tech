"""Test Ollama API keys by sending a simple "HI" message and checking the response.

Reads keys from ollama_keys.json in this folder. Configure the endpoint and
model via the OLLAMA_HOST / OLLAMA_MODEL environment variables.

Usage: python ollama_key_testing.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

KEYS_FILE = Path(__file__).resolve().parent / "ollama_keys.json"
HOST = os.getenv("OLLAMA_HOST", "https://ollama.com").rstrip("/")
MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:120b")
TIMEOUT_SECONDS = 30


def load_keys() -> list[str]:
    """Read the list of keys from ollama_keys.json (accepts a bare list or {"keys": [...]})."""
    if not KEYS_FILE.exists():
        print(f"[KEYS] file not found: {KEYS_FILE}")
        return []
    try:
        data = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[KEYS] failed to read {KEYS_FILE}: {exc}")
        return []
    if isinstance(data, dict):
        data = data.get("keys", [])
    return [str(key).strip() for key in data if isinstance(key, str) and key.strip()]


def test_key(key: str) -> bool:
    """Send 'HI' to the chat endpoint and return whether the key works."""
    url = f"{HOST}/v1/chat/completions"
    payload = {"model": MODEL, "messages": [{"role": "user", "content": "HI"}]}
    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {key}"},
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code == 200 and response.json().get("choices"):
            return True
        print(f"      status {response.status_code}: {response.text[:200]}")
        return False
    except requests.RequestException as exc:
        print(f"      request failed: {type(exc).__name__}: {exc}")
        return False


def main() -> int:
    """Test every configured key and print per-key results; exit 0 on success."""
    keys = load_keys()
    if not keys:
        print(f"[KEYS] no keys configured — add keys to {KEYS_FILE}")
        return 1

    print(f"[KEYS] testing {len(keys)} key(s) against {HOST} (model {MODEL})")
    working = 0
    tested = 0
    for index, key in enumerate(keys, 1):
        if key.startswith("PASTE_"):
            print(f"  [{index}/{len(keys)}] skipped (placeholder)")
            continue
        tested += 1
        ok = test_key(key)
        working += ok
        label = "[OK] WORKING" if ok else "[FAIL] NOT WORKING"
        print(f"  [{index}/{len(keys)}] {label} ({key[:12]}...)")

    print(f"[KEYS] {working} of {tested} configured key(s) working")
    return 0 if working else 1


if __name__ == "__main__":
    raise SystemExit(main())
