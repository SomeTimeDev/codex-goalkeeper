---
name: goalkeeper
description: Use Goalkeeper to prepare, start, checkpoint, and supervise long-running Codex goals from a local standalone CLI. Trigger on phrases like "Use Goalkeeper for:", "Goalkeeper:", or "Run goalkeeper on this objective:".
---

# Goalkeeper Skill

Use this skill when the user asks to use Goalkeeper for a long-running Codex goal, including phrases such as:

- "Use Goalkeeper for: <objective>"
- "Goalkeeper: <objective>"
- "Run goalkeeper on this objective: <objective>"

Goalkeeper is a standalone personal companion tool. It does not add a native `/goalkeeper` slash command, does not fork Codex, and does not modify Codex source.

## Workflow

1. Extract the user's objective exactly.
2. Run:

   ```bash
   goalkeeper prepare "<objective>"
   ```

3. If Goalkeeper prints critical questions, ask only those questions. Keep the recommended defaults visible. After the user answers, record them with:

   ```bash
   goalkeeper answer --contract-id <id> --answer Q_ID="answer"
   ```

   If the user explicitly wants Goalkeeper defaults, use `--assume-defaults` on prepare/start instead of inventing answers.
4. After questions are answered or defaults are assumed, run:

   ```bash
   goalkeeper start --contract-id <id> --true-goal
   ```

   Include `--cwd`, `--thread-id`, or `--token-budget` when the user provided them or the local task context clearly supplies them. Prefer `--true-goal` for normal Goalkeeper starts so the contract records a Codex thread id and can later support app-server pause/resume/watch. Use `goalkeeper start "<objective>" --assume-defaults --true-goal` only when the user accepts the recommended defaults. Use contract-only mode only when true goal-control is unavailable or the user asks for a paste-ready contract only. Use `--sdk-run` only when the user explicitly wants a normal Codex SDK thread run and understands that this is not native `/goal` mode.

5. After start, run:

   ```bash
   goalkeeper status --contract-id <id>
   ```

   Confirm the status shows a thread id. If the contract was already created in contract-only mode and a Codex thread id is known, bind it with:

   ```bash
   goalkeeper attach --contract-id <id> --thread-id <codex-thread-id> --true-goal
   ```

6. If true goal-control start is unavailable, use the generated paste-ready `/goal` contract as the Codex goal objective. Keep checkpointing even in contract-only mode.
7. During long-running work, record checkpoints with:

   ```bash
   goalkeeper checkpoint --contract-id <id> --claimed-progress "..." --evidence "..." --next-action "..."
   ```

   The generated Goalkeeper contract contains the exact checkpoint command shape. Do not let a long-running goal continuation end without either recording a checkpoint or explaining why no checkpoint could be recorded.

   Before each checkpoint, re-read the contract file at `.goalkeeper/contracts/<id>.json` and check that the current work maps to an open acceptance criterion. If it does not, stop and replan instead of continuing.

   For command outcomes, prefer letting Goalkeeper measure instead of self-reporting:

   ```bash
   goalkeeper verify --contract-id <id>
   ```

   `verify` runs the contract's verification plan itself and records an authoritative checkpoint with real command results. Goalkeeper also snapshots git state at every checkpoint; claimed file changes that are not visible in git are flagged as `unverified_file_claim`.

   Or ask the user to run:

   ```bash
   goalkeeper watch --contract-id <id> --auto-pause --true-goal
   ```

8. Respect Goalkeeper recommendations. If it says `replan_required`, stop repeating the same failure and make a new hypothesis; the `criteria_stalled` signal means activity is not closing acceptance criteria (scope drift) — replan against the contract criteria. If it says `pause_recommended` or `defer_recommended`, pause or ask the user instead of continuing low-value turns. If it says `ask_user` with a `checkpoint_gap` signal, the ledger is stale: confirm the goal state and record a fresh checkpoint before continuing.

## Important Boundaries

- This skill does not create a native `/goalkeeper` slash command.
- Native slash command support would require a future Codex plugin, fork, or native integration.
- Goalkeeper's contract-only mode is always valid.
- SDK run mode is a normal Codex SDK thread turn, not true `/goal` mode.
- SDK watch is best-effort and depends on local Codex SDK/app-server availability.
- True goal start, pause, and resume use verified app-server JSON-RPC `thread/goal/*` methods when available.
