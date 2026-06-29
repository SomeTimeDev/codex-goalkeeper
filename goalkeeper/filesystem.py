from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RepoFacts:
    cwd: Path
    exists: bool
    package_managers: list[str] = field(default_factory=list)
    test_commands: list[str] = field(default_factory=list)
    has_agents: bool = False
    has_readme: bool = False
    has_docs: bool = False
    in_git_repo: bool = False
    git_dirty: bool = False
    git_status_summary: str = ""


def inspect_repository(cwd: str | Path | None = None) -> RepoFacts:
    root = Path(cwd or Path.cwd()).expanduser().resolve()
    facts = RepoFacts(cwd=root, exists=root.exists())
    if not root.exists() or not root.is_dir():
        return facts

    if (root / "package.json").exists():
        facts.package_managers.append("node")
        if (root / "pnpm-lock.yaml").exists():
            facts.test_commands.append("pnpm test")
        elif (root / "yarn.lock").exists():
            facts.test_commands.append("yarn test")
        else:
            facts.test_commands.append(_node_test_command(root / "package.json"))

    if (root / "pyproject.toml").exists():
        facts.package_managers.append("python")
        facts.test_commands.append("pytest")

    if (root / "Cargo.toml").exists():
        facts.package_managers.append("rust")
        facts.test_commands.append("cargo test")

    if (root / "go.mod").exists():
        facts.package_managers.append("go")
        facts.test_commands.append("go test ./...")

    if (root / "pom.xml").exists():
        facts.package_managers.append("maven")
        facts.test_commands.append("mvn test")

    facts.has_agents = (root / "AGENTS.md").exists()
    facts.has_readme = any((root / name).exists() for name in ("README.md", "README.rst", "README.txt"))
    facts.has_docs = (root / "docs").exists()
    _inspect_git(root, facts)
    facts.test_commands = _dedupe(facts.test_commands)
    facts.package_managers = _dedupe(facts.package_managers)
    return facts


def _node_test_command(package_json: Path) -> str:
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
        scripts = data.get("scripts", {})
        if isinstance(scripts, dict) and "test" in scripts:
            return "npm test"
    except (OSError, json.JSONDecodeError):
        pass
    return "npm test"


def _inspect_git(root: Path, facts: RepoFacts) -> None:
    try:
        inside = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    facts.in_git_repo = inside.returncode == 0 and inside.stdout.strip() == "true"
    if not facts.in_git_repo:
        return
    try:
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    lines = [line for line in status.stdout.splitlines() if line.strip()]
    facts.git_dirty = bool(lines)
    if lines:
        facts.git_status_summary = f"{len(lines)} changed path(s)"
    else:
        facts.git_status_summary = "clean"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
