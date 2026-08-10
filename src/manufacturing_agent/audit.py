from __future__ import annotations

import json
from pathlib import Path

from .models import AuditEvent, WorkflowRun


class AuditStore:
    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def save(self, run: WorkflowRun) -> None:
        path = self.runtime_dir / f"{run.run_id}.json"
        path.write_text(run.model_dump_json(indent=2), encoding="utf-8")

    def load(self, run_id: str) -> WorkflowRun:
        path = self.runtime_dir / f"{run_id}.json"
        if not path.exists():
            raise KeyError(f"Unknown run: {run_id}")
        return WorkflowRun.model_validate_json(path.read_text(encoding="utf-8"))

    @staticmethod
    def append_event(run: WorkflowRun, event_type: str, actor: str, **details) -> None:
        run.audit_events.append(
            AuditEvent(
                sequence=len(run.audit_events) + 1,
                event_type=event_type,
                actor=actor,
                details=json.loads(json.dumps(details, ensure_ascii=False, default=str)),
            )
        )

