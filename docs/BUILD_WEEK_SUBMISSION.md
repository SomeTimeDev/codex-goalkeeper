# Proofkeeper — OpenAI Build Week Submission Draft

## Category

Developer Tools

## Tagline

Codex can keep working. Proofkeeper makes it earn the right to continue.

## Project Description

Long-running coding agents can pass tests and still drift: they add an unnecessary
service layer, touch unrelated files, repeat a stale plan, or declare completion
before the current repository state supports the claim.

Proofkeeper is an evidence-first runtime supervisor for Codex. It converts a user
objective into a verifiable Goalkeeper contract, records a compact checkpoint
ledger, and adds one closed proof command:

```bash
goalkeeper prove --contract-id <id> --base HEAD
```

The command runs real verification steps, inspects the Git diff with ScopeProof,
updates only the acceptance criteria supported by current evidence, and writes a
reproducible JSON and Markdown evidence bundle. It returns one operational gate:

- **CONTINUE** — evidence is current; work may continue only toward open criteria.
- **REPLAN** — verification failed or the diff escaped scope.
- **PAUSE** — the evidence chain is unavailable or a decision is required.
- **COMPLETE** — tests and scope checks pass and every criterion has evidence.

The demo makes the distinction visible. A focused calculator change passes and
reaches COMPLETE. The same passing tests plus an unnecessary service module are
blocked with REPLAN. Proofkeeper therefore checks more than “did the tests pass?”;
it asks “did the agent solve the requested problem without quietly changing the
problem?”

## Why It Matters

The target audience is any developer or team delegating multi-step repository work
to coding agents. The cost of drift grows with task duration: a plausible-looking
but weak completion report can waste review time, expand attack surface, and make
later agent turns compound the wrong architecture. Proofkeeper turns agent trust
from a narrative into an inspectable local artifact.

## How Codex Was Used

The Build Week extension was built inside Codex as an iterative evidence loop:

1. Codex inspected the existing Goalkeeper and ScopeProof repositories and preserved
   pre-existing uncommitted verification work.
2. Codex implemented the proof adapter, gate policy, evidence schema, CLI surface,
   regression tests, and runnable demo.
3. Codex ran the real integration and accepted the first REPLAN result instead of
   weakening the gate.
4. The real demo exposed a ScopeProof false positive: similarly named test functions
   were treated as duplicate production abstractions. Codex fixed the upstream check,
   added a regression test, and reran the proof to a genuine COMPLETE result.

This is the product thesis demonstrated in its own development process: failure
evidence changed the implementation before the system was allowed to claim success.

Before submission, run `/feedback` in the primary Codex task and paste the returned
session ID into the Devpost form. Confirm that the recorded session used GPT-5.6.

## What Was Added During Build Week

The project existed before the submission period. Only the extension below is the
Build Week entry:

- `goalkeeper prove` closed evidence gate,
- real ScopeProof subprocess adapter with fail-closed unavailable/error handling,
- automatic evidence-supported closure for behavior (`AC2`) and scope (`AC3`),
- explicit closure requirement for the objective criterion (`AC1`),
- JSON and Markdown proof bundles with a versioned schema,
- distinct CONTINUE / REPLAN / PAUSE / COMPLETE decisions and script exit codes,
- strict generated ScopeProof inputs plus project-config overrides,
- a two-scenario, no-rebuild demo,
- regression coverage for proof decisions and ScopeProof test-symbol false positives.

Pre-existing Goalkeeper contract, checkpoint, watch, app-server, and command-only
verification features are supporting infrastructure and are not presented as new
Build Week work.

## Install and Test

Supported platforms: Windows, macOS, and Linux with Python 3.11+, Git, and a shell.

```bash
git clone https://github.com/SomeTimeDev/codex-goalkeeper.git
cd codex-goalkeeper
python -m pip install -e ".[dev,proof]"
python examples/run_proofkeeper_demo.py
```

Expected result:

```text
SCENARIO 1: focused change
Proofkeeper gate: COMPLETE

SCENARIO 2: scope drift after passing tests
Proofkeeper gate: REPLAN

Demo passed: focused work completed; scope drift was blocked.
```

## Demo Video Script (Under Three Minutes)

**0:00–0:20 — Problem**

“Tests passing is not the same as an agent staying on task. Long-running coding
agents can add unrelated architecture and still produce a green test report.”

**0:20–0:40 — Product**

Show the flow diagram in the README. “Proofkeeper combines a Goalkeeper contract,
measured verification, and deterministic ScopeProof diff checks. The next turn is
gated by evidence.”

**0:40–1:30 — Focused change**

Run `python examples/run_proofkeeper_demo.py`. Show two tests passing, all seven
scope checks passing, and the COMPLETE gate. Open the generated Markdown evidence
bundle briefly.

**1:30–2:10 — Drift despite green tests**

Continue the same demo. The tests still pass, but the new service module violates
the path boundary, looks like module sprawl, and is orphaned. Show REPLAN.

**2:10–2:40 — Codex and GPT-5.6**

Explain that Codex built the proof loop during Build Week, ran the real gate against
itself, found the ScopeProof test-symbol false positive, and repaired the upstream
engine rather than bypassing the failure.

**2:40–2:55 — Close**

“Codex can keep working. Proofkeeper makes it earn the right to continue.”

## Submission Checklist

- [ ] Public repository is current and MIT licensed.
- [ ] Build Week commits are clearly dated after July 13, 2026, 9:00 AM PT.
- [ ] README distinguishes pre-existing work from the Build Week extension.
- [ ] Installation and two-minute demo work from a fresh checkout.
- [ ] Public YouTube demo is under three minutes and includes audio.
- [ ] Video explains how Codex and GPT-5.6 were used.
- [ ] Devpost category is Developer Tools.
- [ ] `/feedback` Codex Session ID is included: `[TODO]`.
- [ ] Repository URL is included: `https://github.com/SomeTimeDev/codex-goalkeeper`.
- [ ] YouTube URL is included: `[TODO]`.
