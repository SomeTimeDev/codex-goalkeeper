from __future__ import annotations

import argparse
import importlib.resources
import shutil
import sys
import time
from pathlib import Path

from .calibration import calibrate_objective
from .codex_adapter import CodexAppServerJsonRpcAdapter, DryRunCodexAdapter, PythonSdkCodexAdapter
from .contract import compact_contract_summary, paste_ready_goal, render_contract
from .doctor import collect_doctor_report, render_doctor_report
from .ledger import GoalkeeperStore, new_checkpoint_id, utc_now
from .models import Checkpoint, CommandRun, Decision, GoalkeeperContract
from .policy import evaluate_policy
from .prompts import manual_pause_instruction, manual_watch_instructions, skill_install_instructions


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"goalkeeper: error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="goalkeeper",
        description="Supervise long-running Codex goals with compact verifiable contracts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="Generate and save a Goalkeeper contract.")
    prepare.add_argument("objective")
    _add_calibration_options(prepare)
    prepare.set_defaults(func=cmd_prepare)

    start = sub.add_parser("start", help="Prepare and optionally start a supervised Codex goal.")
    start.add_argument("objective")
    _add_calibration_options(start)
    start.add_argument("--thread-id")
    start.add_argument("--dry-run", action="store_true")
    start.add_argument(
        "--app-server-goal",
        "--true-goal",
        dest="app_server_goal",
        action="store_true",
        help="Use codex app-server JSON-RPC thread/goal/set for true /goal control.",
    )
    start.add_argument(
        "--sdk-run",
        action="store_true",
        help="Run the supervised contract as a normal SDK thread turn. This is not true /goal mode.",
    )
    start.set_defaults(func=cmd_start)

    watch = sub.add_parser("watch", help="Watch a running Goalkeeper contract.")
    watch.add_argument("--contract-id", required=True)
    watch.add_argument("--thread-id")
    watch.add_argument("--interval", type=float, default=30.0)
    watch.add_argument("--once", action="store_true")
    watch.add_argument("--auto-pause", action="store_true")
    watch.add_argument(
        "--app-server-goal",
        "--true-goal",
        dest="app_server_goal",
        action="store_true",
        help="Use app-server JSON-RPC goal state and pause support when available.",
    )
    watch.add_argument("--cwd")
    watch.set_defaults(func=cmd_watch)

    attach = sub.add_parser(
        "attach",
        help="Bind an existing Goalkeeper contract to a Codex thread.",
    )
    attach.add_argument("--contract-id", required=True)
    attach.add_argument("--thread-id", required=True)
    attach.add_argument("--cwd")
    attach.add_argument("--token-budget", type=int)
    attach.add_argument("--dry-run", action="store_true")
    attach.add_argument(
        "--app-server-goal",
        "--true-goal",
        dest="app_server_goal",
        action="store_true",
        help="Also set the existing contract as the active app-server /goal for the thread.",
    )
    attach.set_defaults(func=cmd_attach)

    checkpoint = sub.add_parser("checkpoint", help="Append a manual checkpoint.")
    checkpoint.add_argument("--contract-id", required=True)
    checkpoint.add_argument("--claimed-progress", default="")
    checkpoint.add_argument("--evidence", action="append", default=[])
    checkpoint.add_argument("--criteria-closed", action="append", default=[])
    checkpoint.add_argument("--criteria-remaining", action="append", default=[])
    checkpoint.add_argument("--command", action="append", default=[])
    checkpoint.add_argument("--outcome", action="append", default=[])
    checkpoint.add_argument("--error-signature", action="append", default=[])
    checkpoint.add_argument("--changed-file", action="append", default=[])
    checkpoint.add_argument("--next-action", default="")
    checkpoint.add_argument("--waiting-on")
    checkpoint.add_argument("--cwd")
    checkpoint.set_defaults(func=cmd_checkpoint)

    status = sub.add_parser("status", help="Show contract status and loop risk.")
    status.add_argument("--contract-id", required=True)
    status.add_argument("--thread-id")
    status.add_argument("--cwd")
    status.set_defaults(func=cmd_status)

    pause = sub.add_parser("pause", help="Mark a contract paused and attempt SDK pause if possible.")
    pause.add_argument("--contract-id", required=True)
    pause.add_argument("--thread-id")
    pause.add_argument("--cwd")
    pause.set_defaults(func=cmd_pause)

    resume = sub.add_parser("resume", help="Mark a contract active and attempt SDK resume if possible.")
    resume.add_argument("--contract-id", required=True)
    resume.add_argument("--thread-id")
    resume.add_argument("--cwd")
    resume.set_defaults(func=cmd_resume)

    doctor = sub.add_parser("doctor", help="Inspect local Goalkeeper and Codex integration support.")
    doctor.add_argument("--cwd")
    doctor.set_defaults(func=cmd_doctor)

    install_skill = sub.add_parser("install-skill", help="Show or perform personal Codex skill install.")
    install_skill.add_argument("--target")
    install_skill.add_argument("--force", action="store_true")
    install_skill.set_defaults(func=cmd_install_skill)

    return parser


