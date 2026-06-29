from __future__ import annotations

from .codex_adapter import ThreadSnapshot
from .ledger import new_checkpoint_id, utc_now
from .models import Checkpoint, GoalkeeperContract


WAITING_WORDS = ("waiting", "wait for", "pending", "blocked on", "needs approval")
EVIDENCE_WORDS = ("passed", "verified", "evidence", "test", "diff", "changed", "implemented")


def checkpoint_from_thread_snapshot(
    contract: GoalkeeperContract,
    snapshot: ThreadSnapshot,
    *,
    turn_id: str | None = None,
) -> Checkpoint:
    text = _latest_text(snapshot)
    evidence = []
    if any(word in text.lower() for word in EVIDENCE_WORDS):
        evidence.append("Best-effort thread snapshot mentions verification or implementation evidence.")
    waiting_on = None
    if any(word in text.lower() for word in WAITING_WORDS):
        waiting_on = "Thread snapshot appears to be waiting on external state or input."
    return Checkpoint(
        id=new_checkpoint_id(),
        contract_id=contract.id,
        timestamp=utc_now(),
        turn_id=turn_id or snapshot.latest_event_id,
        claimed_progress=text[:500],
        new_evidence=evidence,
        next_action="Review automatic checkpoint and continue only with evidence-producing work.",
        waiting_on=waiting_on,
    )


def _latest_text(snapshot: ThreadSnapshot) -> str:
    if snapshot.messages:
        latest = snapshot.messages[-1]
        if isinstance(latest, str):
            return latest
        if isinstance(latest, dict):
            for key in ("content", "text", "message"):
                value = latest.get(key)
                if isinstance(value, str):
                    return value
    return snapshot.summary or "Thread snapshot read without parseable message text."
