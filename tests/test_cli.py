import json
from types import SimpleNamespace

from goalkeeper.calibration import calibrate_objective
from goalkeeper.cli import main
from goalkeeper.codex_adapter import PauseGoalResult, StartGoalResult
from goalkeeper.ledger import GoalkeeperStore, new_checkpoint_id, utc_now
from goalkeeper.models import Checkpoint


def _first_contract_id(tmp_path):
    contracts = sorted((tmp_path / ".goalkeeper" / "contracts").glob("*.json"))
    assert contracts
    return json.loads(contracts[0].read_text(encoding="utf-8"))["id"]


def test_prepare_creates_contract(tmp_path, capsys):
    result = main(["prepare", "add health endpoint", "--cwd", str(tmp_path)])

    output = capsys.readouterr().out
    assert result == 0
    assert "Goalkeeper contract prepared" in output
    assert (tmp_path / ".goalkeeper" / "contracts").exists()


def test_status_reads_contract(tmp_path, capsys):
    assert main(["prepare", "add health endpoint", "--cwd", str(tmp_path)]) == 0
    contract_id = _first_contract_id(tmp_path)

    result = main(["status", "--contract-id", contract_id, "--cwd", str(tmp_path)])

    output = capsys.readouterr().out
    assert result == 0
    assert contract_id in output
    assert "Loop risk:" in output


def test_checkpoint_appends_ledger(tmp_path, capsys):
    assert main(["prepare", "add health endpoint", "--cwd", str(tmp_path)]) == 0
    contract_id = _first_contract_id(tmp_path)

    result = main(
        [
            "checkpoint",
            "--contract-id",
            contract_id,
            "--cwd",
            str(tmp_path),
            "--claimed-progress",
            "Implemented endpoint",
            "--evidence",
            "pytest passed",
            "--criteria-closed",
            "AC1",
            "--command",
            "pytest",
            "--outcome",
            "passed",
            "--next-action",
            "Review diff",
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "Checkpoint added:" in output
    assert (tmp_path / ".goalkeeper" / "ledgers" / f"{contract_id}.jsonl").exists()


def test_watch_once_without_sdk_prints_manual_instructions(tmp_path, capsys):
    assert main(["prepare", "add health endpoint", "--cwd", str(tmp_path)]) == 0
    contract_id = _first_contract_id(tmp_path)

    result = main(["watch", "--contract-id", contract_id, "--cwd", str(tmp_path), "--once"])

    output = capsys.readouterr().out
    assert result == 0
    assert "Automatic watch is unavailable" in output


def test_doctor_does_not_crash(tmp_path, capsys):
    result = main(["doctor", "--cwd", str(tmp_path)])

    output = capsys.readouterr().out
    assert result == 0
    assert "Goalkeeper doctor" in output


def test_watch_ledger_auto_pause_calls_app_server_adapter(tmp_path, capsys, monkeypatch):
    calls = []

    class FakeAppServerAdapter:
        def __init__(self, cwd=None):
            self.cwd = cwd

        def available(self):
            return True

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def get_goal(self, thread_id):
            return SimpleNamespace(
                thread_id=thread_id,
                status="active",
                tokens_used=0,
                token_budget=None,
            )

        def pause_goal(self, thread_id):
            calls.append(thread_id)
            return PauseGoalResult(True, True, "paused by fake app-server")

    monkeypatch.setattr("goalkeeper.cli.CodexAppServerJsonRpcAdapter", FakeAppServerAdapter)
    store = GoalkeeperStore(tmp_path)
    contract = calibrate_objective("add health endpoint", cwd=tmp_path)
    contract.thread_id = "thread_123"
    store.save_contract(contract)
    for text in ("Planning", "Still planning", "No evidence yet"):
        store.append_checkpoint(
            Checkpoint(
                id=new_checkpoint_id(),
                contract_id=contract.id,
                timestamp=utc_now(),
                claimed_progress=text,
            )
        )

    result = main(
        [
            "watch",
            "--contract-id",
            contract.id,
            "--cwd",
            str(tmp_path),
            "--once",
            "--auto-pause",
            "--true-goal",
        ]
    )

    output = capsys.readouterr().out
    updated = store.load_contract(contract.id)
    checkpoints = store.read_checkpoints(contract.id)
    assert result == 0
    assert calls == ["thread_123"]
    assert updated.status == "paused"
    assert checkpoints[-1].decision.value == "paused"
    assert "Recorded auto-pause checkpoint" in output
    assert "pause_recommended" in output


def test_attach_true_goal_sets_goal_and_persists_thread(tmp_path, capsys, monkeypatch):
    calls = []

    class FakeAppServerAdapter:
        def __init__(self, cwd=None):
            self.cwd = cwd

        def start_goal(self, thread_id, objective, token_budget=None):
            calls.append((thread_id, objective, token_budget, self.cwd))
            return StartGoalResult(
                True,
                True,
                "fake true goal attached",
                goal_id=thread_id,
                thread_id=thread_id,
                mode="true_goal",
                final_response="thread_id=thread_123, status=active",
            )

    monkeypatch.setattr("goalkeeper.cli.CodexAppServerJsonRpcAdapter", FakeAppServerAdapter)
    store = GoalkeeperStore(tmp_path)
    contract = calibrate_objective("add health endpoint", cwd=tmp_path)
    store.save_contract(contract)

    result = main(
        [
            "attach",
            "--contract-id",
            contract.id,
            "--thread-id",
            "thread_123",
            "--cwd",
            str(tmp_path),
            "--true-goal",
            "--token-budget",
            "123",
        ]
    )

    output = capsys.readouterr().out
    updated = store.load_contract(contract.id)
    assert result == 0
    assert updated.thread_id == "thread_123"
    assert updated.goal_id == "thread_123"
    assert updated.status == "active"
    assert calls[0][0] == "thread_123"
    assert calls[0][2] == 123
    assert "fake true goal attached" in output
