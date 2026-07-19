from goalkeeper.calibration import calibrate_objective
from goalkeeper.contract import (
    DEFAULT_MAX_GOAL_OBJECTIVE_CHARS,
    paste_ready_goal,
    render_contract,
)


def test_contract_generation_includes_required_sections(tmp_path):
    contract = calibrate_objective(
        "refactor billing module without breaking public API",
        cwd=tmp_path,
    )

    rendered = render_contract(contract)

    assert "<goalkeeper_contract id=" in rendered
    assert "User objective:" in rendered
    assert "Normalized objective:" in rendered
    assert "Acceptance criteria:" in rendered
    assert "Verification plan:" in rendered
    assert "Loop policy:" in rendered
    assert "Wait/defer policy:" in rendered
    assert "Checkpoint rule:" in rendered
    assert "Required checkpoint command:" in rendered
    assert f"goalkeeper checkpoint --contract-id {contract.id}" in rendered
    assert "Do not end a goal continuation turn without either:" in rendered
    assert "Stale context defense:" in rendered
    assert "Completion rule:" in rendered
    assert "Do not repeat the same failing command" in rendered
    assert "Pause/defer and record the wake condition" in rendered


def test_contract_includes_reanchor_and_verify_rules(tmp_path):
    contract = calibrate_objective("add audit logging", cwd=tmp_path)

    rendered = render_contract(contract)

    assert "Verification rule:" in rendered
    assert f"goalkeeper verify --contract-id {contract.id}" in rendered
    assert "Re-anchor rule:" in rendered
    assert f".goalkeeper/contracts/{contract.id}.json" in rendered
    assert "scope drift" in rendered
    assert "Record a checkpoint at least every" in rendered


def test_paste_ready_goal_below_limit_contains_inline_contract(tmp_path):
    contract = calibrate_objective("add audit logging", cwd=tmp_path)
    max_chars = len(f"/goal {render_contract(contract)}") + 1

    prompt = paste_ready_goal(
        contract,
        contract_path=tmp_path / "contract.json",
        max_chars=max_chars,
    )

    assert prompt.startswith("/goal ")
    assert contract.id in prompt


def test_paste_ready_goal_above_default_limit_uses_file_reference(tmp_path):
    contract = calibrate_objective("add audit logging", cwd=tmp_path)

    prompt = paste_ready_goal(contract, contract_path=tmp_path / "contract.json")

    assert DEFAULT_MAX_GOAL_OBJECTIVE_CHARS == 4000
    assert prompt.startswith("/goal Read the Goalkeeper contract at ")
    assert str((tmp_path / "contract.json").resolve()) in prompt
