"""Command-line entry point.

Examples:
  export GEMINI_API_KEY=...
  python -m startup_discovery.cli                     # live campaign (5 per batch, cap 50)
  python -m startup_discovery.cli --once              # single live batch (smoke test)
  python -m startup_discovery.cli --dry-run           # offline simulation, no API key needed
  python -m startup_discovery.cli --cap 10 --batch-size 5
"""
from __future__ import annotations

import argparse
import random
import sys

from . import storage
from .config import Config
from .discovery import run_discovery
from .gemini_client import FakeGeminiClient, GeminiClient


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Berlin startup discovery (stage 1 prototype).")
    parser.add_argument("--dry-run", action="store_true", help="Use a simulated Gemini client (no API key needed).")
    parser.add_argument("--once", action="store_true", help="Run a single batch and stop.")
    parser.add_argument("--csv", dest="csv_path", help="Output CSV path.")
    parser.add_argument("--prompt", dest="prompt_path", help="Prompt template file.")
    parser.add_argument("--batch-size", type=int, help="Companies requested per run.")
    parser.add_argument("--cap", dest="total_cap", type=int, help="Stop once this many companies are stored.")
    parser.add_argument("--min-score", type=int, help="Reject candidates below this hiring-probability score.")
    parser.add_argument("--max-runs", type=int, help="Safety limit on API calls.")
    parser.add_argument("--model", help="Gemini model id.")
    parser.add_argument("--cities", help="Comma-separated target cities (default: Berlin).")
    return parser.parse_args(argv)


def _build_fake_pool(size: int, seed: int = 42) -> list[dict]:
    """Deterministic pool of fake candidates for dry runs."""
    rng = random.Random(seed)
    prefixes = [
        "Nordlicht", "Spreebogen", "Kreuzberg", "Mitte", "Prenzlauer",
        "Charlottenburg", "Friedrichshain", "Tempelhofer", "Wedding",
        "Neukoelln", "Grunewald", "Pankow", "Moabit", "Schoneberg",
        "Tiergarten", "Kopenick", "Rummelsburg", "Adlershof",
    ]
    suffixes = [
        "AI", "Labs", "Digital", "Systems", "Analytics", "Data",
        "Fintech", "Cloud", "Health", "Mobility", "Energy", "Robotics",
    ]
    pool = []
    for i in range(size):
        prefix = rng.choice(prefixes)
        suffix = rng.choice(suffixes)
        slug = f"{prefix.lower()}-{suffix.lower()}-{i}"
        score = rng.randint(58, 95)
        if i % 5 == 4:
            score = 40  # sprinkle in candidates that must fail validation
        pool.append(
            {
                "rank": i + 1,
                "company_name": f"{prefix} {suffix} GmbH",
                "website": f"https://www.{slug}.de",
                "location": "Berlin, Germany",
                "company_size": "11-50 employees",
                "startup_stage": rng.choice(["Seed", "Series A", "Series B", "Scale-up"]),
                "technical_focus": "AI/ML, backend engineering",
                "relevant_roles": "Working Student, AI/ML intern, Backend intern",
                "english_hiring_evidence": "Careers page states English is the company language; recent job postings in English.",
                "student_intern_evidence": "Listed Werkstudent/internship positions on careers page.",
                "current_hiring_evidence": "Open technical positions on careers page.",
                "cold_outreach_potential": "Small team; direct outreach to founders/CTO realistic.",
                "hiring_probability_score": score,
                "priority": "High Priority" if score >= 70 else "Medium Priority",
                "why_target": "Small Berlin tech company with relevant technical work and English-friendly hiring.",
                "sources": [f"https://www.{slug}.de/careers"],
            }
        )
    return pool


def _print_summary(records: list[dict], result: dict) -> None:
    print(
        f"\n=== SUMMARY: {result['total_stored']}/{result['target']} companies stored "
        f"across {result['runs']} run(s) ==="
    )
    if records:
        print(f"{'#':>3}  {'Company':<34} {'Score':>5}  {'Priority':<14} Batch  Website")
        for i, record in enumerate(records, start=1):
            print(
                f"{i:>3}  {record['company_name'][:34]:<34} "
                f"{record['hiring_probability_score']:>5}  {record['priority'][:14]:<14} "
                f"{record['discovery_batch']:<5}  {record['website']}"
            )
    print(f"\nCSV: {result.get('csv_path', '')}")


def main(argv: list[str] | None = None) -> int:
    # Never crash on exotic characters (e.g. umlauts in company names) that
    # the console encoding cannot represent.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

    args = _parse_args(argv if argv is not None else sys.argv[1:])
    cities = None
    if args.cities:
        cities = tuple(c.strip() for c in args.cities.split(",") if c.strip())
    config = Config.from_env().with_overrides(
        csv_path=args.csv_path,
        prompt_path=args.prompt_path,
        batch_size=args.batch_size,
        total_cap=args.total_cap,
        min_hiring_score=args.min_score,
        model=args.model,
        cities=cities,
        max_runs=1 if args.once else args.max_runs,
    )

    if config.batch_size <= 0 or config.total_cap <= 0:
        print("batch-size and cap must be positive integers", file=sys.stderr)
        return 2

    if args.dry_run:
        client = FakeGeminiClient(_build_fake_pool(config.total_cap * 2 + 10), config.batch_size)
        print(f"DRY RUN - simulated client, no API calls. Cap {config.total_cap}, {config.batch_size} per batch.\n")
    else:
        if not config.api_key:
            print("GEMINI_API_KEY is not set. Export it first, e.g. 'export GEMINI_API_KEY=...'", file=sys.stderr)
            return 2
        client = GeminiClient(api_key=config.api_key, model=config.model)
        print(f"Live run - model {config.model}, cap {config.total_cap}, {config.batch_size} per batch.\n")

    try:
        result = run_discovery(client, config)
    except Exception as exc:  # keep CLI error messages friendly
        print(f"Fatal error: {exc}", file=sys.stderr)
        return 1

    result["csv_path"] = config.csv_path
    _print_summary(storage.load_records(config.csv_path), result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
