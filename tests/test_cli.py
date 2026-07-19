import json
import importlib.resources
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from goalkeeper.calibration import calibrate_objective
from goalkeeper.cli import _app_server_goal_objective, main
from goalkeeper.codex_adapter import AppServerCapabilityMatrix, PauseGoalResult, StartGoalResult
from goalkeeper.contract import DEFAULT_MAX_GOAL_OBJECTIVE_CHARS
from goalkeeper.ledger import GoalkeeperStore, new_checkpoint_id, utc_now
from goalkeeper.models import Checkpoint, VerificationStep


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
    assert "Contract anchor:" in output
    assert (tmp_path / ".goalkeeper" / "ledgers" / f"{contract_id}.jsonl").exists()


def test_verify_records_authoritative_checkpoint(tmp_path, capsys):
    assert main(["prepare", "add health endpoint", "--cwd", str(tmp_path)]) == 0
    contract_id = _first_contract_id(tmp_path)
    store = GoalkeeperStore(tmp_path)
    contract = store.load_contract(contract_id)
    contract.verification_plan = [
        VerificationStep(id="V1", description="Echo.", command="echo ok", expected_signal="ok"),
    ]
    store.save_contract(contract)

    result = main(["verify", "--contract-id", contract_id, "--cwd", str(tmp_path)])

    output = capsys.readouterr().out
    checkpoints = store.read_checkpoints(contract_id)
    updated = store.load_contract(contract_id)
    assert result == 0
    assert "Verification checkpoint added:" in output
    assert "[PASS] V1" in output
    assert "Contract anchor:" in output
    assert checkpoints[-1].source == "verify"
    assert any("passed" in item for item in checkpoints[-1].new_evidence)
    assert updated.verification_plan[0].last_result.startswith("passed")


def test_verify_returns_nonzero_on_failing_step(tmp_path, capsys):
    assert main(["prepare", "add health endpoint", "--cwd", str(tmp_path)]) == 0
    contract_id = _first_contract_id(tmp_path)
    store = GoalkeeperStore(tmp_path)
    contract = store.load_contract(contract_id)
    contract.verification_plan = [
        VerificationStep(id="V1", description="Fails.", command="exit 2", expected_signal="never"),
    ]
    store.save_contract(contract)

    result = main(["verify", "--contract-id", contract_id, "--cwd", str(tmp_path)])

    output = capsys.readouterr().out
    checkpoints = store.read_checkpoints(contract_id)
    assert result == 1
    assert "[FAIL] V1" in output
    assert checkpoints[-1].commands_run[0].outcome == "failed"
    assert checkpoints[-1].commands_run[0].error_signature


def test_prepare_with_custom_criterion(tmp_path):
    result = main(
        [
            "prepare",
            "add health endpoint",
            "--cwd",
            str(tmp_path),
            "--criterion",
            "GET /health returns 200 with build info",
        ]
    )

    contract = GoalkeeperStore(tmp_path).load_contract(_first_contract_id(tmp_path))
    assert result == 0
    custom = [item for item in contract.acceptance_criteria if item.id == "AC_U1"]
    assert custom
    assert "returns 200" in custom[0].description


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not available")
def test_checkpoint_captures_git_observation(tmp_path, capsys):
    def git(*args):
        subprocess.run(
            ["git", "-C", str(tmp_path), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    git("init")
    (tmp_path / "tracked.txt").write_text("one", encoding="utf-8")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-m", "init")
    (tmp_path / "tracked.txt").write_text("two", encoding="utf-8")

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
            "Edited tracked file",
            "--evidence",
            "manual edit",
            "--changed-file",
            "tracked.txt",
        ]
    )

    checkpoints = GoalkeeperStore(tmp_path).read_checkpoints(contract_id)
    assert result == 0
    assert checkpoints[-1].git_head
    assert "tracked.txt" in checkpoints[-1].observed_changed_files


def test_watch_once_without_sdk_prints_manual_instructions(tmp_path, capsys):
    assert main(["prepare", "add health endpoint", "--cwd", str(tmp_path)]) == 0
    contract_id = _first_contract_id(tmp_path)

    result = main(["watch", "--contract-id", contract_id, "--cwd", str(tmp_path), "--once"])

    output = capsys.readouterr().out
    assert result == 0
    assert "Automatic watch is unavailable" in output


def test_doctor_default_is_passive(tmp_path, capsys, monkeypatch):
    calls = []

    def fake_probe(*, cwd=None, live_probe=False, codex_bin=None):
        calls.append(live_probe)
        _ = (cwd, codex_bin)
        return AppServerCapabilityMatrix(
            codex_binary="codex",
            app_server_available=True,
            notes=[
                "Live app-server goal probe skipped. Run `goalkeeper doctor --live-probe` "
                "to verify true goal-control."
            ],
        )

    monkeypatch.setattr("goalkeeper.doctor.inspect_app_server_capabilities", fake_probe)

    result = main(["doctor", "--cwd", str(tmp_path)])

    output = capsys.readouterr().out
    assert result == 0
    assert calls == [False]
    assert "Goalkeeper doctor" in output
    assert "true /goal control: unknown; run `goalkeeper doctor --live-probe`" in output


