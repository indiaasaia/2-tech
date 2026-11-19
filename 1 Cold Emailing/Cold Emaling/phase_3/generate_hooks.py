#!/usr/bin/env python3
"""
generate_hooks.py — Phase E of PERSONALIZATION_PLAN.md (Layer 7).

One Gemini call per company: reads the Phase 1 evidence (already joined
into `contacts_to_send.csv`) plus the sender profile from `.env`, and asks
Gemini to write a 2-sentence personalised opening for the cold email.
Results are stored in `data/email_hooks.csv` (`company_name,hook`) and
picked up automatically by `send_emails.py` via `EMAIL_HOOKS_CSV`.

A company that comes back "NO_HOOK" (evidence too thin) is stored with an
empty hook, so the Layer 2 fallback (focus + why + hiring) is used instead.

Keys — every Gemini key found is used, rotating on failure:
  1. gemini_keys.json at the project root (the file you edit directly)
  2. env GEMINI_API_KEYS (comma-separated)
  3. env GEMINI_API_KEY + GEMINI_API_KEY_2 (or phase_3/.env, same names)
  4. streamlit_app/settings.json (the Streamlit app's key store)

The hook prompt itself can be overridden from the project-root prompts.md
(section "PHASE 3 - COMPANY HOOK PROMPT"): campaign.py extracts it and
passes the path via the HOOK_PROMPT_PATH env var. Without it, the built-in
SYSTEM_PROMPT below is used.

Usage:
  python3 generate_hooks.py                 # all companies, skip existing hooks
  python3 generate_hooks.py --force         # regenerate everything
  python3 generate_hooks.py --company Parloa
  python3 generate_hooks.py --limit 3
  python3 generate_hooks.py --dry-run       # fake client, write nothing
  python3 generate_hooks.py --probe         # verify keys + models, write nothing
  python3 generate_hooks.py --model gemini-3.6-flash
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone

import hooks_client
import send_emails

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = "contacts_to_send.csv"
DEFAULT_HOOKS = os.path.join("data", "email_hooks.csv")
DEFAULT_MODEL = "gemini-3.6-flash"
DEFAULT_FALLBACKS = ("gemini-3.5-flash", "gemini-3.7-flash")

SETTINGS_PATH = os.path.join(HERE, "..", "streamlit_app", "settings.json")
GEMINI_KEYS_FILE = os.path.join(HERE, "..", "gemini_keys.json")

# The hook replaces only the email's opening line. The sender's degree,
# university, location, availability and skills are deliberately NOT in the
# prompt: the email's intro already states them, and what the model cannot
# see it cannot repeat. The hook is pure company focus.
SYSTEM_PROMPT = (
    "You write the opening two sentences of a cold placement-application email "
    "from a student to a Berlin recruiting/employment agency, registering as a "
    "candidate. Focus ONLY on the agency: what it does, and why the sender's "
    "candidate profile fits the placements it fills. Rules:\n"
    "- First person, natural, specific, professional but not stiff.\n"
    "- Do not mention the sender's degree, university, location, "
    "availability, or personal skills.\n"
    "- Use ONLY the COMPANY RESEARCH facts below. Never invent names, "
    "numbers, roles, dates, or achievements.\n"
    "- Include at least one of the company's exact technical-focus phrases.\n"
    "- Exactly one or two short sentences, max 25 words total. Point-to-\n"
    "point style: short sentences, no long clauses, no fluff.\n"
    "- No greeting, no sign-off, no subject line.\n"
    "- Reply with ONLY the two sentences, or with exactly NO_HOOK when the "
    "evidence is too thin to write something specific."
)


def _load_system_prompt() -> str:
    """Hook prompt from the project-root prompts.md (via HOOK_PROMPT_PATH,
    set by campaign.py), falling back to the built-in SYSTEM_PROMPT."""
    path = os.environ.get("HOOK_PROMPT_PATH", "")
    if path and os.path.exists(path):
        try:
            text = open(path, encoding="utf-8").read().strip()
            if text:
                return text
        except OSError:
            pass
    return SYSTEM_PROMPT


def build_prompt(facts, company_row, system_prompt: str | None = None) -> tuple[str, str]:
    """Return (system_instruction, user_content) for one company."""
    system = system_prompt or SYSTEM_PROMPT
    user = (
        "COMPANY RESEARCH\n"
        f"company: {facts['company']}\n"
        f"website: {company_row.get('website', '')}\n"
        f"technical_focus: {facts['technical_focus']}\n"
        f"why_target: {facts['why_target']}\n"
        f"relevant_roles: {facts['relevant_roles']}\n"
        f"current_hiring_evidence: {facts['current_hiring_evidence']}\n"
    )
    return SYSTEM_PROMPT, user


def normalize_hook(text: str) -> str:
    """Collapse whitespace/newlines into one line; keep it one sentence-y."""
    text = (text or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^[\"'\u201c\u201d]+|[\"'\u201c\u201d]+$", "", text)
    if text and text.upper() == "NO_HOOK":
        return ""
    if text and not text.endswith((".", "!", "?")):
        text += "."
    return text


def find_keys(env: dict[str, str]) -> list[dict[str, str]]:
    """All Gemini keys available, in priority order, deduplicated."""
    keys: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(label: str, value: str) -> None:
        value = (value or "").strip()
        if not value or value in seen:
            return
        seen.add(value)
        keys.append({"label": label, "value": value})

    def read_store(path: str, fallback_label: str) -> None:
        """Add enabled gemini keys from a JSON key store ({api_keys: [...]})."""
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("api_keys", []):
                if not item.get("enabled", True):
                    continue
                provider = str(item.get("provider") or "").lower()
                value = str(item.get("value") or "").strip()
                if provider == "gemini" or (not provider and value.startswith("AIza")):
                    add(str(item.get("label") or fallback_label), value)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"WARNING: could not read {path}: {exc}")

    # 1. The campaign's key store — gemini_keys.json at the project root
    #    (the file you edit directly).
    read_store(GEMINI_KEYS_FILE, "gemini_keys.json")

    # 2. Explicit comma-separated list (env, then .env).
    for source in (os.environ, env):
        raw = source.get("GEMINI_API_KEYS", "")
        for i, value in enumerate(raw.split(","), start=1):
            add(f"GEMINI_API_KEYS[{i}]", value)

    # 3. Primary + secondary keys (env, then .env).
    for source in (os.environ, env):
        add("GEMINI_API_KEY", source.get("GEMINI_API_KEY", ""))
        add("GEMINI_API_KEY_2", source.get("GEMINI_API_KEY_2", ""))

    # 4. The Streamlit app's key store as a fallback.
    read_store(SETTINGS_PATH, "settings.json")

    return keys


def read_existing(path: str) -> dict[str, dict]:
    """company_name (lowercased) -> {"company_name", "hook"} for existing rows.

    Rows with an empty or NO_HOOK hook are ignored (they mean "Layer 2")."""
    existing: dict[str, dict] = {}
    if not os.path.exists(path):
        return existing
    with open(path, encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            company = (raw.get("company_name") or "").strip()
            hook = (raw.get("hook") or "").strip()
            if company and hook and hook.upper() != "NO_HOOK":
                existing[company.lower()] = {"company_name": company, "hook": hook}
    return existing


def write_hooks(path: str, rows: list[dict[str, str]]) -> None:
    """Write the full hooks file. Callers pass the MERGED list (existing +
    newly generated), so re-running never drops previously generated hooks."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["company_name", "hook", "generated_at"])
        writer.writeheader()
        for row in rows:
            writer.writerow({"company_name": row["company_name"], "hook": row["hook"],
                             "generated_at": now})


