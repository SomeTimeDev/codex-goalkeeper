from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .filesystem import RepoFacts, inspect_repository
from .models import (
    AcceptanceCriterion,
    GoalkeeperContract,
    LoopPolicy,
    Question,
    VerificationStep,
    WaitPolicy,
)


GENERIC_QUESTION_FRAGMENTS = (
    "can you clarify",
    "should i continue",
    "what exactly do you want",
    "should i write tests",
)

# Keyword groups accept English and Turkish objectives. Turkish entries are
# stems so suffixed forms ("taşıma", "geçişi") still match by substring.
MIGRATE_WORDS = ("migrate", "migration", "taşı", "geçir", "geçiş")
AUTH_WORDS = ("auth", "provider", "login", "kimlik", "giriş", "sağlayıcı", "oturum")
REFACTOR_WORDS = ("refactor", "refaktör", "yeniden düzenle")
COMPAT_PHRASES = (
    "without breaking",
    "backward-compatible",
    "compatible",
    "uyumlu",
    "bozmadan",
    "kırmadan",
    "geriye dönük",
)
DEPLOY_WORDS = ("deploy", "release", "dağıt", "yayın", "canlıya")
WAIT_WORDS = ("wait", "bekle")
DOC_WORDS = ("doc", "readme", "doküman", "döküman", "belge")


def calibrate_objective(
    objective: str,
    *,
    cwd: str | Path | None = None,
    token_budget: int | None = None,
    max_questions: int = 3,
    max_no_progress_turns: int = 3,
    max_same_error_retries: int = 2,
    max_criteria_stall_turns: int = 5,
    max_checkpoint_gap_minutes: int = 45,
    extra_criteria: list[str] | None = None,
) -> GoalkeeperContract:
    objective = " ".join(objective.strip().split())
    if not objective:
        raise ValueError("objective must not be empty")

    facts = inspect_repository(cwd)
    now = _utc_now()
    questions = _infer_questions(objective, max_questions=max_questions)
    status = "pending_questions" if any(question.critical for question in questions) else "active"

    return GoalkeeperContract(
        id=f"gk_{uuid4().hex[:10]}",
        created_at=now,
        updated_at=now,
        raw_user_objective=objective,
        normalized_objective=_normalize_objective(objective),
        scope=_infer_scope(objective, facts),
        non_goals=_infer_non_goals(objective),
        assumptions=_infer_assumptions(objective, facts),
        acceptance_criteria=_build_acceptance_criteria(objective, extra_criteria),
        verification_plan=_infer_verification_plan(facts),
        loop_policy=LoopPolicy(
            max_no_progress_turns=max_no_progress_turns,
            max_same_error_retries=max_same_error_retries,
            max_waiting_turns=2,
            max_plan_only_turns=2,
            max_criteria_stall_turns=max_criteria_stall_turns,
            max_checkpoint_gap_minutes=max_checkpoint_gap_minutes,
        ),
        wait_policy=WaitPolicy(
            detect_waiting=True,
            pause_on_waiting=True,
            wake_condition="Resume when the external condition, approval, CI result, or user answer is available.",
        ),
        status=status,
        questions=questions,
        token_budget=token_budget,
    )


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_objective(objective: str) -> str:
    text = objective.rstrip(".")
    if not re.match(r"^(implement|refactor|migrate|fix|add|remove|update|verify|build)\b", text, re.I):
        text = f"Complete the requested work: {text}"
    return text[0].upper() + text[1:]


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text) is not None


def _infer_scope(objective: str, facts: RepoFacts) -> list[str]:
    lower = objective.lower()
    scope = [
        "Make changes directly required by the normalized objective.",
        "Preserve existing project conventions and ownership boundaries.",
        "Update or add focused tests and verification artifacts that support the acceptance criteria.",
    ]
    if facts.exists:
        scope.append(f"Use {facts.cwd} as the workspace root.")
    if facts.has_agents:
        scope.append("Read and respect AGENTS.md or local agent instructions before editing.")
    if any(word in lower for word in DOC_WORDS):
        scope.append("Update the requested documentation and keep commands truthful.")
    elif (
        _has_word(lower, "api")
        or _has_word(lower, "public")
        or any(word in lower for word in MIGRATE_WORDS)
        or any(word in lower for word in REFACTOR_WORDS)
    ):
        scope.append("Update minimal docs or migration notes only when behavior visible to users changes.")
    if facts.test_commands:
        scope.append("Run the inferred verification command(s) when practical.")
    return scope


def _infer_non_goals(objective: str) -> list[str]:
    lower = objective.lower()
    non_goals = [
        "Do not broaden scope merely to keep the goal active.",
        "Do not perform unrelated refactors, dependency swaps, or formatting churn.",
        "Do not mark work complete without current evidence for every acceptance criterion.",
    ]
    if any(phrase in lower for phrase in COMPAT_PHRASES) or "public api" in lower:
        non_goals.append("Do not introduce intentional public API or compatibility breaks.")
    if "codex" in lower:
        non_goals.append("Do not modify Codex source or claim native Codex integration unless it exists.")
    return non_goals


def _infer_assumptions(objective: str, facts: RepoFacts) -> list[str]:
    assumptions = [
        "Contract-only mode is sufficient when automatic Codex SDK integration is unavailable.",
        "Claims should be backed by files, tests, commands, or explicit blocker evidence.",
    ]
    if facts.test_commands:
        commands = ", ".join(facts.test_commands)
        assumptions.append(f"Inferred verification command(s): {commands}.")
    else:
        assumptions.append("No standard test command was inferred; use repository-specific validation if found.")
    if facts.in_git_repo:
        assumptions.append(f"Git working tree at calibration time: {facts.git_status_summary}.")
    if facts.has_readme:
        assumptions.append("README or project documentation may contain local usage and verification guidance.")
    return assumptions