def _add_calibration_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cwd")
    parser.add_argument("--token-budget", type=int)
    parser.add_argument("--questions", type=int, default=3)
    parser.add_argument("--max-no-progress-turns", type=int, default=3)
    parser.add_argument("--max-same-error-retries", type=int, default=2)


def cmd_prepare(args: argparse.Namespace) -> int:
    contract, path = _prepare_contract(args)
    print(_format_prepare_output(contract, path))
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    contract, path = _prepare_contract(args)
    contract.thread_id = args.thread_id
    store = GoalkeeperStore(args.cwd)
    store.save_contract(contract)
    print(_format_prepare_output(contract, path))

    if _has_critical_questions(contract):
        print("\nStart deferred: answer the critical Goalkeeper question(s), then run start again with the clarified objective.")
        return 2

    prompt = paste_ready_goal(contract, contract_path=path)
    if args.dry_run:
        result = DryRunCodexAdapter(prompt).start_goal(args.thread_id or "", render_contract(contract), args.token_budget)
        print(f"\nDry run: {result.message}")
        print("\nPaste-ready Codex goal:")
        print(prompt)
        return 0

    if args.app_server_goal:
        adapter = CodexAppServerJsonRpcAdapter(cwd=args.cwd)
        objective = _app_server_goal_objective(contract, path)
        if args.thread_id:
            result = adapter.start_goal(args.thread_id, objective, args.token_budget)
        else:
            result = adapter.start_goal_thread(
                objective,
                cwd=args.cwd,
                token_budget=args.token_budget,
            )
        print(f"\nApp-server true goal mode: {result.message}")
        if result.thread_id:
            contract.thread_id = result.thread_id
            contract.goal_id = result.goal_id or result.thread_id
            store.save_contract(contract)
            print(f"Thread id: {result.thread_id}")
        if result.final_response:
            print(f"Goal state: {result.final_response}")
        if result.success:
            return 0
        print("\nFallback: paste this into Codex:")
        print(prompt)
        return 0

    adapter = PythonSdkCodexAdapter()
    if args.sdk_run:
        if adapter.available():
            sdk_prompt = (
                "Run this Goalkeeper supervised contract as a normal Codex SDK thread turn. "
                "This is SDK run mode, not native Codex /goal mode.\n\n"
                f"{render_contract(contract)}"
            )
            result = adapter.start_sdk_run(
                sdk_prompt,
                thread_id=args.thread_id,
                cwd=args.cwd,
                token_budget=args.token_budget,
            )
            print(f"\nSDK run mode: {result.message}")
            if result.thread_id:
                contract.thread_id = result.thread_id
                store.save_contract(contract)
                print(f"SDK thread id: {result.thread_id}")
            if result.final_response:
                print("\nSDK final response:")
                print(result.final_response)
            if result.success:
                print("\nReminder: this was a normal SDK thread run, not true Codex /goal mode.")
                return 0
        else:
            print("\nSDK run mode unavailable: openai_codex is not importable or not usable.")
        print("\nFallback: paste this into Codex:")
        print(prompt)
        return 0

    if args.thread_id:
        if adapter.available():
            capabilities = adapter.capabilities()
            if not capabilities.true_goal_control:
                print(
                    "\nTrue /goal control unsupported by the installed openai-codex SDK. "
                    "Use --sdk-run for a normal SDK thread turn, or paste the /goal fallback."
                )
                print("\nFallback: paste this into Codex:")
                print(prompt)
                return 0
            result = adapter.start_goal(args.thread_id, render_contract(contract), args.token_budget)
            print(f"\nSDK start: {result.message}")
            if result.success:
                contract.goal_id = result.goal_id
                store.save_contract(contract)
                return 0
        else:
            print("\nSDK start unavailable: openai_codex is not importable or not usable.")
    else:
        print("\nSDK start skipped: --thread-id was not provided.")

    print("\nFallback: paste this into Codex:")
    print(prompt)
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    store = GoalkeeperStore(args.cwd)
    contract = store.load_contract(args.contract_id)
    thread_id = args.thread_id or contract.thread_id
    app_adapter = CodexAppServerJsonRpcAdapter(cwd=args.cwd)
    while True:
        checkpoints = store.read_checkpoints(contract.id)
        evaluation = evaluate_policy(contract, checkpoints)
        print(_format_ledger_watch_result(contract, checkpoints, evaluation))
        _print_best_effort_goal_state(app_adapter, thread_id)

        if args.auto_pause and _should_auto_pause(evaluation):
            if not args.app_server_goal:
                print("Auto-pause requires --true-goal so Goalkeeper can use app-server goal control.")
            elif thread_id and app_adapter.available():
                if contract.status != "paused":
                    pause_result = app_adapter.pause_goal(thread_id)
                    print(f"Auto-pause: {pause_result.message}")
                    if pause_result.success:
                        _record_auto_pause(store, contract, evaluation, thread_id)
                else:
                    print("Auto-pause skipped: contract is already paused.")
            else:
                print("Auto-pause unavailable: no thread id or app-server adapter is unavailable.")

        if not checkpoints:
            print(manual_watch_instructions(contract.id))

        if args.once:
            return 0
        time.sleep(max(args.interval, 1.0))


