import json
from types import SimpleNamespace

from goalkeeper.calibration import calibrate_objective
from goalkeeper.models import Decision
from goalkeeper.policy import PolicyEvaluation
from goalkeeper.proof import (
    ScopeProofOutcome,
    evaluate_proof_gate,
    run_scopeproof,
    supported_criteria_closures,
)
from goalkeeper.verification import VerificationOutcome


def _verification(step_id="V3", outcome="passed", command="pytest -q"):
    return VerificationOutcome(
        step_id=step_id,
        description="Run tests.",
        command=command,
        outcome=outcome,
        summary="tests passed" if outcome == "passed" else "tests failed",
        error_signature=None if outcome == "passed" else "exit 1: tests failed",
    )


def _scope(status="PASS", *, blocks_gate=False):
    return ScopeProofOutcome(
        status=status,
        summary=f"{status}: scope report",
        command="scopeproof check --base HEAD --format json",
        blocks_gate=blocks_gate,
    )


def test_run_scopeproof_parses_json_report_even_when_gate_exits_nonzero(tmp_path, monkeypatch):
    report = {
        "overall_status": "FAIL",
        "changed_files": [{"path": "src/outside.py", "status": "A"}],
        "results": [
            {
                "check_id": "scope_escape",
                "status": "FAIL",
                "summary": "One file escaped scope.",
                "issues": [{"path": "src/outside.py", "message": "outside allowed paths"}],
            }
        ],
    }
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=1, stdout=json.dumps(report), stderr="")

    contract = calibrate_objective("add health endpoint", cwd=tmp_path)
    monkeypatch.setattr("goalkeeper.proof._resolve_scopeproof_command", lambda value: ["scopeproof"])
    monkeypatch.setattr("goalkeeper.proof.subprocess.run", fake_run)

    outcome = run_scopeproof(
        contract,
        cwd=tmp_path,
        allowed_paths=["src/health/**"],
        temp_root=tmp_path / "temp",
    )

    assert outcome.status == "FAIL"
    assert outcome.blocks_gate is True
    assert outcome.changed_files == ["src/outside.py"]
    assert outcome.config_source == "generated"
    assert outcome.task_source == "generated"
    assert "--fail-on-warn" in calls[0][0]


def test_supported_closures_require_behavioral_evidence_for_ac2(tmp_path):
    contract = calibrate_objective("add health endpoint", cwd=tmp_path)

    only_diff = [_verification(step_id="V2", command="git diff --stat")]
    assert supported_criteria_closures(contract, only_diff, _scope()) == ["AC3"]

    with_tests = [*only_diff, _verification()]
    assert supported_criteria_closures(
        contract,
        with_tests,
        _scope(),
        requested=["AC1"],
    ) == ["AC1", "AC2", "AC3"]


def test_proof_gate_completes_only_after_all_criteria_have_evidence(tmp_path):
    contract = calibrate_objective("add health endpoint", cwd=tmp_path)
    for criterion in contract.acceptance_criteria:
        criterion.status = "satisfied"

    gate = evaluate_proof_gate(
        contract,
        [_verification()],
        _scope(),
        PolicyEvaluation(Decision.CONTINUE, 7, explanation="evidence is current"),
    )

    assert gate.label == "COMPLETE"
    assert gate.decision == Decision.COMPLETE_CANDIDATE


def test_proof_gate_replans_on_verification_failure(tmp_path):
    contract = calibrate_objective("add health endpoint", cwd=tmp_path)

    gate = evaluate_proof_gate(
        contract,
        [_verification(outcome="failed")],
        _scope(),
        PolicyEvaluation(Decision.CONTINUE, 0),
    )

    assert gate.label == "REPLAN"
    assert gate.decision == Decision.REPLAN_REQUIRED
    assert any(signal.kind == "proof_verification_failed" for signal in gate.signals)


def test_proof_gate_pauses_when_scopeproof_is_unavailable(tmp_path):
    contract = calibrate_objective("add health endpoint", cwd=tmp_path)
    unavailable = ScopeProofOutcome(
        status="UNAVAILABLE",
        summary="ScopeProof is missing.",
        command="scopeproof check --base HEAD --format json",
        error="not found",
    )

    gate = evaluate_proof_gate(
        contract,
        [_verification()],
        unavailable,
        PolicyEvaluation(Decision.CONTINUE, 2),
    )

    assert gate.label == "PAUSE"
    assert gate.decision == Decision.PAUSE_RECOMMENDED
