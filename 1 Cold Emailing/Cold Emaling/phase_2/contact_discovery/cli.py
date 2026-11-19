"""Command-line entry point for Phase 2 (contact discovery).

Examples:
  export GEMINI_API_KEY=...
  python -m contact_discovery.cli                     # live run, all companies
  python -m contact_discovery.cli --limit 1           # smoke test on one company
  python -m contact_discovery.cli --dry-run           # offline simulation, no API key needed
  python -m contact_discovery.cli --probe             # verify Gemini connectivity + which models respond
  python -m contact_discovery.cli --max-iterations 5  # deeper research per company
"""
from __future__ import annotations

import argparse
import sys

from . import storage
from .config import Config
from .discovery import run_contact_discovery
from .gemini_client import FakeGeminiClient, GeminiClient


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Contact discovery for cold outreach (stage 2 prototype).")
    parser.add_argument("--dry-run", action="store_true", help="Use a simulated Gemini client (no API key needed).")
    parser.add_argument("--companies", dest="companies_path", help="Phase 1 company list CSV (input).")
    parser.add_argument("--csv", dest="csv_path", help="Contacts output CSV (one row per email).")
    parser.add_argument("--outcomes", dest="outcomes_path", help="Per-company outcome CSV (progress tracker).")
    parser.add_argument("--prompt", dest="prompt_path", help="Iteration-1 research prompt template.")
    parser.add_argument("--repeat-prompt", dest="repeat_prompt_path", help="Repeat-iteration research prompt template.")
    parser.add_argument("--max-iterations", type=int, help="Research passes per company.")
    parser.add_argument("--limit", type=int, help="Process at most this many companies this session.")
    parser.add_argument("--temperature", type=float, help="Sampling temperature.")
    parser.add_argument("--model", help="Primary Gemini model id.")
    parser.add_argument("--fallback-models", help="Comma-separated fallback models, tried in order on rate limits.")
    parser.add_argument("--probe", action="store_true", help="Check Gemini connectivity and which chain models respond, then exit.")
    return parser.parse_args(argv)


def _print_summary(result: dict) -> None:
    reports = result["reports"]
    print(
        f"\n=== SUMMARY: {result['companies_processed']} company/companies processed "
        f"({result['companies_skipped']} skipped: already done or outside --limit), "
        f"{result['contacts_found']} contact(s) stored ==="
    )
    if reports:
        print(f"{'#':>3}  {'Company':<34} {'Status':<24} {'Contacts':>8} {'Iters':>5}")
        for i, report in enumerate(reports, start=1):
            outcome = report["outcome"]
            print(
                f"{i:>3}  {report['company_name'][:34]:<34} {outcome['status'][:24]:<24} "
                f"{outcome['contacts_found']:>8} {outcome['iterations_run']:>5}"
            )
    print(f"\nContacts CSV:  {result.get('csv_path', '')}")
    print(f"Outcomes CSV:  {result.get('outcomes_path', '')}")


def main(argv: list[str] | None = None) -> int:
    # Never crash on exotic characters (e.g. umlauts in company names) that
    # the console encoding cannot represent.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

    args = _parse_args(argv if argv is not None else sys.argv[1:])
    fallback_models = None
    if args.fallback_models:
        fallback_models = tuple(m.strip() for m in args.fallback_models.split(",") if m.strip())
    config = Config.from_env().with_overrides(
        companies_path=args.companies_path,
        csv_path=args.csv_path,
        outcomes_path=args.outcomes_path,
        prompt_path=args.prompt_path,
        repeat_prompt_path=args.repeat_prompt_path,
        max_iterations=args.max_iterations,
        limit=args.limit,
        temperature=args.temperature,
        model=args.model,
        fallback_models=fallback_models,
    )

    if config.max_iterations <= 0:
        print("max-iterations must be a positive integer", file=sys.stderr)
        return 2
    if config.limit is not None and config.limit < 0:
        print("limit must be a non-negative integer", file=sys.stderr)
        return 2

    if args.probe:
        if not config.api_key:
            print("GEMINI_API_KEY is not set. Export it first, e.g. 'export GEMINI_API_KEY=...'", file=sys.stderr)
            return 2
        return _probe(config)

    if args.dry_run:
        client = FakeGeminiClient()
        print(f"DRY RUN - simulated client, no API calls. Up to {config.max_iterations} iterations per company.\n")
    else:
        if not config.api_key:
            print("GEMINI_API_KEY is not set. Export it first, e.g. 'export GEMINI_API_KEY=...'", file=sys.stderr)
            return 2
        client = GeminiClient(api_key=config.api_key, model=config.model, fallback_models=config.fallback_models)
        chain = ", ".join([config.model, *config.fallback_models])
        print(f"Live run - models: {chain} (fallback on rate limits), up to {config.max_iterations} iterations per company.\n")

    try:
        result = run_contact_discovery(client, config)
    except Exception as exc:  # keep CLI error messages friendly
        print(f"Fatal error: {exc}", file=sys.stderr)
        return 1

    result["csv_path"] = config.csv_path
    result["outcomes_path"] = config.outcomes_path
    _print_summary(result)
    return 0


def _probe(config: Config) -> int:
    """Live connectivity check: what models the key can see, and which of
    our chain actually respond to a tiny call."""
    from google import genai  # lazy import

    client = genai.Client(api_key=config.api_key)
    print(f"Probing Gemini connectivity (key {config.api_key[:4]}...)\n")

    try:
        available = {m.name for m in client.models.list()}
    except Exception as exc:
        print(f"Could not list models: {exc}", file=sys.stderr)
        return 1
    print(f"Models visible to this key: {len(available)}")

    chain = [config.model, *config.fallback_models]
    print(f"\nOur model chain (purpose-aligned: agentic research + strict extraction):")
    for model in chain:
        print(f"  {model:<24} available: {'yes' if model in available else 'NO'}")

    print("\nLive call per model:")
    ok = 0
    for model in chain:
        probe_client = GeminiClient(api_key=config.api_key, model=model, fallback_models=())
        try:
            out = probe_client.discover("Reply with exactly: OK", "Connectivity probe.", temperature=0.0)
            if "OK" in out.upper():
                ok += 1
                status = "OK"
            else:
                status = f"responded {out.strip()[:40]!r}"
        except Exception as exc:
            status = f"FAILED: {exc}"
        print(f"  {model:<24} {status}")

    print(f"\n{ok}/{len(chain)} model(s) responding.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
