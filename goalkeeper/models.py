from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal


ContractStatus = Literal["active", "pending_questions", "paused", "complete", "blocked"]
CriterionStatus = Literal["open", "satisfied", "unknown"]
CommandOutcome = Literal["passed", "failed", "partial", "not_run", "unknown"]
Severity = Literal["low", "medium", "high"]


class Decision(str, Enum):
    CONTINUE = "continue"
    CONTINUE_WITH_REQUIRED_NEXT_ACTION = "continue_with_required_next_action"
    REPLAN_REQUIRED = "replan_required"
    PAUSE_RECOMMENDED = "pause_recommended"
    PAUSED = "paused"
    DEFER_RECOMMENDED = "defer_recommended"
    ASK_USER = "ask_user"
    COMPLETE_CANDIDATE = "complete_candidate"
    BLOCKED_CANDIDATE = "blocked_candidate"


@dataclass
class AcceptanceCriterion:
    id: str
    description: str
    evidence_required: str
    status: CriterionStatus = "open"
    evidence_refs: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AcceptanceCriterion:
        return cls(
            id=str(data["id"]),
            description=str(data["description"]),
            evidence_required=str(data["evidence_required"]),
            status=data.get("status", "open"),
            evidence_refs=list(data.get("evidence_refs", [])),
        )


@dataclass
class VerificationStep:
    id: str
    description: str
    command: str | None = None
    expected_signal: str = ""
    last_result: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VerificationStep:
        return cls(
            id=str(data["id"]),
            description=str(data["description"]),
            command=data.get("command"),
            expected_signal=str(data.get("expected_signal", "")),
            last_result=data.get("last_result"),
        )


@dataclass
class Question:
    id: str
    prompt: str
    recommended_default: str
    reason: str
    critical: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Question:
        return cls(
            id=str(data["id"]),
            prompt=str(data["prompt"]),
            recommended_default=str(data["recommended_default"]),
            reason=str(data["reason"]),
            critical=bool(data.get("critical", True)),
        )


@dataclass
class LoopPolicy:
    max_no_progress_turns: int = 3
    max_same_error_retries: int = 2
    max_waiting_turns: int = 2
    max_plan_only_turns: int = 2
    max_criteria_stall_turns: int = 5
    max_checkpoint_gap_minutes: int = 45

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LoopPolicy:
        return cls(
            max_no_progress_turns=int(data.get("max_no_progress_turns", 3)),
            max_same_error_retries=int(data.get("max_same_error_retries", 2)),
            max_waiting_turns=int(data.get("max_waiting_turns", 2)),
            max_plan_only_turns=int(data.get("max_plan_only_turns", 2)),
            max_criteria_stall_turns=int(data.get("max_criteria_stall_turns", 5)),
            max_checkpoint_gap_minutes=int(data.get("max_checkpoint_gap_minutes", 45)),
        )


@dataclass
class WaitPolicy:
    detect_waiting: bool = True
    pause_on_waiting: bool = True
    wake_condition: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WaitPolicy:
        return cls(
            detect_waiting=bool(data.get("detect_waiting", True)),
            pause_on_waiting=bool(data.get("pause_on_waiting", True)),
            wake_condition=data.get("wake_condition"),
        )


@dataclass
class GoalkeeperContract:
    id: str
    created_at: str
    updated_at: str
    raw_user_objective: str
    normalized_objective: str
    scope: list[str]
    non_goals: list[str]
    assumptions: list[str]
    acceptance_criteria: list[AcceptanceCriterion]
    verification_plan: list[VerificationStep]
    loop_policy: LoopPolicy
    wait_policy: WaitPolicy
    status: ContractStatus = "active"
    questions: list[Question] = field(default_factory=list)
    thread_id: str | None = None
    goal_id: str | None = None
    token_budget: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoalkeeperContract:
        return cls(
            id=str(data["id"]),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            raw_user_objective=str(data["raw_user_objective"]),
            normalized_objective=str(data["normalized_objective"]),
            scope=list(data.get("scope", [])),
            non_goals=list(data.get("non_goals", [])),
            assumptions=list(data.get("assumptions", [])),
            acceptance_criteria=[
                AcceptanceCriterion.from_dict(item)
                for item in data.get("acceptance_criteria", [])
            ],
            verification_plan=[
                VerificationStep.from_dict(item) for item in data.get("verification_plan", [])
            ],
            loop_policy=LoopPolicy.from_dict(data.get("loop_policy", {})),
            wait_policy=WaitPolicy.from_dict(data.get("wait_policy", {})),
            status=data.get("status", "active"),
            questions=[Question.from_dict(item) for item in data.get("questions", [])],
            thread_id=data.get("thread_id"),
            goal_id=data.get("goal_id"),
            token_budget=data.get("token_budget"),
        )


@dataclass
class CommandRun:
    command: str
    outcome: CommandOutcome = "unknown"
    summary: str = ""
    error_signature: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommandRun:
        return cls(
            command=str(data.get("command", "")),
            outcome=data.get("outcome", "unknown"),
            summary=str(data.get("summary", "")),
            error_signature=data.get("error_signature"),
        )


@dataclass
class LoopSignal:
    kind: str
    severity: Severity
    explanation: str
    evidence: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LoopSignal:
        return cls(
            kind=str(data.get("kind", "")),
            severity=data.get("severity", "low"),
            explanation=str(data.get("explanation", "")),
            evidence=list(data.get("evidence", [])),
        )


@dataclass
class Checkpoint:
    id: str
    contract_id: str
    timestamp: str
    turn_id: str | None = None
    claimed_progress: str = ""
    new_evidence: list[str] = field(default_factory=list)
    criteria_closed: list[str] = field(default_factory=list)
    criteria_remaining: list[str] = field(default_factory=list)
    commands_run: list[CommandRun] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    next_action: str = ""
    waiting_on: str | None = None
    loop_signals: list[LoopSignal] = field(default_factory=list)
    progress_score: int = 0
    decision: Decision = Decision.CONTINUE
    source: str = "manual"
    observed_changed_files: list[str] = field(default_factory=list)
    git_head: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["decision"] = self.decision.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        decision_value = data.get("decision", Decision.CONTINUE.value)
        return cls(
            id=str(data["id"]),
            contract_id=str(data["contract_id"]),
            timestamp=str(data["timestamp"]),
            turn_id=data.get("turn_id"),
            claimed_progress=str(data.get("claimed_progress", "")),
            new_evidence=list(data.get("new_evidence", [])),
            criteria_closed=list(data.get("criteria_closed", [])),
            criteria_remaining=list(data.get("criteria_remaining", [])),
            commands_run=[CommandRun.from_dict(item) for item in data.get("commands_run", [])],
            changed_files=list(data.get("changed_files", [])),
            next_action=str(data.get("next_action", "")),
            waiting_on=data.get("waiting_on"),
            loop_signals=[LoopSignal.from_dict(item) for item in data.get("loop_signals", [])],
            progress_score=int(data.get("progress_score", 0)),
            decision=Decision(decision_value),
            source=str(data.get("source", "manual")),
            observed_changed_files=list(data.get("observed_changed_files", [])),
            git_head=data.get("git_head"),
        )
