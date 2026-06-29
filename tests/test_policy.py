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
