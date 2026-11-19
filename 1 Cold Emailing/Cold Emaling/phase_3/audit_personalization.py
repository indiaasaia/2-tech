#!/usr/bin/env python3
"""
audit_personalization.py — Phase F of PERSONALIZATION_PLAN.md.

Renders every planned email (subject + plain body + html body) and asserts
the personalization guarantees:

  1. No unresolved "{...}" placeholders, no "TODO", no empty sentences.
  2. Every email contains the company's name.
  3. Person-name contacts use the first-name greeting; role inboxes get the
     "Hi {Company} team," greeting.
  4. >= 90% of emails contain at least one of the company's focus terms.

Exit code 0 = pass, 1 = violations found. Nothing is sent.

Usage:
  python3 audit_personalization.py [--csv contacts_to_send.csv]
"""

import argparse
import os
import re
import sys

import email_text
import send_emails

PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")
TARGET_FOCUS_COVERAGE = 0.90


def audit(csv_path):
    env_path = ".env" if os.path.exists(".env") else os.path.join(os.path.dirname(__file__), ".env")
    cfg = send_emails.load_env(env_path)
    cfg["_HOOKS"] = send_emails.load_hooks(cfg)

    if not os.path.exists(csv_path):
        alt_path = os.path.join(os.path.dirname(__file__), csv_path)
        if os.path.exists(alt_path):
            csv_path = alt_path
        else:
            print(f"ERROR: {csv_path} not found. Run `python3 build_email_list.py` first.",
                  file=sys.stderr)
            sys.exit(1)

    rows = send_emails.read_recipients(csv_path)
    if not rows:
        print("ERROR: no recipients in", csv_path, file=sys.stderr)
        sys.exit(1)

    violations = []
    focus_checked = 0
    focus_hits = 0
    person_greetings = 0

    for i, row in enumerate(rows, start=1):
        facts = send_emails.make_facts(cfg, row)
        company = facts["company"]
        subject = email_text.subject(facts)
        plain = email_text.plain_body(facts)
        html = email_text.html_body(facts)
        label = f"[{i}] {company} <{row['email']}>"

        # 1. No unresolved placeholders / TODOs / empty sections
        for text, what in ((subject, "subject"), (plain, "plain body"), (html, "html body")):
            if PLACEHOLDER_RE.search(text):
                violations.append(f"{label}: unresolved placeholder in {what}: "
                                  f"{PLACEHOLDER_RE.search(text).group(0)}")
            if "TODO" in text:
                violations.append(f"{label}: 'TODO' in {what}")
        if not plain.strip():
            violations.append(f"{label}: plain body is empty")
        # 1b. A pre-written hook (Layer 7) must be a real opening, not a stub.
        hook = facts.get("company_hook") or ""
        if hook and len(hook.strip()) < 20:
            violations.append(f"{label}: hook is suspiciously short ({len(hook.strip())} chars)")

        # 2. Company name present (verifies full company name or core brand name)
        brand = re.sub(r"\s*(?:gmbh|ag|se|ug|inc|llc|ltd|\(.*?\))\s*", "", company, flags=re.IGNORECASE).strip()
        for text, what in ((plain, "plain body"), (html, "html body")):
            if company.lower() not in text.lower() and (not brand or brand.lower() not in text.lower()):
                violations.append(f"{label}: company name missing from {what}")

        # 3. Greeting matches the person / role-inbox rule
        expected = email_text.greeting(facts)
        first_line = plain.split("\n\n", 1)[0].strip()
        if first_line != expected:
            violations.append(
                f"{label}: greeting {first_line!r} != expected {expected!r}")
        if not email_text._is_role_inbox(facts.get("contact_name")):
            person_greetings += 1
            if not expected.startswith("Hi "):
                violations.append(f"{label}: person contact without first-name greeting")

        # 4. Focus-term coverage (only rows that carry focus data)
        terms = email_text._focus_terms(facts)
        if terms:
            focus_checked += 1
            if any(t.lower() in plain.lower() for t in terms):
                focus_hits += 1

    coverage = (focus_hits / focus_checked) if focus_checked else 1.0

    print(f"Audited {len(rows)} recipient(s) from {csv_path}")
    print(f"Person-name greetings: {person_greetings}/{len(rows)}")
    print(f"Focus coverage:        {focus_hits}/{focus_checked} "
          f"({coverage:.0%}, target {TARGET_FOCUS_COVERAGE:.0%})")

    if violations:
        print(f"\n{len(violations)} violation(s):")
        for v in violations:
            print("  -", v)
    else:
        print("\nNo violations.")

    failed = bool(violations) or coverage < TARGET_FOCUS_COVERAGE
    print("\nRESULT:", "FAIL" if failed else "PASS")
    sys.exit(1 if failed else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default="contacts_to_send.csv", help="planned recipient CSV")
    args = ap.parse_args()
    audit(args.csv)


if __name__ == "__main__":
    main()
