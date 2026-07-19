from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from goalkeeper.calibration import calibrate_objective
from goalkeeper.cli import main as goalkeeper_main
from goalkeeper.ledger import GoalkeeperStore
from goalkeeper.models import AcceptanceCriterion, VerificationStep


def main() -> int:
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    with tempfile.TemporaryDirectory(prefix="proofkeeper-demo-") as temp_dir:
        repo = Path(temp_dir).resolve()
        _create_baseline(repo)
        _add_scoped_change(repo)
        contract = calibrate_objective(
            "add subtraction support to the existing calculator without creating a new module",
            cwd=repo,
        )
        contract.acceptance_criteria.append(
            AcceptanceCriterion(
                id="AC_DEMO",
                description="subtract(7, 2) returns 5.",
                evidence_required="A focused passing test.",
            )
        )
        contract.verification_plan = [
            VerificationStep(
                id="V1",
                description="Review the final diff.",
                command="git diff --stat",
                expected_signal="Only the calculator and its test changed.",
            ),
            VerificationStep(
                id="V2",
                description="Run the focused test suite.",
                command="python -m pytest -q --basetemp .pytest_tmp",
                expected_signal="All tests pass.",
            ),
        ]
        store = GoalkeeperStore(repo)
        store.save_contract(contract)

        print("\n=== SCENARIO 1: focused change ===\n")
        complete_code = _prove(repo, contract.id)

        print("\n=== SCENARIO 2: scope drift after passing tests ===\n")
        drift_path = repo / "src" / "services" / "subtract_service.py"
        drift_path.parent.mkdir(parents=True, exist_ok=True)
        drift_path.write_text(
            "class SubtractService:\n"
            "    def run(self, left: int, right: int) -> int:\n"
            "        return left - right\n",
            encoding="utf-8",
        )
        replan_code = _prove(repo, contract.id)

        output = Path.cwd() / f"demo-output-{uuid4().hex[:8]}"
        shutil.copytree(store.storage_dir / "proofs" / contract.id, output)
        print(f"\nDemo evidence copied to {output}")
        if complete_code != 0:
            print(f"Expected COMPLETE exit 0, got {complete_code}.", file=sys.stderr)
            return 1
        if replan_code != 2:
            print(f"Expected REPLAN exit 2, got {replan_code}.", file=sys.stderr)
            return 1
        print("Demo passed: focused work completed; scope drift was blocked.")
        return 0


def _prove(repo: Path, contract_id: str) -> int:
    return goalkeeper_main(
        [
            "prove",
            "--contract-id",
            contract_id,
            "--cwd",
            str(repo),
            "--base",
            "HEAD",
            "--allow-path",
            "src/calculator.py",
            "--allow-path",
            "tests/**",
            "--prefer-modify",
            "src/calculator.py",
            "--close-criterion",
            "AC1",
            "--close-criterion",
            "AC_DEMO",
        ]
    )


def _create_baseline(repo: Path) -> None:
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        "[project]\n"
        'name = "proofkeeper-demo"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.11"\n\n'
        "[tool.pytest.ini_options]\n"
        'pythonpath = ["src"]\n'
        'testpaths = ["tests"]\n',
        encoding="utf-8",
    )
    (repo / ".gitignore").write_text(
        "__pycache__/\n.pytest_cache/\n.pytest_tmp/\n.goalkeeper/\n",
        encoding="utf-8",
    )
    (repo / "src" / "calculator.py").write_text(
        "def add(left: int, right: int) -> int:\n"
        "    return left + right\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_calculator.py").write_text(
        "from calculator import add\n\n\n"
        "def test_adds_two_numbers():\n"
        "    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-b", "main")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=Proofkeeper Demo",
        "-c",
        "user.email=demo@example.invalid",
        "commit",
        "-m",
        "Create baseline calculator",
    )


def _add_scoped_change(repo: Path) -> None:
    (repo / "src" / "calculator.py").write_text(
        "def add(left: int, right: int) -> int:\n"
        "    return left + right\n\n\n"
        "def subtract(left: int, right: int) -> int:\n"
        "    return left - right\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_calculator.py").write_text(
        "from calculator import add, subtract\n\n\n"
        "def test_adds_two_numbers():\n"
        "    assert add(2, 3) == 5\n\n\n"
        "def test_subtracts_two_numbers():\n"
        "    assert subtract(7, 2) == 5\n",
        encoding="utf-8",
    )


def _git(repo: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())


if __name__ == "__main__":
    raise SystemExit(main())
