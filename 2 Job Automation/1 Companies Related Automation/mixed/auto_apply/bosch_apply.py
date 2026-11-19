"""Bosch auto-applier (SmartRecruiters platform)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from .base import ApplicationResult, BaseApplier
from .registry import register_applier


@register_applier("bosch")
class BoschApplier(BaseApplier):
    company_id = "bosch"
    display_name = "Bosch Group"
    portal_name = "SmartRecruiters"

    def apply_one(
        self,
        job_url: str,
        resume_path: str | Path,
        letter_path: str | Path | None = None,
        dry_run: bool = True,
        headless: bool = False,
        captcha_wait: int = 45,
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

        bosch_dir = self.workspace_root / "1_BOSCH"
        script = bosch_dir / "3_bosch_job_apply.py"

        cmd = [
            sys.executable,
            str(script),
            "--url",
            job_url,
            "--resume",
            str(resume_p),
            "--wait-after-captcha",
            str(captcha_wait),
        ]
        if dry_run:
            cmd.append("--dry-run")
        else:
            cmd.append("--submit")
        if headless:
            cmd.append("--headless")

        print(f"[bosch-apply] Executing {'DRY-RUN' if dry_run else 'SUBMIT'} for {job_url}...")
        try:
            # We supply YES\n for submission confirmations if required
            proc = subprocess.run(
                cmd,
                cwd=str(bosch_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                input="YES\n" if not dry_run else "",
                timeout=300,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired as exc:
            return ApplicationResult(
                company_id=self.company_id,
                job_url=job_url,
                status="TIMEOUT",
                resume_path=str(resume_p),
                errors=["Apply script timed out after 300s"],
            )

        status = "FAILED"
        if "Final status: SUCCESS" in out:
            status = "SUCCESS"
        elif "DRY_RUN_COMPLETE" in out or "Final status: DRY_RUN" in out:
            status = "DRY_RUN"
        elif "CAPTCHA_DETECTED" in out:
            status = "CAPTCHA_DETECTED"
        elif "UNKNOWN_FORM" in out:
            status = "UNKNOWN_FORM"

        return ApplicationResult(
            company_id=self.company_id,
            job_url=job_url,
            status=status,
            resume_path=str(resume_p),
            letter_path=str(letter_path) if letter_path else "",
            details={"output_tail": "\n".join(out.strip().splitlines()[-10:])},
        )
