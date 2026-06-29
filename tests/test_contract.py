from goalkeeper.calibration import calibrate_objective
from goalkeeper.contract import paste_ready_goal, render_contract


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


def test_paste_ready_goal_contains_goal_prefix(tmp_path):
    contract = calibrate_objective("add audit logging", cwd=tmp_path)

    prompt = paste_ready_goal(contract, contract_path=tmp_path / "contract.json")

    assert prompt.startswith("/goal ")
    assert contract.id in prompt