def cmd_attach(args: argparse.Namespace) -> int:
    store = GoalkeeperStore(args.cwd)
    contract = store.load_contract(args.contract_id)
    contract.thread_id = args.thread_id
    if args.token_budget is not None:
        contract.token_budget = args.token_budget
    path = store.save_contract(contract)

    print(f"Attached Goalkeeper contract {contract.id} to Codex thread {args.thread_id}.")
    if args.dry_run:
        print("Dry run: metadata was saved, but no app-server goal was set.")
        return 0

    if not args.app_server_goal:
        print("Metadata-only attach complete.")
        print("Run with --true-goal to set this contract as the active app-server /goal.")
        return 0

    adapter = CodexAppServerJsonRpcAdapter(cwd=args.cwd)
    objective = _app_server_goal_objective(contract, path)
    result = adapter.start_goal(args.thread_id, objective, args.token_budget or contract.token_budget)
    print(f"App-server true goal attach: {result.message}")
    if result.thread_id:
        contract.thread_id = result.thread_id
    if result.goal_id:
        contract.goal_id = result.goal_id
    if result.success:
        contract.status = "active"
        store.save_contract(contract)
        if result.final_response:
            print(f"Goal state: {result.final_response}")
        print("Auto-pause can now use this thread id when app-server goal state is available.")
        return 0

    store.save_contract(contract)
    print("Attach metadata was saved, but app-server goal-control did not start.")
    print("Use status/watch to confirm whether a goal is available before relying on auto-pause.")
    return 1


