# Goalkeeper

A small safety layer for big Codex goals.

Goalkeeper is a standalone personal companion for long-running Codex `/goal`
work. It takes a normal objective, turns it into a compact contract, asks only
the questions that matter, records checkpoints, and watches for loops before
they turn into wasted hours.

Think of it as a seatbelt and flight recorder for Codex goals: quiet most of
the time, very useful when the work starts drifting.

Goalkeeper is not a fork of Codex. It does not patch Codex source. This MVP
does not add a native `/goalkeeper` slash command.

This is alpha software. It is useful, but intentionally conservative:
true goal-control depends on local Codex app-server behavior, and supervision
quality depends on checkpoints being recorded.

```bash
goalkeeper start "refactor billing module without breaking public API" --true-goal
```

If true Codex goal-control is unavailable, Goalkeeper still produces a
paste-ready `/goal` contract. Contract-only mode always works.

## What Is Goalkeeper?

Goalkeeper is a Python CLI that helps Codex goals stay aligned with evidence.

It does five simple things:

- turns an objective into a verifiable goal contract,
- stores that contract and a compact checkpoint ledger,
- gives Codex a checkpoint rule to follow during long-running work,
- runs the contract's verification plan itself (`goalkeeper verify`) so command
  outcomes are measured, not self-reported,
- recommends continue, replan, pause, or defer when progress stops being real.

The point is not to replace Codex `/goal`. The point is to make `/goal` easier
to trust when the job is long, fuzzy, or expensive to get wrong.

## Why Long-Running `/goal` Needs Supervision

Long-running coding work can quietly go sideways. Not dramatically, usually.
More like this:

- the same failing command gets retried without a new hypothesis,
- the work waits for CI or user input but keeps spending active turns,
- the agent reports plans instead of evidence,
- the same files churn without closing acceptance criteria,
- scope expands because there is always one more nearby thing to improve,
- "done" arrives before the current state proves it.

Goalkeeper makes the stop signs visible. It asks for evidence, keeps a ledger,
and says when the next useful move is not another continuation.

## Installation

From a local checkout:

```bash
python -m pip install -e .
```

From GitHub once you publish your repository:

```bash
python -m pip install git+https://github.com/SomeTimeDev/codex-goalkeeper.git
```

For development:

```bash
python -m pip install -e ".[dev]"
```

For optional Codex SDK experiments:

```bash
python -m pip install -e ".[codex]"
```

Python 3.11 or newer is required.

## Quick Start

Prepare a contract:

```bash
goalkeeper prepare "migrate auth provider but keep login compatible"
```

If Goalkeeper asks critical questions, answer them:

```bash
goalkeeper answer --contract-id gk_example --answer Q_FALLBACK="keep fallback"
goalkeeper start --contract-id gk_example --true-goal
```

Or deliberately accept the recommended defaults:

```bash
goalkeeper start "migrate auth provider but keep login compatible" --assume-defaults --true-goal
```

Start a true app-server goal when available:

```bash
goalkeeper start "refactor billing module without breaking public API" --true-goal
```

Check what Goalkeeper thinks is happening:

```bash
goalkeeper status --contract-id gk_example
```

Record a checkpoint:

```bash
goalkeeper checkpoint --contract-id gk_example \
  --claimed-progress "Updated billing service boundaries" \
  --evidence "pytest passed for billing tests" \
  --criteria-closed AC1 \
  --criteria-remaining "AC2,AC3" \
  --command "pytest tests/billing" \
  --outcome passed \
  --changed-file "billing/service.py" \
  --next-action "Review public API compatibility"
```

Let Goalkeeper measure instead of trusting claims:

```bash
goalkeeper verify --contract-id gk_example
```

Watch once, using the ledger as the source of truth:

```bash
goalkeeper watch --contract-id gk_example --once
```

If true goal-control is unavailable, Goalkeeper prints the exact `/goal ...`
text to paste into Codex.

## CLI Usage

### `goalkeeper prepare "<objective>"`

Analyzes the objective, applies deterministic calibration, saves a contract
under `.goalkeeper/contracts/`, and prints a paste-ready Codex `/goal`.

Goalkeeper only asks targeted questions when the answer changes implementation.
If a critical question remains, the contract is saved as `pending_questions`.
Use `goalkeeper answer` to record answers, or `--assume-defaults` to accept
Goalkeeper's recommended defaults as assumptions.

Calibration keywords understand English and Turkish objectives.

Add objective-specific acceptance criteria with repeatable `--criterion` flags,
because concrete criteria supervise better than generic ones:

