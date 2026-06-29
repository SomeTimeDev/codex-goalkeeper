from __future__ import annotations

from pathlib import Path


def manual_watch_instructions(contract_id: str) -> str:
    return f"""Automatic watch is unavailable in this environment.
Use manual checkpoints instead:

  goalkeeper checkpoint --contract-id {contract_id} --claimed-progress "..." --evidence "..." --next-action "..."
  goalkeeper status --contract-id {contract_id}

You can also paste the checkpoint rule from the generated Goalkeeper contract into Codex so each goal turn records evidence and loop signals.
"""


def manual_pause_instruction(thread_id: str | None = None) -> str:
    target = f" for thread {thread_id}" if thread_id else ""
    return f"Pause the running Codex /goal{target} manually in Codex, then keep this Goalkeeper contract paused until resume."


def skill_install_instructions(skill_path: Path) -> str:
    return f"""Goalkeeper includes a personal Codex skill at:
  {skill_path}

To install manually, copy that directory into your local Codex skills directory as:
  skills/goalkeeper/SKILL.md

Codex skill paths can vary by installation. Goalkeeper does not assume your Codex config layout unless you pass --target.
This skill does not create a native /goalkeeper slash command.
"""
