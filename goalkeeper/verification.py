from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import GoalkeeperContract


DEFAULT_STEP_TIMEOUT_SECONDS = 600.0
_SUMMARY_MAX_CHARS = 200
_SIGNATURE_MAX_CHARS = 120


@dataclass
class VerificationOutcome:
    step_id: str
    description: str
    command: str | None
    outcome: str  # "passed" | "failed" | "not_run"
    summary: str
    error_signature: str | None = None

    @property
    def executed(self) -> bool:
        return self.command is not None and self.outcome != "not_run"


def run_verification_plan(
    contract: GoalkeeperContract,
    *,
    cwd: str | Path | None = None,
    step_ids: list[str] | None = None,
    timeout: float = DEFAULT_STEP_TIMEOUT_SECONDS,
) -> list[VerificationOutcome]:
    """Run the contract's verification plan commands and record real outcomes.

    Steps without a command are reported as manual (`not_run`). Each executed
    step's `last_result` is updated on the contract in place; the caller is
    responsible for persisting the contract.
    """
    root = Path(cwd or Path.cwd()).expanduser().resolve()
    wanted = {step.strip() for step in step_ids or [] if step.strip()}
    outcomes: list[VerificationOutcome] = []
    for step in contract.verification_plan:
        if wanted and step.id not in wanted:
            continue
        if not step.command:
            outcomes.append(
                VerificationOutcome(
                    step_id=step.id,
                    description=step.description,
                    command=None,
                    outcome="not_run",
                    summary="Manual step: no command attached.",
                )
            )
            continue
        outcome = _run_step(step.id, step.description, step.command, root, timeout)
        step.last_result = f"{outcome.outcome}: {outcome.summary}"
        outcomes.append(outcome)
    return outcomes


def _run_step(
    step_id: str,
    description: str,
    command: str,
    root: Path,
    timeout: float,
) -> VerificationOutcome:
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return VerificationOutcome(
            step_id=step_id,
            description=description,
            command=command,
            outcome="failed",
            summary=f"Timed out after {timeout:.0f}s.",
            error_signature=_truncate(f"timeout: {command}", _SIGNATURE_MAX_CHARS),
        )
    except OSError as exc:
        return VerificationOutcome(
            step_id=step_id,
            description=description,
            command=command,
            outcome="failed",
            summary=f"Could not run command: {exc}",
            error_signature=_truncate(f"oserror: {command}", _SIGNATURE_MAX_CHARS),
        )
    tail = _last_meaningful_line(result.stdout, result.stderr)
    if result.returncode == 0:
        return VerificationOutcome(
            step_id=step_id,
            description=description,
            command=command,
            outcome="passed",
            summary=_truncate(tail or "exit 0", _SUMMARY_MAX_CHARS),
        )
    return VerificationOutcome(
        step_id=step_id,
        description=description,
        command=command,
        outcome="failed",
        summary=_truncate(tail or f"exit {result.returncode}", _SUMMARY_MAX_CHARS),
        error_signature=_truncate(
            f"exit {result.returncode}: {tail or command}", _SIGNATURE_MAX_CHARS
        ),
    )


def _last_meaningful_line(stdout: str, stderr: str) -> str:
    for stream in (stderr, stdout):
        lines = [line.strip() for line in (stream or "").splitlines() if line.strip()]
        if lines:
            return lines[-1]
    return ""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
