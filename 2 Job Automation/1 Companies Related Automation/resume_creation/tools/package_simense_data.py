"""package_simense_data.py — build the Desktop SIMENSE_DATA package.

Takes every verified tailored resume from the simense hub state
(job_resume_map_simense.csv), copies each PDF to
    <Desktop>/SIMENSE_DATA/RAVAL_MEETKUMAR_RITESHKUMAR_[JOB_ROLE_IN_SHORT].pdf
and writes simense_jobs.csv with columns: Job URL, RESUME FULL PATH
(paths point at the Desktop copies; utf-8-sig so Excel opens it cleanly).

Filename slugs are derived from the job title (ASCII, short, unique);
collisions get a numeric suffix. Existing files are overwritten so the
package can be regenerated at any time.

Run:
    python tools/package_simense_data.py
"""
from __future__ import annotations

import csv
import re
import shutil
import sys
import unicodedata
from pathlib import Path

STATE = Path(__file__).resolve().parents[1] / "program_files" / "output_v2" / "state"
MAP = STATE / "job_resume_map_simense.csv"
DESKTOP = Path(r"C:\Users\raval\Desktop")
OUT_DIR = DESKTOP / "SIMENSE_DATA"
CSV_OUT = OUT_DIR / "simense_jobs.csv"

PREFIX = "RAVAL_MEETKUMAR_RITESHKUMAR_"
STOPWORDS = {
    "w/m/d", "w/m/div", "f/m/d", "f/m/div", "m/w/d", "m/w/div", "d", "w", "m",
    "f", "div", "und", "der", "den", "dem", "des", "für", "im", "in", "zum",
    "zur", "the", "for", "and", "of", "a",
}


def slugify(title: str) -> str:
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"\((?:[^)]*)\)", " ", t)          # drop parenthesized (w/m/d) etc.
    t = re.sub(r"[^A-Za-z0-9]+", " ", t)
    words = [w for w in t.split() if w.lower() not in STOPWORDS and not w.isdigit()]
    slug = "-".join(words)[:48].strip("-") or "Role"
    return slug


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    if not MAP.exists():
        print(f"resume map not found: {MAP}")
        return 1
    rows = list(csv.DictReader(MAP.open(encoding="utf-8-sig", newline="")))
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    packaged, skipped = [], []
    used: set[str] = set()
    for r in rows:
        if (r.get("status") or "").upper() != "OK":
            skipped.append((r.get("job_url", ""), "status not OK"))
            continue
        src = Path(r.get("resume_pdf") or "")
        if not src.is_file():
            skipped.append((r.get("job_url", ""), "pdf missing on disk"))
            continue
        slug = slugify(r.get("title") or "")
        name = f"{PREFIX}{slug}.pdf"
        n = 2
        while name.lower() in used:
            name = f"{PREFIX}{slug}-{n}.pdf"
            n += 1
        used.add(name.lower())
        dst = OUT_DIR / name
        shutil.copy2(src, dst)
        packaged.append((r.get("job_url", ""), str(dst), r.get("title", ""), r.get("score", "")))

    with CSV_OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Job URL", "RESUME FULL PATH", "JOB ROLE"])
        for url, path, title, _s in packaged:
            w.writerow([url, path, title])

    print(f"packaged {len(packaged)} resumes -> {OUT_DIR}")
    print(f"csv -> {CSV_OUT}")
    for url, path, title, score in packaged:
        print(f"  [{score}] {title[:44]:<46} {Path(path).name}")
    for url, why in skipped:
        print(f"  SKIP ({why}): {url[-60:]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
