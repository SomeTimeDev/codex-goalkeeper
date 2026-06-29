# Billing Refactor Example

User objective:

```text
refactor billing module without breaking public API
```

Inferred contract highlights:

- Public API compatibility is an explicit acceptance criterion.
- Tests are part of the verification plan when a test command is inferred.
- Non-goals reject broad formatting, dependency swaps, and unrelated billing redesign.

Example criteria:

```text
AC1: The billing refactor is implemented within the declared scope.
AC_COMPAT: Public API and compatibility expectations are preserved.
AC2: Relevant behavior is verified with current evidence.
AC3: No unrelated scope expansion or avoidable churn is introduced.
```

Useful checkpoint:

```bash
goalkeeper checkpoint --contract-id gk_example_billing \
  --claimed-progress "Extracted invoice calculation helper without changing public exports" \
  --evidence "pytest tests/billing passed" \
  --criteria-closed AC1 \
  --command "pytest tests/billing" \
  --outcome passed \
  --changed-file "billing/calculation.py" \
  --next-action "Inspect public API diff and close AC_COMPAT if unchanged"
```