```bash
goalkeeper prepare "add health endpoint" \
  --criterion "GET /health returns 200 with build info" \
  --criterion "Endpoint is covered by an integration test"
```

Tune drift and staleness thresholds when needed:

```bash
goalkeeper prepare "<objective>" --max-criteria-stall-turns 5 --max-checkpoint-gap-minutes 45
```

### `goalkeeper start "<objective>"`

Runs prepare, finalizes the contract if no critical question remains, and then
tries to start the supervised Codex work.

Common options:

```bash
goalkeeper start "<objective>" --cwd C:\path\to\repo --token-budget 50000
goalkeeper start "<objective>" --thread-id <codex-thread-id> --true-goal
goalkeeper start "<objective>" --true-goal
goalkeeper start "<objective>" --dry-run
goalkeeper start "<objective>" --sdk-run
goalkeeper start --contract-id gk_abc123 --true-goal
goalkeeper start "<objective>" --assume-defaults --true-goal
goalkeeper start "<objective>" --max-no-progress-turns 3 --max-same-error-retries 2
```

`--true-goal` uses `codex app-server --listen stdio://` and verified JSON-RPC
methods: `thread/start`, `thread/goal/set`, `thread/goal/get`,
`thread/goal/clear`, and `thread/read`.

`--dry-run` does not start Codex. It prints the contract and paste-ready goal.

`--sdk-run` is not true `/goal` mode. It runs the supervised contract as a
normal Codex SDK thread turn when the SDK exposes `thread.run()`.

Goalkeeper uses a conservative 4000-character default for inline generated
goal objectives. If the rendered `/goal <contract>` would exceed that limit,
it falls back to a short file reference.

### `goalkeeper answer --contract-id <id> --answer Q_ID=value`

Records answers for pending critical questions:

```bash
goalkeeper answer --contract-id gk_abc123 --answer Q_FALLBACK="keep fallback"
goalkeeper start --contract-id gk_abc123 --true-goal
```

Answers are stored as assumptions, the original question remains in the
contract for audit, and answered questions are marked non-critical. When no
critical questions remain, the contract becomes `active`.

### `goalkeeper attach --contract-id <id> --thread-id <id>`

Binds an existing Goalkeeper contract to an existing Codex thread.

This is the recovery move when a goal started in contract-only mode but you
later know the Codex thread id:

```bash
goalkeeper attach --contract-id gk_abc123 --thread-id <codex-thread-id> --true-goal
```

With `--true-goal`, Goalkeeper also sets that contract as the active app-server
goal for the thread. Without `--true-goal`, it only records the thread id
metadata.

### `goalkeeper watch --contract-id <id>`

Evaluates the checkpoint ledger and prints a recommendation.

```bash
goalkeeper watch --contract-id gk_abc123 --once
goalkeeper watch --contract-id gk_abc123 --interval 60 --auto-pause --true-goal
```

Watch mode is ledger-first. App-server `thread/read` is best-effort context,
not the source of truth for loop detection.

With `--auto-pause --true-goal`, Goalkeeper pauses the app-server goal when the
ledger crosses no-progress, same-error, or waiting-only thresholds. Auto-pause
is intentionally disabled without `--true-goal`.

### `goalkeeper checkpoint --contract-id <id>`

Adds one compact checkpoint to `.goalkeeper/ledgers/<id>.jsonl`.

Useful fields:

- `--claimed-progress`
- `--evidence`
- `--criteria-closed`
- `--criteria-remaining`
- `--command`
- `--outcome`
- `--error-signature`
- `--changed-file`
- `--next-action`
- `--waiting-on`

Each checkpoint also snapshots git state (HEAD hash and dirty paths) when the
workspace is a git repository. If a checkpoint claims changed files that are
not visible in git and the HEAD did not move since the previous checkpoint,
the claim is flagged as `unverified_file_claim`.

After recording, the command prints the decision plus a contract anchor: the
normalized objective, the open acceptance criteria, and the contract file
path. This re-injects the goal into the agent's context on every turn.

### `goalkeeper verify --contract-id <id>`

Runs the contract's verification plan commands itself and records an
authoritative checkpoint with the real outcomes. This is the antidote to
optimistic self-reporting: evidence comes from measured command results, not
from claims.

```bash
goalkeeper verify --contract-id gk_abc123
goalkeeper verify --contract-id gk_abc123 --step V3 --timeout 300
```

Steps without a command are reported as manual. Each executed step's
`last_result` is stored on the contract. The command exits non-zero when any
step fails, so a failing verification is visible to scripts and agents.

### `goalkeeper status --contract-id <id>`