def cmd_checkpoint(args: argparse.Namespace) -> int:
    store = GoalkeeperStore(args.cwd)
    contract = store.load_contract(args.contract_id)
    commands = _build_command_runs(args.command, args.outcome, args.error_signature)
    checkpoint = Checkpoint(
        id=new_checkpoint_id(),
        contract_id=contract.id,
        timestamp=utc_now(),
        claimed_progress=args.claimed_progress,
        new_evidence=_split_values(args.evidence),
        criteria_closed=_split_values(args.criteria_closed),
        criteria_remaining=_split_values(args.criteria_remaining),
        commands_run=commands,
        changed_files=_split_values(args.changed_file),
        next_action=args.next_action,
        waiting_on=args.waiting_on,
    )
    _apply_criteria_closures(contract, checkpoint)
    checkpoints = store.read_checkpoints(contract.id)
    evaluation = evaluate_policy(contract, checkpoints + [checkpoint])
    checkpoint.loop_signals = evaluation.signals
    checkpoint.progress_score = evaluation.progress_score
    checkpoint.decision = evaluation.decision
    store.append_checkpoint(checkpoint)
    if evaluation.decision == Decision.COMPLETE_CANDIDATE:
        contract.status = "complete"
    store.save_contract(contract)
    print(f"Checkpoint added: {checkpoint.id}")
    print(f"Decision: {checkpoint.decision.value}")
    print(f"Progress score: {checkpoint.progress_score}")
    print(f"Recommendation: {evaluation.explanation}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    store = GoalkeeperStore(args.cwd)
    contract = store.load_contract(args.contract_id)
    checkpoints = store.read_checkpoints(contract.id)
    evaluation = evaluate_policy(contract, checkpoints)
    thread_id = args.thread_id or contract.thread_id
    app_adapter = CodexAppServerJsonRpcAdapter(cwd=args.cwd)
    app_goal = None
    app_goal_error = None
    if thread_id and app_adapter.available():
        try:
            with app_adapter:
                app_goal = app_adapter.get_goal(thread_id)
        except Exception as exc:
            app_goal_error = str(exc)
    auto_pause_available = bool(thread_id and app_goal)

    print(compact_contract_summary(contract))
    print("\nGoal:")
    print(f"- thread id: {thread_id or '(none)'}")
    print(f"- goal id: {contract.goal_id or '(none)'}")
    print(f"- contract status: {contract.status}")
    print(f"- auto-pause available: {'yes' if auto_pause_available else 'no'}")

    print("\nAcceptance criteria:")
    closed = [criterion for criterion in contract.acceptance_criteria if criterion.status == "satisfied"]
    open_criteria = [criterion for criterion in contract.acceptance_criteria if criterion.status != "satisfied"]
    print(f"- closed: {', '.join(item.id for item in closed) if closed else 'none'}")
    print(f"- open: {', '.join(item.id for item in open_criteria) if open_criteria else 'none'}")
    for criterion in contract.acceptance_criteria:
        refs = f" Evidence: {', '.join(criterion.evidence_refs)}" if criterion.evidence_refs else ""
        print(f"- {criterion.id}: {criterion.status} - {criterion.description}{refs}")

    print("\nLast checkpoint:")
    if checkpoints:
        print(_format_checkpoint_line(checkpoints[-1]))
    else:
        print("- none")

    print("\nRecent checkpoints:")
    print(store.recent_checkpoint_summary(contract.id))
    print("\nLoop risk:")
    print(f"- decision: {evaluation.decision.value}")
    print(f"- score: {evaluation.progress_score}")
    print(f"- no-evidence streak: {evaluation.no_evidence_streak}")
    print(f"- same-error retries: {evaluation.same_error_retries}")
    print(f"- waiting streak: {evaluation.waiting_streak}")
    print(f"- recommendation: {evaluation.explanation}")
    if evaluation.signals:
        print("- signals:")
        for signal in evaluation.signals:
            print(f"  - {signal.kind} ({signal.severity}): {signal.explanation}")
    if thread_id:
        print("\nApp-server goal state:")
        if app_goal:
            print(f"- thread id: {app_goal.thread_id}")
            print(f"- status: {app_goal.status}")
            print(f"- token budget: {app_goal.token_budget}")
            print(f"- tokens used: {app_goal.tokens_used}")
        elif app_goal_error:
            print(f"- unavailable: {app_goal_error}")
        else:
            print("- no active goal")
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    store = GoalkeeperStore(args.cwd)
    contract = store.load_contract(args.contract_id)
    contract.status = "paused"
    store.save_contract(contract)
    thread_id = args.thread_id or contract.thread_id
    print(f"Goalkeeper contract paused: {contract.id}")
    if thread_id:
        app_adapter = CodexAppServerJsonRpcAdapter(cwd=args.cwd)
        if app_adapter.available():
            result = app_adapter.pause_goal(thread_id)
            print(result.message)
            if result.success:
                return 0
        adapter = PythonSdkCodexAdapter()
        if adapter.available():
            print(adapter.pause_goal(thread_id).message)
        else:
            print(manual_pause_instruction(thread_id))
    else:
        print(manual_pause_instruction())
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    store = GoalkeeperStore(args.cwd)
    contract = store.load_contract(args.contract_id)
    contract.status = "active"
    store.save_contract(contract)
    thread_id = args.thread_id or contract.thread_id
    print(f"Goalkeeper contract resumed: {contract.id}")
    if thread_id:
        app_adapter = CodexAppServerJsonRpcAdapter(cwd=args.cwd)
        if app_adapter.available():
            result = app_adapter.resume_goal(thread_id)
            print(result.message)
            if result.success:
                return 0
        adapter = PythonSdkCodexAdapter()
        if adapter.available():
            print(adapter.resume_goal(thread_id).message)
        else:
            print(f"Resume the Codex /goal for thread {thread_id} manually, then continue checkpointing.")
    else:
        print("Resume the Codex /goal manually if one is running, then continue checkpointing.")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    print(render_doctor_report(collect_doctor_report(args.cwd)))
    return 0


def cmd_install_skill(args: argparse.Namespace) -> int:
    source = _skill_source_path()
    if not args.target:
        print(skill_install_instructions(source))
        return 0
    if not source.exists():
        print(f"Skill source not found: {source}", file=sys.stderr)
        return 1
    target_root = Path(args.target).expanduser().resolve()
    destination_dir = target_root if target_root.name == "goalkeeper" else target_root / "goalkeeper"
    destination = destination_dir / "SKILL.md"
    if destination.exists() and not args.force:
        print(f"Refusing to overwrite existing skill without --force: {destination}", file=sys.stderr)
        return 1
    destination_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    print(f"Installed Goalkeeper skill to {destination}")
    print("This does not add a native /goalkeeper slash command.")
    return 0


def _prepare_contract(args: argparse.Namespace) -> tuple[GoalkeeperContract, Path]:
    contract = calibrate_objective(
        args.objective,
        cwd=args.cwd,
        token_budget=args.token_budget,
        max_questions=args.questions,
        max_no_progress_turns=args.max_no_progress_turns,
        max_same_error_retries=args.max_same_error_retries,
    )
    store = GoalkeeperStore(args.cwd)
    path = store.save_contract(contract)
    return contract, path


def _format_prepare_output(contract: GoalkeeperContract, path: Path) -> str:
    prompt = paste_ready_goal(contract, contract_path=path)
    question_lines = ["Questions:"]
    if contract.questions:
        for question in contract.questions:
            question_lines.append(f"- {question.id}: {question.prompt}")
            question_lines.append(f"  Recommended default: {question.recommended_default}")
            question_lines.append(f"  Why it matters: {question.reason}")
    else:
        question_lines.append("- None.")
    assumptions = "\n".join(f"- {item}" for item in contract.assumptions)
    return f"""Goalkeeper contract prepared
Contract id: {contract.id}
Status: {contract.status}
Saved contract: {path}

Assumptions:
{assumptions}

{chr(10).join(question_lines)}

Generated contract:
{render_contract(contract)}

Paste-ready Codex goal:
{prompt}
"""


def _format_watch_result(checkpoint: Checkpoint, evaluation) -> str:
    return f"""Checkpoint: {checkpoint.id}
Decision: {evaluation.decision.value}
Progress score: {evaluation.progress_score}
Recommendation: {evaluation.explanation}
"""


def _format_ledger_watch_result(
    contract: GoalkeeperContract,
    checkpoints: list[Checkpoint],
    evaluation,
) -> str:
    last_checkpoint = _format_checkpoint_line(checkpoints[-1]) if checkpoints else "- none"
    return f"""Goalkeeper ledger watch
Contract: {contract.id}
Status: {contract.status}
Checkpoints: {len(checkpoints)}
Last checkpoint:
{last_checkpoint}
Decision: {evaluation.decision.value}
Progress score: {evaluation.progress_score}
No-evidence streak: {evaluation.no_evidence_streak}
Same-error retries: {evaluation.same_error_retries}
Waiting streak: {evaluation.waiting_streak}
Recommendation: {evaluation.explanation}
"""


def _format_checkpoint_line(checkpoint: Checkpoint) -> str:
    claimed = checkpoint.claimed_progress or "(no claimed progress)"
    return (
        f"- {checkpoint.timestamp} {checkpoint.id}: {checkpoint.decision.value}, "
        f"score {checkpoint.progress_score}, {claimed}"
    )


def _should_auto_pause(evaluation) -> bool:
    return evaluation.decision in {
        Decision.PAUSE_RECOMMENDED,
        Decision.DEFER_RECOMMENDED,
        Decision.REPLAN_REQUIRED,
    }


def _record_auto_pause(
    store: GoalkeeperStore,
    contract: GoalkeeperContract,
    evaluation,
    thread_id: str,
) -> None:
    reason = f"Auto-paused by Goalkeeper watch: {evaluation.decision.value}. {evaluation.explanation}"
    checkpoint = Checkpoint(
        id=new_checkpoint_id(),
        contract_id=contract.id,
        timestamp=utc_now(),
        claimed_progress=reason,
        criteria_remaining=[
            criterion.id
            for criterion in contract.acceptance_criteria
            if criterion.status != "satisfied"
        ],
        next_action="Inspect the loop signal, replan or wait for the wake condition, then resume deliberately.",
        waiting_on=(
            "External state or user decision"
            if evaluation.decision == Decision.DEFER_RECOMMENDED
            else None
        ),
        loop_signals=evaluation.signals,
        progress_score=evaluation.progress_score,
        decision=Decision.PAUSED,
    )
    store.append_checkpoint(checkpoint)
    contract.status = "paused"
    contract.thread_id = contract.thread_id or thread_id
    store.save_contract(contract)
    print(f"Recorded auto-pause checkpoint: {checkpoint.id}")


def _print_best_effort_goal_state(
    app_adapter: CodexAppServerJsonRpcAdapter,
    thread_id: str | None,
) -> None:
    if not thread_id or not app_adapter.available():
        return
    try:
        with app_adapter:
            goal = app_adapter.get_goal(thread_id)
        if goal:
            print(
                f"App-server goal: status={goal.status}, "
                f"tokens={goal.tokens_used}/{goal.token_budget}"
            )
        else:
            print("App-server goal: none")
    except Exception as exc:
        print(f"App-server goal state unavailable: {exc}")


def _app_server_goal_objective(contract: GoalkeeperContract, path: Path) -> str:
    rendered = render_contract(contract)
    if len(rendered) <= 4000:
        return rendered
    absolute = path.expanduser().resolve()
    return (
        f"Read the Goalkeeper contract at {absolute} and pursue it exactly. "
        f"Contract id: {contract.id}. User objective: {contract.raw_user_objective}"
    )


def _has_critical_questions(contract: GoalkeeperContract) -> bool:
    return any(question.critical for question in contract.questions)


def _build_command_runs(
    commands: list[str],
    outcomes: list[str],
    error_signatures: list[str],
) -> list[CommandRun]:
    runs = []
    for index, command in enumerate(commands):
        outcome = outcomes[index] if index < len(outcomes) else "unknown"
        if outcome not in {"passed", "failed", "partial", "not_run", "unknown"}:
            outcome = "unknown"
        error_signature = error_signatures[index] if index < len(error_signatures) else None
        runs.append(
            CommandRun(
                command=command,
                outcome=outcome,
                summary=f"Recorded outcome: {outcome}",
                error_signature=error_signature,
            )
        )
    return runs


def _split_values(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        for part in value.split(","):
            item = part.strip()
            if item:
                result.append(item)
    return result


def _apply_criteria_closures(contract: GoalkeeperContract, checkpoint: Checkpoint) -> None:
    evidence = checkpoint.new_evidence or [checkpoint.claimed_progress]
    for criterion in contract.acceptance_criteria:
        if criterion.id in checkpoint.criteria_closed:
            criterion.status = "satisfied"
            for item in evidence:
                if item and item not in criterion.evidence_refs:
                    criterion.evidence_refs.append(item)


def _skill_source_path() -> Path:
    source_tree_path = Path(__file__).resolve().parents[1] / "skills" / "goalkeeper" / "SKILL.md"
    if source_tree_path.exists():
        return source_tree_path
    return Path(
        str(
            importlib.resources.files("goalkeeper").joinpath(
                "assets",
                "skills",
                "goalkeeper",
                "SKILL.md",
            )
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
