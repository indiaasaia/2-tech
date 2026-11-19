"""Application configuration.

Every knob that controls contact discovery lives here (env vars + CLI
overrides), so the system can be tuned without touching code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Config:
    # --- Gemini ---
    api_key: str = ""                     # GEMINI_API_KEY
    model: str = "gemini-3.7-flash"       # GEMINI_MODEL (primary; best agentic research/extraction)
    fallback_models: tuple[str, ...] = (  # GEMINI_FALLBACK_MODELS (tried in order on rate limits)
        "gemini-3.6-flash",
        "gemini-3.5-flash",
    )

    # --- Research loop ---
    temperature: float = 0.2              # CONTACT_TEMPERATURE
    max_iterations: int = 3               # research passes per company (CONTACT_MAX_ITERATIONS)
    limit: int | None = None              # process at most this many companies per session (CONTACT_LIMIT)

    # --- State & context ---
    companies_path: str = "data/discovered_companies.csv"        # CONTACT_COMPANIES_CSV (Phase 1 output)
    csv_path: str = "data/contact_discovery_results.csv"         # CONTACT_CSV (one row per contact)
    outcomes_path: str = "data/contact_discovery_outcomes.csv"   # CONTACT_OUTCOMES_CSV (one row per company)
    prompt_path: str = "prompts/contact_discovery_prompt.md"           # CONTACT_PROMPT (iteration 1)
    repeat_prompt_path: str = "prompts/contact_discovery_repeat_prompt.md"  # CONTACT_REPEAT_PROMPT (iterations 2+)

    @classmethod
    def from_env(cls) -> "Config":
        def _int(name: str, default: int) -> int:
            raw = os.environ.get(name)
            return int(raw) if raw not in (None, "") else default

        def _float(name: str, default: float) -> float:
            raw = os.environ.get(name)
            return float(raw) if raw not in (None, "") else default

        def _models(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
            raw = os.environ.get(name)
            if raw in (None, ""):
                return default
            return tuple(m.strip() for m in raw.split(",") if m.strip())

        def _optional_int(name: str) -> int | None:
            raw = os.environ.get(name)
            return None if raw in (None, "") else int(raw)

        return cls(
            api_key=os.environ.get("GEMINI_API_KEY", ""),
            model=os.environ.get("GEMINI_MODEL", cls.model),
            fallback_models=_models("GEMINI_FALLBACK_MODELS", cls.fallback_models),
            temperature=_float("CONTACT_TEMPERATURE", cls.temperature),
            max_iterations=_int("CONTACT_MAX_ITERATIONS", cls.max_iterations),
            limit=_optional_int("CONTACT_LIMIT"),
            companies_path=os.environ.get("CONTACT_COMPANIES_CSV", cls.companies_path),
            csv_path=os.environ.get("CONTACT_CSV", cls.csv_path),
            outcomes_path=os.environ.get("CONTACT_OUTCOMES_CSV", cls.outcomes_path),
            prompt_path=os.environ.get("CONTACT_PROMPT", cls.prompt_path),
            repeat_prompt_path=os.environ.get("CONTACT_REPEAT_PROMPT", cls.repeat_prompt_path),
        )

    def with_overrides(self, **kwargs) -> "Config":
        """Return a copy with the given fields replaced (None values ignored)."""
        return replace(self, **{k: v for k, v in kwargs.items() if v is not None})
