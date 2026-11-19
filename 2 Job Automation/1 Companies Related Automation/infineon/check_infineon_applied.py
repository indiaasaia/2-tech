"""check_infineon_applied.py — READ-ONLY: does Eightfold show an application?

Opens one Infineon job page (the application form is embedded in it), waits
for the SPA to render, then dumps raw signals WITHOUT uploading anything,
filling anything, or clicking anything:

  - file-input presence (the resume upload control)
  - any 'already applied'-style body text
  - visible button labels (an applied state can swap 'Submit' for 'Applied')
  - full-page screenshot

Run it on known-applied and known-not-applied jobs first (controls) — the
detector is derived from that evidence, never assumed.

Usage:
    python check_infineon_applied.py <job_url> [label]
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("infineon_job_apply", ROOT / "infineon_job_apply.py")
inf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inf)

from playwright.sync_api import sync_playwright  # noqa: E402

ALREADY_TEXT = re.compile(
    r"already\s+applied|you\s+have\s+applied|application\s+already\s+exists"
    r"|you\s+applied\s+(?:for|to)\s+this",
    re.I,
)


def _labels(page) -> list[str]:
    out = []
    for role in ("button", "link"):
        loc = page.get_by_role(role)
        for i in range(min(loc.count(), 40)):
            try:
                t = loc.nth(i).inner_text(timeout=2_000).strip()
                if t and len(t) < 60 and t not in out:
                    out.append(t)
            except Exception:  # noqa: BLE001
                continue
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python check_infineon_applied.py <job_url> [label]")
        return 2
    url = sys.argv[1]
    label = sys.argv[2] if len(sys.argv) > 2 else inf._job_id(url)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(viewport=inf.VIEWPORT)
        page = context.new_page()
        page.set_default_timeout(inf.DEFAULT_TIMEOUT_MS)
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        inf._settle(page, 12_000)
        inf._dismiss_cookie_banner(page)

        # wait for either the form or an applied-state message
        deadline = 30
        seen_form = False
        while deadline > 0:
            body = inf._visible_body_text(page)
            if re.search(r"resume|contact\s+information|already\s+applied", body, re.I):
                seen_form = True
                break
            page.wait_for_timeout(2_000)
            deadline -= 2
        body = inf._visible_body_text(page)
        already = ALREADY_TEXT.search(body)

        evidence = {
            "label": label,
            "url": url,
            "formOrMessageVisible": seen_form,
            "alreadyAppliedTextMatch": already.group(0) if already else None,
            "fileInputCount": page.locator("input[type='file']").count(),
            "buttonsAndLinks": _labels(page),
            "bodySnippet": body[:1_200],
        }
        shot = ROOT / "results" / f"check-{label}.png"
        page.screenshot(path=str(shot), full_page=False)
        evidence["screenshot"] = shot.name
        out = ROOT / "results" / f"check-{label}.json"
        out.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")

        print(f"[check] form/message visible: {seen_form}")
        print(f"[check] already-applied text: {already.group(0) if already else None}")
        print(f"[check] file inputs: {evidence['fileInputCount']}")
        print(f"[check] buttons: {evidence['buttonsAndLinks'][:12]}")
        print(f"[check] saved -> {out.name}")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
