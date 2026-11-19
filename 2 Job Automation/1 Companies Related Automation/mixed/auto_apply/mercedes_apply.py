"""Mercedes-Benz auto-applier (Workday & Taleo platforms)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .base import ApplicationResult, BaseApplier
from .registry import register_applier


@register_applier("mercedes")
class MercedesApplier(BaseApplier):
    company_id = "mercedes"
    display_name = "Mercedes-Benz"
    portal_name = "Workday / Taleo"

    def apply_one(
        self,
        job_url: str,
        resume_path: str | Path,
        letter_path: str | Path | None = None,
        dry_run: bool = True,
        headless: bool = False,
        **kwargs,
    ) -> ApplicationResult:
        resume_p = Path(resume_path).resolve()
        if not resume_p.exists():
            return ApplicationResult(
                company_id=self.company_id,
                job_url=job_url,
                status="FAILED",
                errors=[f"Resume not found: {resume_p}"],
            )

        merc_dir = self.workspace_root / "mercedes"
        is_taleo = "taleo.net" in job_url

        if is_taleo:
            script = merc_dir / "5_apply_taleo.py"
        else:
            script = merc_dir / "4_MERCEDES_job_apply.py"

        cmd = [
            sys.executable,
            str(script),
            "--url",
            job_url,
            "--resume",
            str(resume_p),
        ]
        if dry_run:
            cmd.append("--dry-run")
        else:
            cmd.append("--submit")
        if headless:
            cmd.append("--headless")

        print(f"[mercedes-apply] Running on {'Taleo' if is_taleo else 'Workday'} ({'DRY-RUN' if dry_run else 'SUBMIT'}) for {job_url}...")
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(merc_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                input="YES\n" if not dry_run else "",
                timeout=300,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            return ApplicationResult(
                company_id=self.company_id,
                job_url=job_url,
                status="TIMEOUT",
                resume_path=str(resume_p),
                errors=["Apply script timed out after 300s"],
            )

        status = "FAILED"
        if "SUCCESS" in out:
            status = "SUCCESS"
        elif "DRY_RUN" in out or "DRY_RUN_COMPLETE" in out:
            status = "DRY_RUN"
        elif "NEEDS_CREDENTIALS" in out or "LOGIN_REQUIRED" in out:
            status = "NEEDS_CREDENTIALS"
        elif "NEEDS_ATTENTION" in out:
            status = "NEEDS_ATTENTION"
        elif "BLOCKED" in out:
            status = "BLOCKED"

        return ApplicationResult(
            company_id=self.company_id,
            job_url=job_url,
            status=status,
            resume_path=str(resume_p),
            letter_path=str(letter_path) if letter_path else "",
            details={"output_tail": "\n".join(out.strip().splitlines()[-10:])},
        )
