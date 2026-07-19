from goalkeeper.calibration import calibrate_objective
from goalkeeper.models import VerificationStep
from goalkeeper.verification import run_verification_plan


def make_contract_with_steps(tmp_path, steps):
    contract = calibrate_objective("add search filters", cwd=tmp_path)
    contract.verification_plan = steps
    return contract


def test_run_verification_plan_records_real_outcomes(tmp_path):
    contract = make_contract_with_steps(
        tmp_path,
        [
            VerificationStep(
                id="V1",
                description="Inspect workspace manually.",
                command=None,
                expected_signal="Context identified.",
            ),
            VerificationStep(
                id="V2",
                description="Echo a marker.",
                command="echo ok",
                expected_signal="ok",
            ),
            VerificationStep(
                id="V3",
                description="Always fails.",
                command="exit 3",
                expected_signal="never",
            ),
        ],
    )

    results = run_verification_plan(contract, cwd=tmp_path)

    by_id = {result.step_id: result for result in results}
    assert by_id["V1"].outcome == "not_run"
    assert not by_id["V1"].executed
    assert by_id["V2"].outcome == "passed"
    assert "ok" in by_id["V2"].summary
    assert by_id["V3"].outcome == "failed"
    assert by_id["V3"].error_signature
    assert contract.verification_plan[1].last_result.startswith("passed")
    assert contract.verification_plan[2].last_result.startswith("failed")


def test_run_verification_plan_step_filter(tmp_path):
    contract = make_contract_with_steps(
        tmp_path,
        [
            VerificationStep(id="V1", description="Echo.", command="echo one", expected_signal="one"),
            VerificationStep(id="V2", description="Echo.", command="echo two", expected_signal="two"),
        ],
    )

    results = run_verification_plan(contract, cwd=tmp_path, step_ids=["V2"])

    assert [result.step_id for result in results] == ["V2"]
    assert results[0].outcome == "passed"
    assert contract.verification_plan[0].last_result is None


def test_success_summary_prefers_stdout_over_nonfatal_stderr(tmp_path, monkeypatch):
    class Completed:
        returncode = 0
        stdout = "2 files changed, 9 insertions\n"
        stderr = "line-ending warning\n"

    monkeypatch.setattr("goalkeeper.verification.subprocess.run", lambda *args, **kwargs: Completed())
    contract = make_contract_with_steps(
        tmp_path,
        [VerificationStep(id="V1", description="Diff.", command="git diff --stat")],
    )

    result = run_verification_plan(contract, cwd=tmp_path)[0]

    assert result.outcome == "passed"
    assert result.summary == "2 files changed, 9 insertions"
