from __future__ import annotations

from pathlib import Path

from .models import GoalkeeperContract


DEFAULT_MAX_GOAL_OBJECTIVE_CHARS = 4000


def render_contract(contract: GoalkeeperContract) -> str:
    criteria = "\n".join(
        f"{index}. [{criterion.id}] {criterion.description} "
        f"(Evidence: {criterion.evidence_required})"
        for index, criterion in enumerate(contract.acceptance_criteria, start=1)
    )
    verification = "\n".join(
        f"{index}. {step.description}"
        + (f"\n   Command: `{step.command}`" if step.command else "")
        + f"\n   Expected signal: {step.expected_signal}"
        for index, step in enumerate(contract.verification_plan, start=1)
    )
    return f"""<goalkeeper_contract id="{contract.id}">
User objective:
{contract.raw_user_objective}

Normalized objective:
{contract.normalized_objective}

Scope:
{_bullets(contract.scope)}

Non-goals:
{_bullets(contract.non_goals)}

Assumptions:
{_bullets(contract.assumptions)}

Acceptance criteria:
{criteria}

Verification plan:
{verification}

Evidence requirements:
- Each completed criterion must be supported by current-state evidence.
- Tests count only if they cover the requirement.
- File edits count only if they directly support a criterion.
- Claims without evidence do not close criteria.

Loop policy:
- Do not repeat the same failing command more than {contract.loop_policy.max_same_error_retries} times without a new hypothesis and changed precondition.
- Do not spend more than {contract.loop_policy.max_no_progress_turns} consecutive goal turns without new evidence.
- If no new evidence is produced, replan before continuing.
- If no new evidence is produced for the configured limit, pause or ask for user input.
- Do not broaden scope merely to keep working.
- Avoid unrelated refactors.

Wait/defer policy:
- If the next useful action is waiting for CI, deployment, a future time, external state, approval, or user input, do not continue immediate low-value turns.
- Pause/defer and record the wake condition.

Checkpoint rule:
At the end of each goal turn, create or update a Goalkeeper checkpoint containing:
- claimed progress,
- evidence,
- criteria closed,
- remaining criteria,
- commands and outcomes,
- changed files,
- loop signals,
- next action,
- whether continued work is justified.

Required checkpoint command:
Run this command shape from the workspace root at the end of each meaningful goal continuation turn:
`goalkeeper checkpoint --contract-id {contract.id} --claimed-progress "..." --evidence "..." --criteria-closed "AC1" --criteria-remaining "AC2,AC3" --command "pytest" --outcome passed --changed-file "path/to/file" --next-action "..."`

Use repeated flags for multiple evidence refs, commands, outcomes, criteria, or changed files.
If a command failed, include `--outcome failed` and `--error-signature "short stable error"`.
If the goal is waiting, include `--waiting-on "CI, approval, user input, deployment, or external state"` and set `--next-action` to the wake condition.

Do not end a goal continuation turn without either:
- recording a goalkeeper checkpoint, or
- explaining why no checkpoint could be recorded.

Stale context defense:
- Before repeating a previous manual steer or subtask, check the Goalkeeper contract and checkpoint history.
- Do not redo completed work unless current evidence contradicts completion or the user explicitly asked to repeat it.

Completion rule:
Only mark the goal complete when all acceptance criteria are satisfied and verified.
</goalkeeper_contract>"""


def paste_ready_goal(
    contract: GoalkeeperContract,
    *,
    contract_path: str | Path | None = None,
    max_chars: int = DEFAULT_MAX_GOAL_OBJECTIVE_CHARS,
) -> str:
    command = f"/goal {render_contract(contract)}"
    if len(command) <= max_chars:
        return command
    if contract_path is None:
        return command
    absolute = Path(contract_path).expanduser().resolve()
    return f"/goal Read the Goalkeeper contract at {absolute} and pursue it exactly."


def compact_contract_summary(contract: GoalkeeperContract) -> str:
    criteria = ", ".join(f"{item.id}:{item.status}" for item in contract.acceptance_criteria)
    return (
        f"{contract.id} [{contract.status}] {contract.normalized_objective}\n"
        f"Criteria: {criteria}\n"
        f"Questions: {len(contract.questions)}"
    )


def _bullets(items: list[str]) -> str:
    if not items:
        return "- None."
    return "\n".join(f"- {item}" for item in items)
