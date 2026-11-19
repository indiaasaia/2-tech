"""API-key rotation for live runs.

The phase discovery loops accept a single client with a ``discover()``
method. ``RotatingClient`` wraps the provider clients so every **enabled**
key configured in Settings is usable: keys are tried in order and, on any
failure (auth error, quota, rate limit, outage), the next enabled key takes
over automatically. Which key actually served each call is logged, so a
run's log doubles as an audit of key usage.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import settings as settings_mod


class RotatingClient:
    """Adapter with the same ``discover()`` shape as the phase clients.

    ``client_factory`` builds a fresh provider client for a key record
    (a dict with label/value/provider/folder_id), e.g.::

        lambda rec: (
            YandexGPTClient(rec["value"], rec.get("folder_id", ""))
            if rec.get("provider") == "yandex"
            else GeminiClient(api_key=rec["value"], model=cfg.model)
        )
    """

    def __init__(
        self,
        keys: list[dict[str, Any]],
        client_factory: Callable[[dict[str, Any]], Any],
        log_fn: Callable[[str], None] = print,
    ):
        self._keys = keys
        self._factory = client_factory
        self._log = log_fn
        self._index = 0
        self._client: Any = None
        self._current_label: str | None = None
        self.last_model: str | None = None  # which model served the last call

    def _client_for(self) -> Any:
        if self._client is None:
            record = self._keys[self._index]
            label = str(record.get("label") or (record.get("value") or "")[:8])
            self._current_label = label
            self._log(f"[keys] using '{label}' ({record.get('provider', 'gemini')})")
            self._client = self._factory(record)
        return self._client

    def discover(self, system_instruction: str, user_content: str, temperature: float = 0.2) -> str:
        if not self._keys:
            raise RuntimeError(
                "No enabled API keys. Open Settings → API keys and add a Gemini "
                "(AIza…) or Yandex (AQ… + folder id) key."
            )
        last_error: Exception | None = None
        for _ in range(len(self._keys)):
            try:
                client = self._client_for()
                text = client.discover(system_instruction, user_content, temperature)
                self.last_model = getattr(client, "last_model", None)
                return text
            except Exception as exc:
                last_error = exc
                self._log(
                    f"[keys] '{self._current_label}' failed ({type(exc).__name__}: {exc}); "
                    f"trying the next key"
                )
                self._index = (self._index + 1) % len(self._keys)
                self._client = None
        raise last_error  # type: ignore[misc]  # non-None: loop ran at least once


# Backwards-compatible alias.
RotatingGeminiClient = RotatingClient


def build_provider_factory(phase_model: str, phase: int = 1, phase2_fallback: tuple[str, ...] = ()) -> Callable:
    """Return a ``client_factory`` that dispatches by provider.

    Yandex keys use the native YandexGPT client; everything else uses the
    matching phase Gemini client (with model/fallback chain for Phase 2).
    ``phase`` is 1 or 2 and picks the right Gemini client explicitly, so an
    empty fallback list on Phase 2 still builds the Phase 2 client.
    """
    from .providers.yandex import YandexGPTClient

    def factory(record: dict[str, Any]) -> Any:
        value = str(record.get("value") or "").strip()
        provider = record.get("provider")
        if provider == "yandex":
            return YandexGPTClient(
                api_key=value,
                folder_id=str(record.get("folder_id") or "").strip(),
                model=phase_model,
            )
        return _gemini_client(phase_model, phase, phase2_fallback, value)

    return factory


def _gemini_client(
    phase_model: str, phase: int, phase2_fallback: tuple[str, ...], key: str
) -> Any:
    try:
        from phase_1.startup_discovery.gemini_client import GeminiClient as P1Client
        from phase_2.contact_discovery.gemini_client import GeminiClient as P2Client

        if phase == 2:
            return P2Client(api_key=key, model=phase_model, fallback_models=phase2_fallback)
        return P1Client(api_key=key, model=phase_model)
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is not installed — needed for Gemini live runs. "
            "Install it with: pip install -r streamlit_app/requirements.txt  "
            "(Yandex keys do not need it.)"
        ) from exc


def ensure_usable_keys(keys: list[dict[str, Any]], log_fn: Callable[[str], None] = print) -> bool:
    """Log a warning for keys missing provider requirements; True if at least
    one key is fully usable (the others will just fail and rotate past)."""
    ready = [k for k in keys if settings_mod.provider_ready(k)]
    for key in keys:
        if not settings_mod.provider_ready(key):
            label = key.get("label") or (key.get("value") or "")[:8]
            log_fn(
                f"[keys] '{label}' is a Yandex key without a folder id — it will fail "
                "until you add the folder id in Settings → API keys."
            )
    return bool(ready)
