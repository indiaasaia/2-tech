"""Step 3: test each Ollama key from sub_program_files/ollama_keys.json and keep the working ones.

Sends a simple 'HI' message to the Ollama-compatible chat endpoint with every key
and writes the keys that responded successfully to active_ollama_keys.json.

Run directly: python program_files/3_test_ollama_keys.py
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KEYS_FILE = PROJECT_ROOT / "sub_program_files" / "ollama_keys.json"
ACTIVE_KEYS_FILE = PROJECT_ROOT / "sub_program_files" / "active_ollama_keys.json"
HOST = os.getenv("OLLAMA_HOST", "https://ollama.com").rstrip("/")
MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:120b")
TIMEOUT_SECONDS = 30


def load_keys() -> list[str]:
    """Read keys from ollama_keys.json (accepts a bare list or {"keys": [...]})."""
    if not KEYS_FILE.exists():
        print(f"[STEP3] ERROR file not found: {KEYS_FILE}")
        return []
    try:
        data = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[STEP3] ERROR could not read {KEYS_FILE}: {exc}")
        return []
    if isinstance(data, dict):
        data = data.get("keys", [])
    keys = [str(key).strip() for key in data if isinstance(key, str) and key.strip()]
    if not keys:
        print(f"[STEP3] WARNING no keys found in {KEYS_FILE}")
    return keys


def test_key(key: str) -> tuple[bool, str]:
    """Send 'HI' and return (worked, detail) where detail explains failures for debugging."""
    url = f"{HOST}/v1/chat/completions"
    payload = {"model": MODEL, "messages": [{"role": "user", "content": "HI"}]}
    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {key}"},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return False, f"request error {type(exc).__name__}: {exc}"

    if response.status_code == 200:
        try:
            if response.json().get("choices"):
                return True, "HTTP 200 with choices"
        except ValueError as exc:
            return False, f"HTTP 200 but invalid JSON body: {exc}"
        return False, f"HTTP 200 but no choices field: {response.text[:200]}"
    return False, f"HTTP {response.status_code}: {response.text[:200]}"


def test_ollama_keys() -> int:
    """Test every key and write the working ones to active_ollama_keys.json.

    Returns the number of keys that passed.
    """
    keys = load_keys()
    if not keys:
        print(f"[STEP3] no keys configured — add keys to {KEYS_FILE}")
        return 0

    print(f"[STEP3] testing {len(keys)} key(s) against {HOST} (model {MODEL})")
    active: list[str] = []
    for index, key in enumerate(keys, 1):
        if key.startswith("PASTE_"):
            print(f"  [{index}/{len(keys)}] skipped (placeholder)")
            continue
        worked, detail = test_key(key)
        if worked:
            active.append(key)
            print(f"  [{index}/{len(keys)}] [OK] WORKING ({key[:12]}...)")
        else:
            print(f"  [{index}/{len(keys)}] [FAIL] NOT WORKING ({key[:12]}...)")
            print(f"           reason: {detail}")

    try:
        ACTIVE_KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ACTIVE_KEYS_FILE.write_text(json.dumps({"keys": active}, indent=2), encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"could not write {ACTIVE_KEYS_FILE}: {exc}") from exc

    print(f"[STEP3] saved {len(active)} active key(s) -> {ACTIVE_KEYS_FILE}")
    return len(active)


if __name__ == "__main__":
    try:
        sys.exit(0 if test_ollama_keys() else 1)
    except Exception as exc:  # noqa: BLE001 - CLI entry point: report and exit non-zero
        print(f"[STEP3] FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise SystemExit(1) from exc