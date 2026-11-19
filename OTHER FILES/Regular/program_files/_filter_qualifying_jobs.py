"""Apply the reviewed student/internship + technical-domain keep list."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
INPUT_CSV = OUTPUT_DIR / "._workweek_manual_review.csv"
OUTPUT_CSV = OUTPUT_DIR / "2_filted_jobs.csv"

# Reviewed row numbers (1-based) in the 230-row workweek filter output.
# Rows must be student/internship roles AND have relevant technical duties.
# Use a stable, separately generated date/language-filtered snapshot as input.
KEEP_ROW_NUMBERS = {
    2, 4, 5, 13, 18, 19, 20, 21, 23, 28, 31, 32, 36,
    49, 50, 51, 69, 85, 136, 137,
    154, 155, 156, 158, 160, 161, 162, 164, 166, 169,
    173, 176, 178, 180, 181, 182, 185, 186, 187, 189,
    191, 193, 194, 198, 200, 201, 202, 205, 209, 210,
    212, 214, 216, 217, 218, 220, 221, 224, 227, 228, 230,
}


def main() -> int:
    if not INPUT_CSV.exists():
        raise SystemExit(f"manual review input not found: {INPUT_CSV}; rebuild the workweek snapshot before reapplying the keep list")

    jobs = pd.read_csv(INPUT_CSV)
    if len(jobs) != 230:
        raise SystemExit(
            f"expected reviewed 230-row input; found {len(jobs)} rows, refusing to apply stale row numbers"
        )

    row_numbers = sorted(KEEP_ROW_NUMBERS)
    if not row_numbers or row_numbers[-1] > len(jobs):
        raise SystemExit("keep list is empty or contains a row number outside the input")

    kept = jobs.iloc[[row_number - 1 for row_number in row_numbers]].reset_index(drop=True)
    kept.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    INPUT_CSV.unlink()
    print(
        f"[MANUAL-FILTER] kept {len(kept)}/{len(jobs)} individually reviewed "
        f"student/intern technical roles -> {OUTPUT_CSV}"
    )
    return len(kept)


if __name__ == "__main__":
    raise SystemExit(main())