def test_doctor_live_probe_is_opt_in(tmp_path, capsys, monkeypatch):
    calls = []

    def fake_probe(*, cwd=None, live_probe=False, codex_bin=None):
        calls.append(live_probe)
        _ = (cwd, codex_bin)
        return AppServerCapabilityMatrix(
            codex_binary="codex",
            app_server_available=True,
            initialize=True,
            thread_start=True,
            goal_get=True,
            goal_set=True,
            goal_pause=True,
            goal_clear=True,
            thread_read=True,
            true_goal_control=True,
            notes=["fake live probe succeeded"],
        )

    monkeypatch.setattr("goalkeeper.doctor.inspect_app_server_capabilities", fake_probe)

    result = main(["doctor", "--cwd", str(tmp_path), "--live-probe"])

    output = capsys.readouterr().out
    assert result == 0
    assert calls == [True]
    assert "true /goal control: available" in output


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
                goal_id=None,
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
    assert updated.goal_id is None
    assert updated.status == "active"
    assert calls[0][0] == "thread_123"
    assert calls[0][2] == 123
    assert "fake true goal attached" in output


def test_start_true_goal_persists_thread_without_fake_goal_id(tmp_path, capsys, monkeypatch):
    class FakeAppServerAdapter:
        def __init__(self, cwd=None):
            self.cwd = cwd

        def start_goal_thread(self, objective, *, cwd=None, token_budget=None):
            _ = (objective, cwd, token_budget, self.cwd)
            return StartGoalResult(
                True,
                True,
                "fake true goal started",
                goal_id=None,
                thread_id="thread_123",
                mode="true_goal",
                final_response="thread_id=thread_123, goal_id=unavailable, status=active",
            )

    monkeypatch.setattr("goalkeeper.cli.CodexAppServerJsonRpcAdapter", FakeAppServerAdapter)

    result = main(["start", "add health endpoint", "--cwd", str(tmp_path), "--true-goal"])

    output = capsys.readouterr().out
    contract = GoalkeeperStore(tmp_path).load_contract(_first_contract_id(tmp_path))
    assert result == 0
    assert contract.thread_id == "thread_123"
    assert contract.goal_id is None
    assert "fake true goal started" in output


def test_package_skill_asset_exists():
    asset = importlib.resources.files("goalkeeper").joinpath(
        "assets",
        "skills",
        "goalkeeper",
        "SKILL.md",
    )

    assert asset.is_file()
    assert "Goalkeeper Skill" in asset.read_text(encoding="utf-8")


def test_install_skill_copies_skill(tmp_path, capsys):
    target = tmp_path / "skills"

    result = main(["install-skill", "--target", str(target)])

    output = capsys.readouterr().out
    installed = target / "goalkeeper" / "SKILL.md"
    assert result == 0
    assert installed.exists()
    assert "Installed Goalkeeper skill" in output
    assert "Goalkeeper Skill" in installed.read_text(encoding="utf-8")


def test_start_assume_defaults_turns_pending_contract_active(tmp_path, capsys):
    result = main(
        [
            "start",
            "migrate auth provider",
            "--cwd",
            str(tmp_path),
            "--assume-defaults",
            "--dry-run",
        ]
    )

    output = capsys.readouterr().out
    contract_id = _first_contract_id(tmp_path)
    contract = GoalkeeperStore(tmp_path).load_contract(contract_id)
    assert result == 0
    assert contract.status == "active"
    assert not any(question.critical for question in contract.questions)
    assert any("Assumed Q_FALLBACK default" in item for item in contract.assumptions)
    assert "Assumed defaults for 1 question(s)." in output


def test_answer_records_answer_and_clears_critical_question(tmp_path, capsys):
    assert main(["prepare", "migrate auth provider", "--cwd", str(tmp_path)]) == 0
    contract_id = _first_contract_id(tmp_path)

    result = main(
        [
            "answer",
            "--contract-id",
            contract_id,
            "--cwd",
            str(tmp_path),
            "--answer",
            "Q_FALLBACK=keep fallback",
        ]
    )

    output = capsys.readouterr().out
    contract = GoalkeeperStore(tmp_path).load_contract(contract_id)
    assert result == 0
    assert contract.status == "active"
    assert not any(question.critical for question in contract.questions)
    assert "Answered Q_FALLBACK: keep fallback" in contract.assumptions
    assert f"goalkeeper start --contract-id {contract_id} --true-goal" in output


def test_start_from_existing_contract_does_not_create_new_contract(tmp_path, capsys):
    assert main(["prepare", "add health endpoint", "--cwd", str(tmp_path)]) == 0
    contract_id = _first_contract_id(tmp_path)

    result = main(
        [
            "start",
            "--contract-id",
            contract_id,
            "--cwd",
            str(tmp_path),
            "--dry-run",
        ]
    )

    output = capsys.readouterr().out
    contracts = sorted((tmp_path / ".goalkeeper" / "contracts").glob("*.json"))
    assert result == 0
    assert len(contracts) == 1
    assert "Goalkeeper contract loaded" in output
    assert contract_id in output


def test_start_from_existing_pending_contract_is_deferred(tmp_path, capsys):
    assert main(["prepare", "migrate auth provider", "--cwd", str(tmp_path)]) == 0
    contract_id = _first_contract_id(tmp_path)

    result = main(
        [
            "start",
            "--contract-id",
            contract_id,
            "--cwd",
            str(tmp_path),
            "--dry-run",
        ]
    )

    output = capsys.readouterr().out
    assert result == 2
    assert "Start deferred" in output


def test_app_server_goal_objective_uses_default_limit(tmp_path):
    contract = calibrate_objective("add audit logging", cwd=tmp_path)
    path = tmp_path / "contract.json"

    objective = _app_server_goal_objective(contract, path)

    assert DEFAULT_MAX_GOAL_OBJECTIVE_CHARS == 4000
    assert objective.startswith("Read the Goalkeeper contract at ")
    assert str(path.resolve()) in objective
