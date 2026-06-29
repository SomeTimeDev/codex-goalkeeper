from __future__ import annotations

from dataclasses import dataclass, field

from .models import Checkpoint, Decision, GoalkeeperContract, LoopSignal


@dataclass
class PolicyEvaluation:
    decision: Decision
    progress_score: int
    signals: list[LoopSignal] = field(default_factory=list)
    explanation: str = ""
    no_evidence_streak: int = 0
    same_error_retries: int = 0
    waiting_streak: int = 0


def evaluate_policy(contract: GoalkeeperContract, checkpoints: list[Checkpoint]) -> PolicyEvaluation:
    if not checkpoints:
        return PolicyEvaluation(
            decision=Decision.CONTINUE,
            progress_score=0,
            explanation="No checkpoints recorded yet.",
        )

    latest = checkpoints[-1]
    score = score_checkpoint(latest)
    signals: list[LoopSignal] = []

    no_evidence_streak = _count_no_evidence_streak(checkpoints)
    same_error_retries = _count_same_error_retries(checkpoints)
    waiting_streak = _count_waiting_streak(checkpoints)
    plan_only_streak = _count_plan_only_streak(checkpoints)
    repeated_command = _latest_repeated_command(checkpoints)
    churned_files = _latest_file_churn(checkpoints)

    if repeated_command:
        score -= 1
        signals.append(
            LoopSignal(
                kind="repeated_command",
                severity="medium",
                explanation="The same command was repeated with the same outcome.",
                evidence=[repeated_command],
            )
        )

    if same_error_retries >= contract.loop_policy.max_same_error_retries:
        score -= 2
        signals.append(
            LoopSignal(
                kind="same_error_repeated",
                severity="high",
                explanation="The same error signature repeated beyond the configured retry limit.",
                evidence=[str(same_error_retries)],
            )
        )
        return PolicyEvaluation(
            decision=Decision.REPLAN_REQUIRED,
            progress_score=score,
            signals=signals,
            explanation="Repeated failure requires a new hypothesis before continuing.",
            no_evidence_streak=no_evidence_streak,
            same_error_retries=same_error_retries,
            waiting_streak=waiting_streak,
        )

    if waiting_streak >= contract.loop_policy.max_waiting_turns:
        score -= 3
        signals.append(
            LoopSignal(
                kind="waiting_state",
                severity="high",
                explanation="The goal is waiting on external state for consecutive checkpoints.",
                evidence=[latest.waiting_on or latest.claimed_progress],
            )
        )
        decision = (
            Decision.DEFER_RECOMMENDED
            if contract.wait_policy.pause_on_waiting
            else Decision.PAUSE_RECOMMENDED
        )
        return PolicyEvaluation(
            decision=decision,
            progress_score=score,
            signals=signals,
            explanation="Pause or defer until the wake condition is available.",
            no_evidence_streak=no_evidence_streak,
            same_error_retries=same_error_retries,
            waiting_streak=waiting_streak,
        )

    if no_evidence_streak >= contract.loop_policy.max_no_progress_turns:
        score -= 2
        signals.append(
            LoopSignal(
                kind="no_new_evidence",
                severity="high",
                explanation="No new evidence was produced for the configured limit.",
                evidence=[str(no_evidence_streak)],
            )
        )
        return PolicyEvaluation(
            decision=Decision.PAUSE_RECOMMENDED,
            progress_score=score,
            signals=signals,
            explanation="No-progress limit reached; pause or ask for user input.",
            no_evidence_streak=no_evidence_streak,
            same_error_retries=same_error_retries,
            waiting_streak=waiting_streak,
        )

    if plan_only_streak >= contract.loop_policy.max_plan_only_turns:
        score -= 2
        signals.append(
            LoopSignal(
                kind="plan_only",
                severity="medium",
                explanation="Recent checkpoints describe plans without evidence or action.",
                evidence=[str(plan_only_streak)],
            )
        )

    if churned_files:
        score -= 3
        signals.append(
            LoopSignal(
                kind="same_files_churned",
                severity="medium",
                explanation="The same files changed repeatedly without closing criteria.",
                evidence=churned_files,
            )
        )

    if _all_criteria_satisfied(contract):
        return PolicyEvaluation(
            decision=Decision.COMPLETE_CANDIDATE,
            progress_score=score,
            signals=signals,
            explanation="All acceptance criteria are marked satisfied.",
            no_evidence_streak=no_evidence_streak,
            same_error_retries=same_error_retries,
            waiting_streak=waiting_streak,
        )

    if score <= -4:
        return PolicyEvaluation(
            decision=Decision.PAUSE_RECOMMENDED,
            progress_score=score,
            signals=signals,
            explanation="Loop risk is high enough to pause before continuing.",
            no_evidence_streak=no_evidence_streak,
            same_error_retries=same_error_retries,
            waiting_streak=waiting_streak,
        )

    if latest.criteria_closed or latest.new_evidence:
        return PolicyEvaluation(
            decision=Decision.CONTINUE,
            progress_score=score,
            signals=signals,
            explanation="New evidence or closed criteria justify continued work.",
            no_evidence_streak=no_evidence_streak,
            same_error_retries=same_error_retries,
            waiting_streak=waiting_streak,
        )

    return PolicyEvaluation(
        decision=Decision.CONTINUE_WITH_REQUIRED_NEXT_ACTION,
        progress_score=score,
        signals=signals,
        explanation="Continue only if the next action is expected to produce evidence.",
        no_evidence_streak=no_evidence_streak,
        same_error_retries=same_error_retries,
        waiting_streak=waiting_streak,
    )