Shows the contract summary, active thread/goal id, criteria state, last
checkpoint, recent checkpoints, loop risk, recommendation, and whether
auto-pause is available.

### `goalkeeper pause --contract-id <id>`

Marks the contract paused. If a thread id is known and app-server goal-control
is available, Goalkeeper attempts to pause the underlying Codex goal.
Otherwise it prints the manual pause action.

### `goalkeeper resume --contract-id <id>`

Marks the contract active again and attempts app-server resume when possible.

### `goalkeeper doctor`

Checks the local environment passively:

- Python version,
- storage location,
- `openai_codex` import status and detected version,
- whether `codex` is on PATH,
- SDK run-mode capabilities,
- app-server binary availability.

The default command does not start Codex app-server and does not create probe
threads:

```bash
goalkeeper doctor
```

To validate true app-server goal-control, opt in to the live probe:

```bash
goalkeeper doctor --live-probe
```

`--live-probe` may create a temporary persisted Codex thread, set a probe goal,
pause it, clear it, and attempt to archive the probe thread.

### `goalkeeper install-skill`

Prints instructions for installing the included personal Codex skill.

If you know your Codex skills directory:

```bash
goalkeeper install-skill --target C:\path\to\codex\skills
```

Goalkeeper is conservative about Codex config paths. It does not guess a native
installation location unless you provide one.

The pip-installed package includes the skill asset, so `install-skill` works
from both a source checkout and a `pip install git+...` installation.

## Codex Skill Usage

This repository includes:

```text
skills/goalkeeper/SKILL.md
```

After installing the skill, ask Codex:

```text
Use Goalkeeper for: refactor billing module without breaking public API
```

The skill tells Codex to run the local Goalkeeper CLI, ask any critical
Goalkeeper questions, prefer `--true-goal` when available, checkpoint during
long work, and respect pause/replan recommendations.

Important: this skill does not create a native `/goalkeeper` slash command.

## Contract-Only Mode

Contract-only mode always works.

Goalkeeper writes a local contract and prints:

```text
/goal <goalkeeper_contract id="...">
...
</goalkeeper_contract>
```

If the command would exceed the conservative 4000-character default, Goalkeeper
saves the contract and prints a shorter goal:

```text
/goal Read the Goalkeeper contract at <path> and pursue it exactly.
```

This mode gives Codex the same contract and checkpoint rule, but Goalkeeper
cannot automatically pause or resume the Codex goal.

## SDK Mode

SDK run mode is optional and deliberately separate from true `/goal` control.

Goalkeeper imports `openai_codex` only inside the SDK adapter, inspects the
available methods at runtime, and only calls methods that actually exist.

During development, the inspected public SDK surface exposed normal thread
operations such as:

- `Codex.thread_start(...)`
- `Codex.thread_resume(...)`
- `Thread.run(...)`
- `Thread.read(...)`

It did not expose verified public `/goal` lifecycle methods. Goalkeeper
therefore labels this as SDK run mode, not true goal-control mode.

```bash
goalkeeper start "refactor billing module without breaking public API" --sdk-run --cwd C:\path\to\repo
```

## True Goal-Control Mode

True goal-control means Goalkeeper can set a Codex `/goal`, read its goal
state, and attempt pause/resume through app-server JSON-RPC.

Goalkeeper starts:

```bash
codex app-server --listen stdio://
```

Then it performs the JSON-RPC `initialize` / `initialized` handshake and uses
verified app-server methods:

- `thread/start`
- `thread/goal/set`
- `thread/goal/get`
- `thread/goal/clear`
- `thread/read`

If the rendered contract is over 4000 characters, Goalkeeper stores the
contract JSON locally and sends Codex a short objective that points to the
contract path.

The current app-server response may not expose a separate goal id. In that
case Goalkeeper records the thread id for app-server operations and shows the
goal id as unavailable instead of pretending the thread id is a goal id.

If a Codex session was already started, use attach:

```bash
goalkeeper attach --contract-id <id> --thread-id <codex-thread-id> --true-goal
```

## Watch Mode

Watch mode reads the Goalkeeper ledger first.

The generated contract tells Codex:

```bash
goalkeeper checkpoint --contract-id <id> --claimed-progress "..." --evidence "..." --criteria-closed "AC1" --criteria-remaining "AC2,AC3" --command "pytest" --outcome passed --changed-file "path/to/file" --next-action "..."
```

Codex should not end a goal continuation turn without either recording a
checkpoint or explaining why no checkpoint could be recorded.

When automatic watch is unavailable, manual checkpointing still gives useful
status and loop-risk decisions:

```bash
goalkeeper checkpoint --contract-id <id> --claimed-progress "..." --evidence "..." --next-action "..."
goalkeeper status --contract-id <id>
```

`--once` is safe for tests and one-shot checks.

## Loop Detection Policy

Goalkeeper scores checkpoints with deterministic heuristics.

Positive signals:

- acceptance criterion closed,
- new verification evidence,
- relevant test passed,
- relevant file changed,
- useful blocker identified,
- external state or user decision changed.

Negative signals:

- no new evidence,
- same command repeated with the same result,
- same error signature repeated (including alternating retries such as A-B-A-B),
- waiting while active,
- same files churned without criterion movement,
- sustained activity that closes no acceptance criterion (`criteria_stalled`,
  the scope-drift pattern),
- claimed file changes not visible in git (`unverified_file_claim`),
- an active contract with a stale ledger (`checkpoint_gap`),
- plan-only updates,
- repeated inspection without action.

Decisions include:

- `continue`
- `continue_with_required_next_action`
- `replan_required`
- `pause_recommended`
- `defer_recommended`
- `ask_user`
- `complete_candidate`
- `blocked_candidate`

Two thresholds target the classic failure modes of long-running goals:

- `criteria_stalled`: after `--max-criteria-stall-turns` active checkpoints
  (default 5) without closing a criterion, the recommendation becomes
  `replan_required`. Motion that does not map to the goal is drift, not
  progress.
- `checkpoint_gap`: when an active contract records no checkpoint for
  `--max-checkpoint-gap-minutes` (default 45), the recommendation becomes
  `ask_user`. A silent ledger is itself a signal; supervision that trusts a
  stale ledger supervises nothing.

The goal is not drama. The goal is explainable friction at the moment friction
is useful.

## Wait/Defer Handling

If the next useful action depends on CI, deployment, future time, approval,
user input, or another external condition, Goalkeeper recommends pause or
defer instead of spending more active turns.

A waiting checkpoint should record:

- what is being waited on,
- the wake condition,
- the next action after the wake condition is met.

## Storage And Privacy

By default, Goalkeeper stores state under the selected `--cwd` or current
directory:

```text
.goalkeeper/
  contracts/
    gk_<id>.json
  ledgers/
    gk_<id>.jsonl
  reports/
    gk_<id>_summary.md
```

Goalkeeper does not intentionally store secrets. It stores compact
user-provided summaries, not huge logs. Do not paste private command output
into checkpoints unless you want it persisted locally.

## Limitations

- Goalkeeper is alpha/experimental.
- Goalkeeper does not add a native `/goalkeeper` command.
- Goalkeeper does not replace Codex `/goal`.
- Contract-only mode cannot auto-pause or resume Codex.
- SDK run mode is a normal SDK thread turn, not true `/goal` mode.
- True goal-control depends on `codex app-server` and verified
  `thread/goal/*` JSON-RPC methods.
- `goalkeeper doctor` is passive by default; `doctor --live-probe` can create
  a temporary probe thread.
- Auto-pause only works when app-server goal pause via `thread/goal/set`
  succeeds.
- Watch mode is best-effort around Codex thread reading.
- Supervisor decisions depend on checkpoints. A silent ledger is now flagged
  (`checkpoint_gap`) and `goalkeeper verify` measures command outcomes
  directly, but the quality of free-text evidence claims is still not judged.
- Calibration is deterministic and conservative. It does not call external LLM
  APIs. Use `--criterion` to add objective-specific acceptance criteria.
- Loop detection is explainable but imperfect.

## Roadmap

- richer checkpoint extraction from Codex thread events,
- stronger repository-aware verification inference,
- optional report generation under `.goalkeeper/reports/`,
- configurable storage roots,
- richer app-server event monitoring,
- better packaging for personal Codex skill distribution,
- native Codex plugin integration if the standalone workflow proves useful.

## Development/Testing

Install dev dependencies:

```bash
python -m pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

Run Ruff:

```bash
ruff check .
```

Run the CLI from source:

```bash
python -m goalkeeper.cli doctor
```

The repository also includes a small GitHub Actions workflow that runs tests
and Ruff on pushes and pull requests.

## Future Native Codex Integration

A future version could become a Codex plugin or native extension with:

- `/goalkeeper <objective>` slash command,
- goal lifecycle hooks,
- first-class checkpoint tools,
- pause/defer integration,
- thread event subscriptions,
- UI for contract status and wake conditions.

That is future work. This MVP stays standalone on purpose: useful today,
replaceable later, and honest about the line between "contract", "SDK run", and
true goal-control.
