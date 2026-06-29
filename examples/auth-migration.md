# Auth Migration Example

User objective:

```text
migrate auth provider but keep login compatible
```

Likely Goalkeeper questions:

```text
Q_FALLBACK: Should the legacy provider remain as a fallback until parity is verified, or be removed entirely?
Recommended default: Keep fallback until parity is verified.
```

Inferred contract highlights:

- Scope includes the auth provider migration, compatibility checks, focused tests, and minimal docs only if user-visible behavior changes.
- Non-goals include unrelated refactors and compatibility breaks.
- Acceptance criteria include implementation, login compatibility, verification evidence, and limited diff scope.

Final supervised goal:

```text
/goal <goalkeeper_contract id="gk_example_auth">
User objective:
migrate auth provider but keep login compatible

Normalized objective:
Migrate auth provider but keep login compatible

Acceptance criteria:
1. Migration is implemented within scope.
2. Login compatibility is preserved.
3. Relevant behavior is verified with current evidence.
4. Diff scope is limited to the objective.

Loop policy:
- Do not repeat the same failing command more than 2 times without a new hypothesis and changed precondition.
- Do not spend more than 3 consecutive goal turns without new evidence.

Wait/defer policy:
- If blocked on provider credentials, review, CI, or approval, pause/defer and record the wake condition.
</goalkeeper_contract>
```