def score_checkpoint(checkpoint: Checkpoint) -> int:
    score = 0
    score += 3 * len(checkpoint.criteria_closed)
    score += 2 * len(checkpoint.new_evidence)
    score += 1 * len(checkpoint.changed_files)
    if any(command.outcome == "passed" for command in checkpoint.commands_run):
        score += 2
    if any(command.outcome == "partial" for command in checkpoint.commands_run):
        score += 1
    if _blocker_identified(checkpoint):
        score += 1
    if not _has_new_evidence(checkpoint):
        score -= 2
    if checkpoint.waiting_on:
        score -= 3
    if _is_plan_only(checkpoint):
        score += 0
    return score


def _has_new_evidence(checkpoint: Checkpoint) -> bool:
    return bool(
        checkpoint.new_evidence
        or checkpoint.criteria_closed
        or any(command.outcome == "passed" for command in checkpoint.commands_run)
    )


def _blocker_identified(checkpoint: Checkpoint) -> bool:
    text = f"{checkpoint.claimed_progress} {checkpoint.next_action}".lower()
    return "blocker" in text or "blocked" in text


def _is_plan_only(checkpoint: Checkpoint) -> bool:
    if checkpoint.new_evidence or checkpoint.criteria_closed or checkpoint.commands_run:
        return False
    text = f"{checkpoint.claimed_progress} {checkpoint.next_action}".lower()
    plan_words = ("plan", "will", "next i", "going to", "intend")
    return any(word in text for word in plan_words)


def _is_waiting(checkpoint: Checkpoint) -> bool:
    if checkpoint.waiting_on:
        return True
    text = f"{checkpoint.claimed_progress} {checkpoint.next_action}".lower()
    waiting_words = ("waiting", "wait for", "pending ci", "pending approval", "defer")
    return any(word in text for word in waiting_words)


def _count_no_evidence_streak(checkpoints: list[Checkpoint]) -> int:
    count = 0
    for checkpoint in reversed(checkpoints):
        if _has_new_evidence(checkpoint):
            break
        count += 1
    return count


def _count_waiting_streak(checkpoints: list[Checkpoint]) -> int:
    count = 0
    for checkpoint in reversed(checkpoints):
        if not _is_waiting(checkpoint):
            break
        count += 1
    return count


def _count_plan_only_streak(checkpoints: list[Checkpoint]) -> int:
    count = 0
    for checkpoint in reversed(checkpoints):
        if not _is_plan_only(checkpoint):
            break
        count += 1
    return count


def _count_same_error_retries(checkpoints: list[Checkpoint]) -> int:
    latest_signature = None
    count = 0
    for command in reversed(checkpoints[-1].commands_run):
        if command.error_signature:
            latest_signature = command.error_signature
            break
    if latest_signature is None:
        return 0
    for checkpoint in reversed(checkpoints):
        signatures = [
            command.error_signature
            for command in checkpoint.commands_run
            if command.error_signature and command.outcome in {"failed", "partial"}
        ]
        if latest_signature in signatures:
            count += 1
        else:
            break
    return count


def _latest_repeated_command(checkpoints: list[Checkpoint]) -> str | None:
    if len(checkpoints) < 2:
        return None
    latest_commands = checkpoints[-1].commands_run
    previous_commands = checkpoints[-2].commands_run
    for latest in latest_commands:
        for previous in previous_commands:
            if latest.command == previous.command and latest.outcome == previous.outcome:
                return f"{latest.command} -> {latest.outcome}"
    return None


def _latest_file_churn(checkpoints: list[Checkpoint]) -> list[str]:
    if len(checkpoints) < 3:
        return []
    latest = set(checkpoints[-1].changed_files)
    if not latest or checkpoints[-1].criteria_closed:
        return []
    previous = set(checkpoints[-2].changed_files)
    before_previous = set(checkpoints[-3].changed_files)
    churned = sorted(latest & previous & before_previous)
    return churned


def _all_criteria_satisfied(contract: GoalkeeperContract) -> bool:
    return bool(contract.acceptance_criteria) and all(
        criterion.status == "satisfied" for criterion in contract.acceptance_criteria
    )
