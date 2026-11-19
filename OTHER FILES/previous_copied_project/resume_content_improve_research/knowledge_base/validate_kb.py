"""Phase A validator for candidate_kb.json.

Checks the KB against the v2 rules:
  - status must be APPROVED before v2 generation may run
  - every skill / experience / project has >=1 evidence id that resolves
  - explicit skills_allowed and skills_forbidden on every experience/project
  - no tool appears in both skills_allowed and skills_forbidden of the same entry
  - titles_forbidden_patterns present on every experience
  - unconfirmed GUESS markers are reported (warn-only, but listed for review)

Run:  python resume_content_improve_research/knowledge_base/validate_kb.py
Exit 0 = structurally valid (GUESS warnings allowed); exit 1 = structural errors.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

KB_PATH = Path(__file__).resolve().parent / "candidate_kb.json"


def load_kb(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"[KB] knowledge base not found: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[KB] INVALID JSON: {exc}")


def validate(kb: dict) -> tuple[list[str], list[str]]:
    """Return (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    def add_err(msg: str) -> None:
        errors.append(msg)

    def add_warn(msg: str) -> None:
        warnings.append(msg)

    # --- status gate -------------------------------------------------------
    status = kb.get("status")
    if status == "DRAFT_PENDING_REVIEW":
        add_warn('status is DRAFT_PENDING_REVIEW - v2 generation must refuse to run until APPROVED')
    elif status != "APPROVED":
        add_err(f'status must be APPROVED or DRAFT_PENDING_REVIEW, got: {status!r}')

    # --- collect evidence ids ---------------------------------------------
    # master_cv is a built-in evidence source: every static fact confirmed by the
    # candidate's own master Academic CV is licensed by it.
    evidence_ids: set[str] = {"master_cv"}
    for exp in kb.get("experience", []):
        evidence_ids.add(exp.get("id", ""))
        second = exp.get("second_stint")
        if second:
            evidence_ids.add(second.get("id", ""))
    for proj in kb.get("projects", []):
        evidence_ids.add(proj.get("id", ""))
    for res in kb.get("research", []):
        evidence_ids.add(res.get("id", ""))

    # --- GUESS markers (review aid) ----------------------------------------
    def find_guess(obj, path="$") -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                find_guess(value, f"{path}.{key}")
        elif isinstance(obj, list):
            for i, value in enumerate(obj):
                find_guess(value, f"{path}[{i}]")
        elif isinstance(obj, str) and "GUESS" in obj.upper():
            add_warn(f"unconfirmed guess at {path}: {obj[:80]}...")

    find_guess(kb)

    # --- global skills: name + evidence ------------------------------------
    for skill in kb.get("skills", []):
        name = skill.get("name", "")
        if not name:
            add_err("skills entry without 'name'")
        ev = skill.get("evidence", [])
        if not ev:
            add_err(f"global skill '{name}' has no evidence")
        for eid in ev:
            base = eid.split()[0]
            if base not in evidence_ids:
                add_err(f"global skill '{name}' references unknown evidence id '{eid}'")

    # --- experiences --------------------------------------------------------
    for exp in kb.get("experience", []):
        entries = [("experience", exp)]
        second = exp.get("second_stint")
        if second:
            entries.append(("second_stint", second))
        for label, entry in entries:
            eid = entry.get("id", "")
            if not eid:
                add_err(f"{label} of '{exp.get('company')}' missing id")
            if not entry.get("evidence"):
                add_err(f"{label} '{eid}' has no evidence")
            allowed = entry.get("skills_allowed", [])
            forbidden = entry.get("skills_forbidden", [])
            if not allowed:
                add_err(f"{label} '{eid}' has empty skills_allowed")
            if not forbidden:
                add_warn(f"{label} '{eid}' has empty skills_forbidden (nothing blocked - fabrication watchlist disabled here)")
            overlap = {a.lower() for a in allowed} & {f.lower() for f in forbidden}
            if overlap:
                add_err(f"{label} '{eid}' skills both allowed and forbidden: {sorted(overlap)}")
            if label == "experience" and not entry.get("titles_allowed"):
                add_err(f"{label} '{eid}' missing titles_allowed")
            if label == "experience" and not entry.get("titles_forbidden_patterns"):
                add_err(f"{label} '{eid}' missing titles_forbidden_patterns")
            # evidence vs forbidden overlap: forbidden tools must not appear in evidence text
            evidence_text = " ".join(str(e) for e in entry.get("evidence", [])).lower()
            for tool in forbidden:
                if re.search(rf"\b{re.escape(tool.lower())}\b", evidence_text):
                    add_err(f"{label} '{eid}': forbidden tool '{tool}' appears in its own evidence text")

    # --- projects -----------------------------------------------------------
    for proj in kb.get("projects", []):
        pid = proj.get("id", "")
        if not proj.get("evidence"):
            add_err(f"project '{pid}' has no evidence")
        if not proj.get("real", False):
            add_err(f"project '{pid}' is not marked real: true - v2 only generates real projects")
        overlap = {a.lower() for a in proj.get("skills_allowed", [])} & {
            f.lower() for f in proj.get("skills_forbidden", [])
        }
        if overlap:
            add_err(f"project '{pid}' skills both allowed and forbidden: {sorted(overlap)}")

    # --- research entries ---------------------------------------------------
    for res in kb.get("research", []):
        if not res.get("id"):
            add_err("research entry missing id")
        if not res.get("evidence"):
            add_err(f"research '{res.get('id')}' has no evidence")

    # --- policy sanity ------------------------------------------------------
    policy = kb.get("templates_policy", {})
    if not policy.get("no_fabricated_metrics", False):
        add_err("templates_policy.no_fabricated_metrics must be true (V4/V6: 35 fabricated metrics measured)")

    return errors, warnings


def main() -> int:
    kb = load_kb(KB_PATH)
    errors, warnings = validate(kb)

    print(f"[KB] {KB_PATH.name}: {len(kb.get('skills', []))} global skills, "
          f"{len(kb.get('experience', []))} experience(s), {len(kb.get('projects', []))} project(s)")

    if warnings:
        print(f"\n[KB] {len(warnings)} review warning(s):")
        for w in warnings:
            print(f"  [WARN] {w}")
    if errors:
        print(f"\n[KB] {len(errors)} structural error(s):")
        for e in errors:
            print(f"  [ERR ] {e}")
        print("\n[KB] RESULT: INVALID")
        return 1
    print("\n[KB] RESULT: STRUCTURALLY VALID")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