def probe(keys: list[dict[str, str]], model: str, fallback_models: tuple[str, ...]) -> None:
    """Verify connectivity for every key and model in the chain."""
    if not keys:
        print("No Gemini keys found — nothing to probe.", file=sys.stderr)
        sys.exit(1)
    models = [model, *fallback_models]
    ok_any = False
    for record in keys:
        label = str(record.get("label") or record["value"][:8])
        print(f"\nkey '{label}' ({record['value'][:4]}...):")
        for m in models:
            try:
                client = hooks_client.GeminiClient(record["value"], model=m, fallback_models=())
                text = client.discover(
                    "Reply with the single word OK.",
                    "Connectivity check.",
                    temperature=0.0,
                )
                status = "OK" if text.strip().upper() == "OK" else f"OK (reply: {text.strip()[:20]!r})"
                print(f"  {m:28s} {status}")
                ok_any = True
            except Exception as exc:
                print(f"  {m:28s} FAIL ({type(exc).__name__}: {exc})")
    sys.exit(0 if ok_any else 1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=DEFAULT_CSV, help="planned recipient CSV (default: contacts_to_send.csv)")
    ap.add_argument("--hooks", default=DEFAULT_HOOKS, help="output hooks CSV (default: data/email_hooks.csv)")
    ap.add_argument("--force", action="store_true", help="regenerate hooks even if they already exist")
    ap.add_argument("--company", help="only this company (substring match)")
    ap.add_argument("--limit", type=int, default=None, help="at most this many companies this run")
    ap.add_argument("--model", default=None, help=f"primary Gemini model (default: {DEFAULT_MODEL})")
    ap.add_argument("--fallback-models", default=None, help="comma-separated fallback models")
    ap.add_argument("--dry-run", action="store_true", help="use the fake client, write nothing")
    ap.add_argument("--probe", action="store_true", help="verify keys + models, then exit")
    args = ap.parse_args()

    here = HERE
    csv_path = args.csv if os.path.isabs(args.csv) else os.path.join(here, args.csv)
    hooks_path = args.hooks if os.path.isabs(args.hooks) else os.path.join(here, args.hooks)

    if not os.path.exists(csv_path):
        print(f"ERROR: {csv_path} not found. Run `python3 build_email_list.py` first.",
              file=sys.stderr)
        sys.exit(1)

    cfg = send_emails.load_env()
    model = args.model or cfg.get("GEMINI_MODEL") or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
    if args.fallback_models:
        fallback_models = tuple(m.strip() for m in args.fallback_models.split(",") if m.strip())
    else:
        raw = cfg.get("GEMINI_FALLBACK_MODELS", "")
        fallback_models = tuple(m.strip() for m in raw.split(",") if m.strip()) or DEFAULT_FALLBACKS

    keys = find_keys(cfg)
    system_prompt = _load_system_prompt()

    if args.probe:
        probe(keys, model, fallback_models)
        return

    # One row per company (company-level fields are repeated across rows).
    rows = send_emails.read_recipients(csv_path)
    by_company: dict[str, dict] = {}
    for row in rows:
        by_company.setdefault(row["company_name"], row)
    companies = list(by_company.values())
    if args.company:
        companies = [r for r in companies if args.company.lower() in r["company_name"].lower()]
    if args.limit is not None:
        companies = companies[: args.limit]
    if not companies:
        print("No companies matched.", file=sys.stderr)
        sys.exit(1)

    existing = read_existing(hooks_path)
    todo = []
    for row in companies:
        if not args.force and row["company_name"].lower() in existing:
            continue
        todo.append(row)

    if not todo:
        print("Nothing to do — every company already has a hook. Use --force to regenerate.")
        return

    print(f"Companies to process: {len(todo)}/{len(companies)} "
          f"(keys: {', '.join(k['label'] for k in keys) or 'NONE'})")

    if args.dry_run:
        client = hooks_client.FakeGeminiClient()
    else:
        client = hooks_client.RotatingGeminiHooks(keys, model=model, fallback_models=fallback_models)

    results = []
    for i, row in enumerate(todo, start=1):
        facts = send_emails.make_facts(cfg, row)
        system, user = build_prompt(facts, row, system_prompt)
        hook = normalize_hook(client.discover(system, user))
        served = ""
        if not args.dry_run:
            served = f"  [key: {client.last_key}, model: {client.last_model}]"
        if hook:
            print(f"[{i}/{len(todo)}] {row['company_name']}: {hook}{served}")
        else:
            print(f"[{i}/{len(todo)}] {row['company_name']}: NO_HOOK (Layer 2 fallback){served}")
        results.append({"company_name": row["company_name"], "hook": hook})

    if args.dry_run:
        print(f"\nDry run — {len(results)} hook(s) generated with the fake client, nothing written.")
        return

    # Merge: keep hooks that were already in the file, add/overwrite the new ones.
    merged: dict[str, dict] = {name: dict(rec) for name, rec in existing.items()}
    for r in results:
        merged[r["company_name"].lower()] = {"company_name": r["company_name"], "hook": r["hook"]}
    write_hooks(hooks_path, list(merged.values()))
    print(f"\nWrote {len(merged)} hook(s) ({(len(merged) - len(results))} kept from before) -> {hooks_path}")


if __name__ == "__main__":
    main()
