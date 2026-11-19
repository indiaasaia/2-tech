"""Small Ollama client compatible with the archived INFO configuration."""
from __future__ import annotations

import json
import os
import time
from typing import Any

from app.core import config


def resolve_api_key() -> str:
    value = os.getenv("OLLAMA_API_KEY", "").strip()
    if value:
        return value
    for path in config.API_KEY_FILE_CANDIDATES:
        if path.exists():
            values = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
            if values:
                return values[-1]
    return ""


def create_client() -> Any:
    from ollama import Client
    key = resolve_api_key()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return Client(host=config.OLLAMA_HOST, headers=headers, timeout=config.OLLAMA_TIMEOUT_SECONDS)


def _retryable(exc: Exception) -> bool:
    code = getattr(exc, "status_code", None)
    text = str(exc).lower()
    return (isinstance(code, int) and code >= 429) or "429" in text or "too many concurrent" in text or "connection" in text


def call_json(prompt: str, client: Any | None = None) -> Any:
    active = client or create_client()
    for attempt in range(3):
        try:
            response = active.chat(
                model=config.OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                options={"temperature": 0.4},
            )
            text = str(response["message"]["content"]).strip()
            start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
            if start < 0:
                raise ValueError("Ollama response contained no JSON")
            end = max(text.rfind("}"), text.rfind("]"))
            return json.loads(text[start:end + 1])
        except Exception as exc:
            if attempt < 2 and _retryable(exc):
                time.sleep(6 * (attempt + 1))
                continue
            raise
    raise RuntimeError("Ollama request failed")