def _build_acceptance_criteria(
    objective: str,
    extra_criteria: list[str] | None,
) -> list[AcceptanceCriterion]:
    criteria = _infer_acceptance_criteria(objective)
    added = 0
    for description in extra_criteria or []:
        text = " ".join(description.strip().split())
        if not text:
            continue
        added += 1
        criteria.append(
            AcceptanceCriterion(
                id=f"AC_U{added}",
                description=text,
                evidence_required=(
                    "Current-state evidence (files, tests, command output) showing this "
                    "criterion is met."
                ),
            )
        )
    return criteria


def _infer_acceptance_criteria(objective: str) -> list[AcceptanceCriterion]:
    lower = objective.lower()
    criteria = [
        AcceptanceCriterion(
            id="AC1",
            description="The normalized objective is implemented within the declared scope.",
            evidence_required="Relevant files changed or inspected, with a concise explanation of how they satisfy the objective.",
        ),
        AcceptanceCriterion(
            id="AC2",
            description="Relevant behavior is verified with current evidence.",
            evidence_required="Passing tests, command output summary, manual inspection notes, or documented reason a test could not run.",
        ),
        AcceptanceCriterion(
            id="AC3",
            description="No unrelated scope expansion or avoidable churn is introduced.",
            evidence_required="Diff or status review showing changes are limited to the objective.",
        ),
    ]
    if (
        _has_word(lower, "api")
        or _has_word(lower, "public")
        or any(phrase in lower for phrase in COMPAT_PHRASES)
    ):
        criteria.insert(
            1,
            AcceptanceCriterion(
                id="AC_COMPAT",
                description="Public API and compatibility expectations are preserved unless explicitly approved.",
                evidence_required="Compatibility tests, unchanged public signatures, or migration notes for any approved break.",
            ),
        )
    if (
        _has_word(lower, "ci")
        or any(word in lower for word in DEPLOY_WORDS)
        or any(word in lower for word in WAIT_WORDS)
    ):
        criteria.append(
            AcceptanceCriterion(
                id="AC_WAIT",
                description="Waiting states are paused or deferred instead of consuming low-value active turns.",
                evidence_required="Checkpoint naming the external wait condition and wake condition.",
            )
        )
    return criteria


def _infer_verification_plan(facts: RepoFacts) -> list[VerificationStep]:
    steps = [
        VerificationStep(
            id="V1",
            description="Inspect the current workspace instructions and relevant files before editing.",
            command=None,
            expected_signal="Relevant local context identified.",
        ),
        VerificationStep(
            id="V2",
            description="Review the final diff or changed files against the contract scope.",
            command="git diff --stat",
            expected_signal="Changes are limited to files required by the objective.",
        ),
    ]
    for index, command in enumerate(facts.test_commands, start=3):
        steps.append(
            VerificationStep(
                id=f"V{index}",
                description=f"Run inferred test command: {command}.",
                command=command,
                expected_signal="Command passes, or failure is explained with a current blocker and next action.",
            )
        )
    if not facts.test_commands:
        steps.append(
            VerificationStep(
                id="V3",
                description="Run the most relevant repository-specific validation found during inspection.",
                command=None,
                expected_signal="Validation result is recorded, including any reason it could not run.",
            )
        )
    return steps


def _infer_questions(objective: str, *, max_questions: int) -> list[Question]:
    lower = objective.lower()
    questions: list[Question] = []
    if any(word in lower for word in MIGRATE_WORDS) and any(
        word in lower for word in AUTH_WORDS
    ):
        questions.append(
            Question(
                id="Q_FALLBACK",
                prompt=(
                    "Should the legacy provider remain as a fallback until parity is verified, "
                    "or be removed entirely?"
                ),
                recommended_default="Keep fallback until parity is verified.",
                reason="This changes the migration safety boundary and rollback path.",
            )
        )
    if any(word in lower for word in REFACTOR_WORDS) and not any(
        phrase in lower for phrase in COMPAT_PHRASES
    ):
        questions.append(
            Question(
                id="Q_COMPAT",
                prompt=(
                    "Should public behavior be strictly backward-compatible, or are breaking "
                    "changes allowed with migration notes?"
                ),
                recommended_default="Keep behavior backward-compatible.",
                reason="This determines whether compatibility breaks are defects or accepted scope.",
            )
        )
    if (
        _has_word(lower, "api") or _has_word(lower, "public") or _has_word(lower, "sdk")
    ) and "breaking" not in lower:
        questions.append(
            Question(
                id="Q_API_SURFACE",
                prompt="Which public surface is in scope for compatibility checks?",
                recommended_default="Use the documented public API and existing tests as the compatibility surface.",
                reason="The answer prevents accidental expansion into unrelated internal APIs.",
            )
        )
    if _has_word(lower, "ci") or any(word in lower for word in DEPLOY_WORDS):
        questions.append(
            Question(
                id="Q_WAIT_CONDITION",
                prompt="What external signal should wake this goal if it must wait?",
                recommended_default="Resume only after CI, deployment, or approval produces a concrete result.",
                reason="The wake condition controls pause/defer behavior instead of active waiting.",
            )
        )
    return [question for question in questions if not _is_generic(question.prompt)][:max_questions]


def _is_generic(prompt: str) -> bool:
    lower = prompt.lower()
    return any(fragment in lower for fragment in GENERIC_QUESTION_FRAGMENTS)
