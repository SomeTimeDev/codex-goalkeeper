from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from .ledger import GoalkeeperStore, utc_now
from .models import Checkpoint, Decision, GoalkeeperContract, LoopSignal
from .policy import PolicyEvaluation
from .verification import VerificationOutcome


DEFAULT_SCOPEPROOF_TIMEOUT_SECONDS = 120.0
PROOF_SCHEMA_VERSION = 1


@dataclass
class ScopeProofOutcome:
    status: str
    summary: str
    command: str
    exit_code: int | None = None
    config_source: str = "generated"
    task_source: str = "generated"
    changed_files: list[str] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    blocks_gate: bool = True

    @property
    def available(self) -> bool:
        return self.status not in {"UNAVAILABLE", "ERROR"}


@dataclass
class ProofGate:
    decision: Decision
    label: str
    reason: str
    signals: list[LoopSignal] = field(default_factory=list)


@dataclass
class ProofArtifactPaths:
    json_path: Path
    markdown_path: Path
    latest_json_path: Path


def run_scopeproof(
    contract: GoalkeeperContract,
    *,
    cwd: str | Path | None = None,
    base: str = "HEAD",
    head: str | None = None,
    config_path: str | Path | None = None,
    task_path: str | Path | None = None,
    allowed_paths: list[str] | None = None,
    forbidden_paths: list[str] | None = None,
    prefer_modify: list[str] | None = None,
    allow_warn: bool = False,
    scopeproof_bin: str | Path | None = None,
    timeout: float = DEFAULT_SCOPEPROOF_TIMEOUT_SECONDS,
    temp_root: str | Path | None = None,
) -> ScopeProofOutcome:
    root = Path(cwd or Path.cwd()).expanduser().resolve()
    command_prefix = _resolve_scopeproof_command(scopeproof_bin)
    command_label = _scopeproof_command_label(base, head)
    if command_prefix is None:
        return ScopeProofOutcome(
            status="UNAVAILABLE",
            summary=(
                "ScopeProof is not installed. Install the proof extra or provide "
                "--scopeproof-bin."
            ),
            command=command_label,
            error="scopeproof executable and Python module were not found",
            blocks_gate=True,
        )

    explicit_config = _resolve_optional_path(root, config_path)
    explicit_task = _resolve_optional_path(root, task_path)
    if explicit_config is not None and not explicit_config.exists():
        return _scopeproof_input_error(command_label, f"ScopeProof config not found: {explicit_config}")
    if explicit_task is not None and not explicit_task.exists():
        return _scopeproof_input_error(command_label, f"ScopeProof task file not found: {explicit_task}")

    project_config = explicit_config or root / "scopeproof.yml"
    project_task = explicit_task or root / ".scopeproof" / "task.yml"
    config_source = "project" if project_config.exists() else "generated"
    task_source = "project" if project_task.exists() else "generated"
    temp_parent = Path(temp_root).expanduser().resolve() if temp_root else None
    if temp_parent is not None:
        temp_parent.mkdir(parents=True, exist_ok=True)

    try:
        with tempfile.TemporaryDirectory(prefix="proofkeeper-", dir=temp_parent) as temp_dir:
            temp = Path(temp_dir)
            if not project_config.exists():
                project_config = temp / "scopeproof.yml"
                project_config.write_text(
                    json.dumps(_generated_scopeproof_config(contract), indent=2) + "\n",
                    encoding="utf-8",
                )
            if not project_task.exists():
                project_task = temp / "task.yml"
                project_task.write_text(
                    json.dumps(
                        _generated_scopeproof_task(
                            contract,
                            allowed_paths=allowed_paths or [],
                            forbidden_paths=forbidden_paths or [],
                            prefer_modify=prefer_modify or [],
                        ),
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )

            command = [
                *command_prefix,
                "check",
                "--config",
                str(project_config),
                "--task",
                str(project_task),
                "--base",
                base,
                "--goal",
                contract.normalized_objective,
                "--format",
                "json",
            ]
            if head:
                command.extend(["--head", head])
            if not allow_warn:
                command.append("--fail-on-warn")
            result = subprocess.run(
                command,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
    except subprocess.TimeoutExpired:
        return ScopeProofOutcome(
            status="ERROR",
            summary=f"ScopeProof timed out after {timeout:.0f}s.",
            command=command_label,
            config_source=config_source,
            task_source=task_source,
            error="scopeproof timeout",
            blocks_gate=True,
        )
    except OSError as exc:
        return ScopeProofOutcome(
            status="ERROR",
            summary=f"ScopeProof could not run: {exc}",
            command=command_label,
            config_source=config_source,
            task_source=task_source,
            error=str(exc),
            blocks_gate=True,
        )

    try:
        report = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        detail = _last_meaningful_line(result.stderr, result.stdout)
        return ScopeProofOutcome(
            status="ERROR",
            summary="ScopeProof did not return a valid JSON report.",
            command=command_label,
            exit_code=result.returncode,
            config_source=config_source,
            task_source=task_source,
            error=_truncate(detail or "invalid JSON output", 240),
            blocks_gate=True,
        )

    status = str(report.get("overall_status", "ERROR")).upper()
    if status not in {"PASS", "WARN", "FAIL"}:
        return ScopeProofOutcome(
            status="ERROR",
            summary=f"ScopeProof returned an unknown status: {status}",
            command=command_label,
            exit_code=result.returncode,
            config_source=config_source,
            task_source=task_source,
            report=report,
            error="unknown overall_status",
            blocks_gate=True,
        )
    checks = [item for item in report.get("results", []) if isinstance(item, dict)]
    changed_files = [
        str(item.get("path", ""))
        for item in report.get("changed_files", [])
        if isinstance(item, dict) and item.get("path")
    ]
    blocking_checks = [
        str(item.get("check_id", "unknown"))
        for item in checks
        if str(item.get("status", "")).upper() in {"WARN", "FAIL"}
    ]
    summary = f"{status}: {len(changed_files)} changed file(s), {len(checks)} check(s)"
    if blocking_checks:
        summary += f"; findings: {', '.join(blocking_checks)}"
    blocks_gate = status == "FAIL" or (status == "WARN" and not allow_warn)
    return ScopeProofOutcome(
        status=status,
        summary=summary,
        command=command_label,
        exit_code=result.returncode,
        config_source=config_source,
        task_source=task_source,
        changed_files=changed_files,
        checks=checks,
        report=report,
        error=_truncate(result.stderr.strip(), 240) or None,
        blocks_gate=blocks_gate,
    )


def supported_criteria_closures(
    contract: GoalkeeperContract,
    verification: list[VerificationOutcome],
    scopeproof: ScopeProofOutcome,
    *,
    requested: list[str] | None = None,
) -> list[str]:
    known = {criterion.id for criterion in contract.acceptance_criteria}
    requested_ids = _dedupe(requested or [])
    unknown = [criterion_id for criterion_id in requested_ids if criterion_id not in known]
    if unknown:
        raise ValueError(f"unknown acceptance criterion id(s): {', '.join(unknown)}")

    closures = list(requested_ids)
    behavioral = [item for item in verification if item.executed and _is_behavioral(item.command)]
    if behavioral and all(item.outcome == "passed" for item in behavioral) and "AC2" in known:
        closures.append("AC2")
    if scopeproof.status == "PASS" and "AC3" in known:
        closures.append("AC3")
    return _dedupe(closures)


def evaluate_proof_gate(
    contract: GoalkeeperContract,
    verification: list[VerificationOutcome],
    scopeproof: ScopeProofOutcome,
    policy: PolicyEvaluation,
) -> ProofGate:
    signals = list(policy.signals)
    failed_verification = [item for item in verification if item.outcome == "failed"]
    behavioral = [item for item in verification if item.executed and _is_behavioral(item.command)]

    if any(question.critical for question in contract.questions):
        signals.append(
            LoopSignal(
                kind="proof_pending_questions",
                severity="high",
                explanation="Critical contract questions remain unanswered.",
            )
        )
        return ProofGate(
            Decision.ASK_USER,
            "PAUSE",
            "Answer the critical contract questions before accepting proof.",
            signals,
        )

    if failed_verification:
        failed_ids = ", ".join(item.step_id for item in failed_verification)
        signals.append(
            LoopSignal(
                kind="proof_verification_failed",
                severity="high",
                explanation=f"Verification failed: {failed_ids}.",
                evidence=[item.error_signature or item.summary for item in failed_verification],
            )
        )
        return ProofGate(
            Decision.REPLAN_REQUIRED,
            "REPLAN",
            f"Fix failing verification step(s) {failed_ids} with a new hypothesis.",
            signals,
        )

    if scopeproof.available and scopeproof.blocks_gate:
        signals.extend(_scopeproof_signals(scopeproof))
        return ProofGate(
            Decision.REPLAN_REQUIRED,
            "REPLAN",
            f"ScopeProof blocked continuation: {scopeproof.summary}.",
            signals,
        )

    if not scopeproof.available:
        signals.append(
            LoopSignal(
                kind="proof_scopeproof_unavailable",
                severity="high",
                explanation=scopeproof.summary,
                evidence=[scopeproof.error] if scopeproof.error else [],
            )
        )
        return ProofGate(
            Decision.PAUSE_RECOMMENDED,
            "PAUSE",
            "Scope evidence is unavailable; install or repair ScopeProof before continuing.",
            signals,
        )

    if not behavioral:
        signals.append(
            LoopSignal(
                kind="proof_behavior_unverified",
                severity="high",
                explanation="No behavioral verification command was executed.",
            )
        )
        return ProofGate(
            Decision.PAUSE_RECOMMENDED,
            "PAUSE",
            "Add and run a behavioral verification command before continuing.",
            signals,
        )

    if policy.decision in {
        Decision.ASK_USER,
        Decision.REPLAN_REQUIRED,
        Decision.PAUSE_RECOMMENDED,
        Decision.DEFER_RECOMMENDED,
    }:
        return ProofGate(
            policy.decision,
            _gate_label(policy.decision),
            policy.explanation,
            signals,
        )

    if _all_criteria_satisfied(contract):
        return ProofGate(
            Decision.COMPLETE_CANDIDATE,
            "COMPLETE",
            "Behavioral verification and ScopeProof passed, and every criterion has evidence.",
            signals,
        )
    open_ids = [
        criterion.id for criterion in contract.acceptance_criteria if criterion.status != "satisfied"
    ]
    return ProofGate(
        Decision.CONTINUE,
        "CONTINUE",
        f"Proof passed; continue only toward open criteria: {', '.join(open_ids)}.",
        signals,
    )


def save_proof_artifacts(
    store: GoalkeeperStore,
    contract: GoalkeeperContract,
    checkpoint: Checkpoint,
    verification: list[VerificationOutcome],
    scopeproof: ScopeProofOutcome,
    gate: ProofGate,
    *,
    base: str,
    head: str | None,
) -> ProofArtifactPaths:
    proof_id = f"proof_{uuid4().hex[:10]}"
    proof_dir = store.storage_dir / "proofs" / contract.id
    proof_dir.mkdir(parents=True, exist_ok=True)
    json_path = proof_dir / f"{proof_id}.json"
    markdown_path = proof_dir / f"{proof_id}.md"
    latest_json_path = proof_dir / "latest.json"
    payload = {
        "schema_version": PROOF_SCHEMA_VERSION,
        "proof_id": proof_id,
        "contract_id": contract.id,
        "generated_at": utc_now(),
        "workspace": store.root.name,
        "git": {
            "base": base,
            "head": head,
            "commit": checkpoint.git_head,
            "changed_files": checkpoint.observed_changed_files,
        },
        "verification": {
            "status": _verification_status(verification),
            "steps": [asdict(item) for item in verification],
        },
        "scopeproof": {
            "status": scopeproof.status,
            "summary": scopeproof.summary,
            "command": scopeproof.command,
            "exit_code": scopeproof.exit_code,
            "config_source": scopeproof.config_source,
            "task_source": scopeproof.task_source,
            "changed_files": scopeproof.changed_files,
            "checks": scopeproof.checks,
            "error": scopeproof.error,
        },
        "acceptance_criteria": [asdict(item) for item in contract.acceptance_criteria],
        "checkpoint": checkpoint.to_dict(),
        "gate": {
            "decision": gate.label,
            "goalkeeper_decision": gate.decision.value,
            "reason": gate.reason,
        },
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    json_path.write_text(rendered, encoding="utf-8")
    latest_json_path.write_text(rendered, encoding="utf-8")
    markdown_path.write_text(_render_proof_markdown(payload), encoding="utf-8")
    return ProofArtifactPaths(json_path, markdown_path, latest_json_path)


def proof_exit_code(gate: ProofGate) -> int:
    if gate.label in {"CONTINUE", "COMPLETE"}:
        return 0
    if gate.label == "REPLAN":
        return 2
    return 3


def scopeproof_command_run(scopeproof: ScopeProofOutcome) -> tuple[str, str, str | None]:
    if scopeproof.status == "PASS":
        return "passed", scopeproof.summary, None
    if scopeproof.status == "WARN" and not scopeproof.blocks_gate:
        return "partial", scopeproof.summary, None
    signature = f"scopeproof:{scopeproof.status.lower()}"
    blocking = [
        str(item.get("check_id", "unknown"))
        for item in scopeproof.checks
        if str(item.get("status", "")).upper() in {"WARN", "FAIL"}
    ]
    if blocking:
        signature += ":" + ",".join(blocking)
    return "failed", scopeproof.summary, signature


def _resolve_scopeproof_command(scopeproof_bin: str | Path | None) -> list[str] | None:
    if scopeproof_bin:
        return [str(scopeproof_bin)]
    executable = shutil.which("scopeproof")
    if executable:
        return [executable]
    if importlib.util.find_spec("scopeproof") is not None:
        return [sys.executable, "-m", "scopeproof"]
    return None


def _resolve_optional_path(root: Path, value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _generated_scopeproof_config(contract: GoalkeeperContract) -> dict[str, Any]:
    return {
        "version": 1,
        "project": {
            "name": contract.id,
            "mission": contract.normalized_objective,
            "non_goals": contract.non_goals,
        },
        "paths": {
            "include": ["**/*"],
            "exclude": [
                ".git/**",
                ".goalkeeper/**",
                ".venv/**",
                "venv/**",
                "node_modules/**",
                "dist/**",
                "build/**",
                "__pycache__/**",
                ".pytest_cache/**",
            ],
        },
        "rules": {
            "max_changed_files_per_task": 12,
            "max_new_files_per_task": 3,
            "max_new_public_symbols_per_task": 6,
            "duplicate_symbol_similarity": 0.82,
            "fail_on_scope_escape": True,
            "fail_on_module_sprawl": True,
            "fail_on_duplicate_symbol": True,
            "fail_on_orphan_new_file": True,
            "fail_on_public_api_growth": True,
            "fail_on_changed_file_growth": True,
        },
    }


def _generated_scopeproof_task(
    contract: GoalkeeperContract,
    *,
    allowed_paths: list[str],
    forbidden_paths: list[str],
    prefer_modify: list[str],
) -> dict[str, Any]:
    return {
        "goal": contract.normalized_objective,
        "allowed_paths": _dedupe(allowed_paths),
        "forbidden_paths": _dedupe(forbidden_paths),
        "prefer_modify": _dedupe(prefer_modify),
        "expected_behavior": [criterion.description for criterion in contract.acceptance_criteria],
        "verification": [
            step.command for step in contract.verification_plan if step.command is not None
        ],
    }


def _scopeproof_input_error(command: str, message: str) -> ScopeProofOutcome:
    return ScopeProofOutcome(
        status="ERROR",
        summary=message,
        command=command,
        error=message,
        blocks_gate=True,
    )


def _scopeproof_command_label(base: str, head: str | None) -> str:
    label = f"scopeproof check --base {base}"
    if head:
        label += f" --head {head}"
    return f"{label} --format json"


def _scopeproof_signals(scopeproof: ScopeProofOutcome) -> list[LoopSignal]:
    signals: list[LoopSignal] = []
    for item in scopeproof.checks:
        status = str(item.get("status", "")).upper()
        if status not in {"WARN", "FAIL"}:
            continue
        issues = item.get("issues", [])
        evidence = []
        if isinstance(issues, list):
            evidence = [
                str(issue.get("path") or issue.get("message") or "scope finding")
                for issue in issues
                if isinstance(issue, dict)
            ]
        signals.append(
            LoopSignal(
                kind=f"scopeproof_{item.get('check_id', 'finding')}",
                severity="high" if status == "FAIL" else "medium",
                explanation=str(item.get("summary") or scopeproof.summary),
                evidence=evidence,
            )
        )
    if not signals:
        signals.append(
            LoopSignal(
                kind="scopeproof_blocked",
                severity="high",
                explanation=scopeproof.summary,
            )
        )
    return signals


def _is_behavioral(command: str | None) -> bool:
    if not command:
        return False
    normalized = " ".join(command.lower().split())
    return not normalized.startswith(("git diff", "git status", "git show"))


def _all_criteria_satisfied(contract: GoalkeeperContract) -> bool:
    return bool(contract.acceptance_criteria) and all(
        criterion.status == "satisfied" for criterion in contract.acceptance_criteria
    )


def _gate_label(decision: Decision) -> str:
    if decision == Decision.COMPLETE_CANDIDATE:
        return "COMPLETE"
    if decision == Decision.REPLAN_REQUIRED:
        return "REPLAN"
    if decision in {
        Decision.PAUSE_RECOMMENDED,
        Decision.PAUSED,
        Decision.DEFER_RECOMMENDED,
        Decision.ASK_USER,
    }:
        return "PAUSE"
    return "CONTINUE"


def _verification_status(verification: list[VerificationOutcome]) -> str:
    executed = [item for item in verification if item.executed]
    if any(item.outcome == "failed" for item in executed):
        return "FAIL"
    if not any(_is_behavioral(item.command) for item in executed):
        return "NOT_PROVEN"
    return "PASS"


def _render_proof_markdown(payload: dict[str, Any]) -> str:
    gate = payload["gate"]
    verification = payload["verification"]
    scopeproof = payload["scopeproof"]
    criteria = payload["acceptance_criteria"]
    lines = [
        "# Proofkeeper Evidence Bundle",
        "",
        f"**Decision:** {gate['decision']}",
        "",
        gate["reason"],
        "",
        "## Verification",
        "",
        f"Overall: **{verification['status']}**",
        "",
    ]
    for step in verification["steps"]:
        marker = {"passed": "PASS", "failed": "FAIL"}.get(step["outcome"], "SKIP")
        lines.append(f"- {marker} {step['step_id']}: {step['summary']}")
    lines.extend(
        [
            "",
            "## ScopeProof",
            "",
            f"Overall: **{scopeproof['status']}**",
            "",
            f"- {scopeproof['summary']}",
            f"- Config: {scopeproof['config_source']}",
            f"- Task boundary: {scopeproof['task_source']}",
        ]
    )
    for check in scopeproof["checks"]:
        lines.append(
            f"- {str(check.get('status', 'UNKNOWN')).upper()} "
            f"{check.get('check_id', 'unknown')}: {check.get('summary', '')}"
        )
    lines.extend(["", "## Acceptance Criteria", ""])
    for criterion in criteria:
        lines.append(
            f"- {criterion['id']} [{criterion['status']}]: {criterion['description']}"
        )
    lines.extend(
        [
            "",
            "## Reproduce",
            "",
            f"`{scopeproof['command']}`",
            "",
        ]
    )
    return "\n".join(lines)


def _last_meaningful_line(*streams: str) -> str:
    for stream in streams:
        lines = [line.strip() for line in (stream or "").splitlines() if line.strip()]
        if lines:
            return lines[-1]
    return ""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result
