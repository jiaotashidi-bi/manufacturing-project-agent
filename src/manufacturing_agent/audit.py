from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

from .models import AuditEvent, WorkflowRun

if TYPE_CHECKING:
    from .database import DatabaseStore


class AuditStore:
    def __init__(self, runtime_dir: Path, database: DatabaseStore | None = None) -> None:
        self.runtime_dir = runtime_dir
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.database = database

    def save(self, run: WorkflowRun) -> None:
        path = self.runtime_dir / f"{run.run_id}.json"
        path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        if self.database is not None:
            self.database.save_run(run)

    def load(self, run_id: str) -> WorkflowRun:
        path = self.runtime_dir / f"{run_id}.json"
        if path.exists():
            return WorkflowRun.model_validate_json(path.read_text(encoding="utf-8"))
        if self.database is not None:
            return self.database.load_run(run_id)
        raise KeyError(f"Unknown run: {run_id}")

    @staticmethod
    def append_event(run: WorkflowRun, event_type: str, actor: str, **details) -> None:
        normalized = json.loads(json.dumps(details, ensure_ascii=False, default=str))
        previous_hash = run.audit_events[-1].event_hash if run.audit_events else "GENESIS"
        event = AuditEvent(
            sequence=len(run.audit_events) + 1,
            event_type=event_type,
            actor=actor,
            details=normalized,
            previous_hash=previous_hash,
        )
        event.event_hash = AuditStore._event_hash(event)
        run.audit_events.append(event)

    @staticmethod
    def _event_hash(event: AuditEvent) -> str:
        payload = {
            "sequence": event.sequence,
            "timestamp": event.timestamp.isoformat(),
            "event_type": event.event_type,
            "actor": event.actor,
            "details": event.details,
            "previous_hash": event.previous_hash,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def verify(run: WorkflowRun) -> bool:
        previous_hash = "GENESIS"
        for expected_sequence, event in enumerate(run.audit_events, start=1):
            if event.sequence != expected_sequence or event.previous_hash != previous_hash:
                return False
            if event.event_hash != AuditStore._event_hash(event):
                return False
            previous_hash = event.event_hash
        return True
