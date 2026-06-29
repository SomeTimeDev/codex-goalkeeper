# CI Wait Example

User objective:

```text
finish release branch after CI passes
```

Goalkeeper should avoid active waiting. If the only useful next action is waiting for CI, record a checkpoint:

```bash
goalkeeper checkpoint --contract-id gk_example_ci \
  --claimed-progress "Release branch pushed; no further local action until CI reports" \
  --waiting-on "CI result for release branch" \
  --next-action "Resume when CI has a pass/fail result"
```

After repeated waiting checkpoints, Goalkeeper should recommend:

```text
defer_recommended
```

Manual resume:

```bash
goalkeeper resume --contract-id gk_example_ci
goalkeeper checkpoint --contract-id gk_example_ci \
  --claimed-progress "CI failed with test_imports error" \
  --evidence "CI failure summary captured" \
  --next-action "Reproduce test_imports locally"
```
