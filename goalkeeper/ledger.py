from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .models import Checkpoint, GoalkeeperContract


class GoalkeeperStore:
    def __init__(self, cwd: str | Path | None = None) -> None:
        self.root = Path(cwd or Path.cwd()).expanduser().resolve()
        self.storage_dir = self.root / ".goalkeeper"
        self.contracts_dir = self.storage_dir / "contracts"
        self.ledgers_dir = self.storage_dir / "ledgers"
        self.reports_dir = self.storage_dir / "reports"

    def ensure(self) -> None:
        self.contracts_dir.mkdir(parents=True, exist_ok=True)
        self.ledgers_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def contract_path(self, contract_id: str) -> Path:
        return self.contracts_dir / f"{contract_id}.json"

    def ledger_path(self, contract_id: str) -> Path:
        return self.ledgers_dir / f"{contract_id}.jsonl"

    def report_path(self, contract_id: str) -> Path:
        return self.reports_dir / f"{contract_id}_summary.md"

    def save_contract(self, contract: GoalkeeperContract) -> Path:
        self.ensure()
        contract.updated_at = utc_now()
        path = self.contract_path(contract.id)
        path.write_text(json.dumps(contract.to_dict(), indent=2) + "\n", encoding="utf-8")
        return path

    def load_contract(self, contract_id: str) -> GoalkeeperContract:
        path = self.contract_path(contract_id)
        if not path.exists():
            raise FileNotFoundError(f"Goalkeeper contract not found: {path}")
        return GoalkeeperContract.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def append_checkpoint(self, checkpoint: Checkpoint) -> Path:
        self.ensure()
        path = self.ledger_path(checkpoint.contract_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(checkpoint.to_dict(), sort_keys=True) + "\n")
        return path

    def read_checkpoints(self, contract_id: str, *, limit: int | None = None) -> list[Checkpoint]:
        path = self.ledger_path(contract_id)
        if not path.exists():
            return []
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if limit is not None:
            lines = lines[-limit:]
        return [Checkpoint.from_dict(json.loads(line)) for line in lines]

    def recent_checkpoint_summary(self, contract_id: str, *, limit: int = 5) -> str:
        checkpoints = self.read_checkpoints(contract_id, limit=limit)
        if not checkpoints:
            return "No checkpoints recorded."
        rows = []
        for checkpoint in checkpoints:
            claimed = checkpoint.claimed_progress or "(no claimed progress)"
            rows.append(
                f"- {checkpoint.timestamp} {checkpoint.id}: {checkpoint.decision.value}, "
                f"score {checkpoint.progress_score}, {claimed}"
            )
        return "\n".join(rows)


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_checkpoint_id() -> str:
    return f"cp_{uuid4().hex[:10]}"
