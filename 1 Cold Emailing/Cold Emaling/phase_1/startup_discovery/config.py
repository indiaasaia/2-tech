"""Application configuration.

Every knob that controls discovery behaviour lives here (env vars + CLI
overrides), so the system can be tuned without touching code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Config:
    # --- Gemini ---
    api_key: str = ""                     # GEMINI_API_KEY
    model: str = "gemini-3.6-flash"       # GEMINI_MODEL

    # --- Discovery loop ---
    batch_size: int = 5                   # companies requested per run (DISCOVERY_BATCH_SIZE)
    total_cap: int = 50                   # stop once this many are stored (DISCOVERY_CAP)
    min_hiring_score: int = 55            # reject candidates below this score (DISCOVERY_MIN_SCORE)
    max_runs: int = 20                    # safety limit on API calls per session (DISCOVERY_MAX_RUNS)
    empty_run_retries: int = 1            # consecutive empty runs tolerated before stopping
    temperature: float = 0.2              # DISCOVERY_TEMPERATURE
    cities: tuple[str, ...] = ("Berlin",)  # target cities (DISCOVERY_CITIES, comma-separated)

    # --- State & context ---
    csv_path: str = "data/discovered_companies.csv"   # DISCOVERY_CSV
    prompt_path: str = "prompts/discovery_prompt.md"  # DISCOVERY_PROMPT
    max_exclusion_entries: int | None = 200           # None = no limit

    @classmethod
    def from_env(cls) -> "Config":
        def _int(name: str, default: int) -> int:
            raw = os.environ.get(name)
            return int(raw) if raw not in (None, "") else default

        def _float(name: str, default: float) -> float:
            raw = os.environ.get(name)
            return float(raw) if raw not in (None, "") else default

        def _cities(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
            raw = os.environ.get(name)
            if raw in (None, ""):
                return default
            return tuple(c.strip() for c in raw.split(",") if c.strip())

        return cls(
            api_key=os.environ.get("GEMINI_API_KEY", ""),
            model=os.environ.get("GEMINI_MODEL", cls.model),
            batch_size=_int("DISCOVERY_BATCH_SIZE", cls.batch_size),
            total_cap=_int("DISCOVERY_CAP", cls.total_cap),
            min_hiring_score=_int("DISCOVERY_MIN_SCORE", cls.min_hiring_score),
            max_runs=_int("DISCOVERY_MAX_RUNS", cls.max_runs),
            temperature=_float("DISCOVERY_TEMPERATURE", cls.temperature),
            cities=_cities("DISCOVERY_CITIES", cls.cities),
            csv_path=os.environ.get("DISCOVERY_CSV", cls.csv_path),
            prompt_path=os.environ.get("DISCOVERY_PROMPT", cls.prompt_path),
        )

    def with_overrides(self, **kwargs) -> "Config":
        """Return a copy with the given fields replaced (None values ignored)."""
        return replace(self, **{k: v for k, v in kwargs.items() if v is not None})
