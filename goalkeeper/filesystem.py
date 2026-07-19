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


@dataclass
class GitObservation:
    head: str
    changed_files: list[str] = field(default_factory=list)


def observe_git_state(cwd: str | Path | None = None) -> GitObservation | None:
    """Capture the current HEAD hash and dirty paths, or None outside a usable git repo."""
    root = Path(cwd or Path.cwd()).expanduser().resolve()
    head = _git_output(root, "rev-parse", "HEAD")
    if head is None:
        return None
    head = head.strip()
    status = _git_output(root, "status", "--porcelain")
    if status is None:
        return GitObservation(head=head)
    changed: list[str] = []
    # Porcelain v1: two status chars, one space, then the path. Leading spaces
    # in the status columns are significant, so the raw line must not be stripped.
    for line in status.splitlines():
        if not line.strip():
            continue
        path = line[3:] if len(line) > 3 else line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        changed.append(path.strip().strip('"'))
    return GitObservation(head=head, changed_files=changed)


def _git_output(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


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
