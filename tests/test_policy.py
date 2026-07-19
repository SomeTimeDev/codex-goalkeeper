from datetime import UTC, datetime

from goalkeeper.calibration import calibrate_objective
from goalkeeper.ledger import new_checkpoint_id, utc_now
from goalkeeper.models import Checkpoint, CommandRun, Decision
from goalkeeper.policy import evaluate_policy


def make_contract(tmp_path):
    return calibrate_objective(
        "refactor billing module without breaking public API",
        cwd=tmp_path,
        max_no_progress_turns=3,
        max_same_error_retries=2,
    )


def cp(contract, **kwargs):
    data = {
        "id": new_checkpoint_id(),
        "contract_id": contract.id,
        "timestamp": utc_now(),
    }
    data.update(kwargs)
    return Checkpoint(**data)


def test_repeated_same_error_triggers_replan(tmp_path):
    contract = make_contract(tmp_path)
    checkpoints = [
        cp(
            contract,
            commands_run=[
                CommandRun(
                    command="pytest tests/billing",
                    outcome="failed",
                    error_signature="ImportError: billing.api",
                )
            ],
        ),
        cp(
            contract,
            commands_run=[
                CommandRun(
                    command="pytest tests/billing",
                    outcome="failed",
                    error_signature="ImportError: billing.api",
                )
            ],
        ),
    ]

    evaluation = evaluate_policy(contract, checkpoints)

    assert evaluation.decision == Decision.REPLAN_REQUIRED
    assert evaluation.same_error_retries == 2


def test_no_evidence_threshold_triggers_pause(tmp_path):
    contract = make_contract(tmp_path)
    checkpoints = [
        cp(contract, claimed_progress="I will inspect next"),
        cp(contract, claimed_progress="Still planning"),
        cp(contract, claimed_progress="No result yet"),
    ]

    evaluation = evaluate_policy(contract, checkpoints)

    assert evaluation.decision == Decision.PAUSE_RECOMMENDED
    assert evaluation.no_evidence_streak == 3


def test_waiting_only_checkpoints_trigger_defer(tmp_path):
    contract = make_contract(tmp_path)
    checkpoints = [
        cp(contract, claimed_progress="Waiting for CI", waiting_on="CI"),
        cp(contract, claimed_progress="Still waiting for CI", waiting_on="CI"),
    ]

    evaluation = evaluate_policy(contract, checkpoints)

    assert evaluation.decision == Decision.DEFER_RECOMMENDED
    assert evaluation.waiting_streak == 2


def test_new_evidence_resets_no_progress_risk(tmp_path):
    contract = make_contract(tmp_path)
    checkpoints = [
        cp(contract, claimed_progress="Planning only"),
        cp(contract, claimed_progress="Inspected code", new_evidence=["found billing entrypoint"]),
        cp(contract, claimed_progress="Next action selected"),
    ]

    evaluation = evaluate_policy(contract, checkpoints)

    assert evaluation.no_evidence_streak == 1
    assert evaluation.decision != Decision.PAUSE_RECOMMENDED


def test_criterion_closed_produces_positive_progress(tmp_path):
    contract = make_contract(tmp_path)
    checkpoints = [
        cp(
            contract,
            claimed_progress="Closed implementation criterion",
            new_evidence=["diff reviewed"],
            criteria_closed=["AC1"],
        )
    ]

    evaluation = evaluate_policy(contract, checkpoints)

    assert evaluation.progress_score > 0
    assert evaluation.decision == Decision.CONTINUE


def test_alternating_error_signatures_trigger_replan(tmp_path):
    contract = make_contract(tmp_path)

    def failing(signature):
        return cp(
            contract,
            claimed_progress="Retried the failing command",
            commands_run=[
                CommandRun(command="pytest", outcome="failed", error_signature=signature)
            ],
        )

    checkpoints = [failing("error A"), failing("error B"), failing("error A"), failing("error B")]

    evaluation = evaluate_policy(contract, checkpoints)

    assert evaluation.decision == Decision.REPLAN_REQUIRED
    assert evaluation.same_error_retries >= 2


def test_activity_without_criteria_movement_triggers_drift_replan(tmp_path):
    contract = make_contract(tmp_path)
    checkpoints = [
        cp(
            contract,
            claimed_progress=f"Edited helper {index}",
            new_evidence=[f"inspection note {index}"],
            changed_files=[f"src/file{index}.py"],
        )
        for index in range(5)
    ]

    evaluation = evaluate_policy(contract, checkpoints)

    assert evaluation.decision == Decision.REPLAN_REQUIRED
    assert evaluation.criteria_stall_streak == 5
    assert any(signal.kind == "criteria_stalled" for signal in evaluation.signals)


def test_stale_ledger_on_active_contract_asks_user(tmp_path):
    contract = make_contract(tmp_path)
    contract.status = "active"
    checkpoints = [
        cp(
            contract,
            timestamp="2026-07-05T09:00:00Z",
            claimed_progress="Edited file",
            new_evidence=["inspection note"],
        )
    ]
    now = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)

    evaluation = evaluate_policy(contract, checkpoints, now=now)

    assert evaluation.decision == Decision.ASK_USER
    assert any(signal.kind == "checkpoint_gap" for signal in evaluation.signals)
    assert evaluation.checkpoint_gap_minutes is not None
    assert evaluation.checkpoint_gap_minutes > 45


def test_empty_ledger_on_old_active_contract_asks_user(tmp_path):
    contract = make_contract(tmp_path)
    contract.status = "active"
    contract.updated_at = "2026-07-05T09:00:00Z"
    now = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)

    evaluation = evaluate_policy(contract, [], now=now)

    assert evaluation.decision == Decision.ASK_USER
    assert any(signal.kind == "checkpoint_gap" for signal in evaluation.signals)


def test_paused_contract_does_not_report_checkpoint_gap(tmp_path):
    contract = make_contract(tmp_path)
    contract.status = "paused"
    contract.updated_at = "2026-07-05T09:00:00Z"
    now = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)

    evaluation = evaluate_policy(contract, [], now=now)

    assert evaluation.decision == Decision.CONTINUE
    assert not evaluation.signals


def test_unverified_file_claim_is_flagged(tmp_path):
    contract = make_contract(tmp_path)
    checkpoints = [
        cp(
            contract,
            claimed_progress="Initial inspection",
            new_evidence=["context gathered"],
            git_head="abc123",
            observed_changed_files=[],
        ),
        cp(
            contract,
            claimed_progress="Edited billing service",
            new_evidence=["claimed edit"],
            changed_files=["billing/service.py"],
            git_head="abc123",
            observed_changed_files=[],
        ),
    ]

    evaluation = evaluate_policy(contract, checkpoints)

    assert any(signal.kind == "unverified_file_claim" for signal in evaluation.signals)


def test_supported_file_claim_is_not_flagged(tmp_path):
    contract = make_contract(tmp_path)
    checkpoints = [
        cp(
            contract,
            claimed_progress="Initial inspection",
            new_evidence=["context gathered"],
            git_head="abc123",
            observed_changed_files=[],
        ),
        cp(
            contract,
            claimed_progress="Edited billing service",
            new_evidence=["real edit"],
            changed_files=["billing\\service.py"],
            git_head="abc123",
            observed_changed_files=["billing/service.py"],
        ),
    ]

    evaluation = evaluate_policy(contract, checkpoints)

    assert not any(signal.kind == "unverified_file_claim" for signal in evaluation.signals)
