from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .models import CompanyProfile, Policy, WorkflowRun


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


class PolicyRecord(Base):
    __tablename__ = "policy_versions"

    row_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[str] = mapped_column(String(160), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    payload: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(160))
    reviewed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CompanyRecord(Base):
    __tablename__ = "companies"

    company_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[str] = mapped_column(String(160))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WorkflowRecord(Base):
    __tablename__ = "workflow_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(160), index=True)
    approval_status: Mapped[str] = mapped_column(String(30), index=True)
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditRecord(Base):
    __tablename__ = "audit_events"

    row_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_hash: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class JobRecord(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


class DatabaseStore:
    """Small repository abstraction supporting both SQLite and PostgreSQL URLs."""

    def __init__(self, database_url: str) -> None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
        Base.metadata.create_all(self.engine)

    def save_run(self, run: WorkflowRun) -> None:
        with Session(self.engine) as session:
            record = session.get(WorkflowRecord, run.run_id)
            if record is None:
                record = WorkflowRecord(
                    run_id=run.run_id,
                    company_id=run.company_id,
                    approval_status=run.approval_status,
                    payload=run.model_dump_json(),
                )
                session.add(record)
            else:
                record.approval_status = run.approval_status
                record.payload = run.model_dump_json()
                record.updated_at = utc_now()
            session.query(AuditRecord).filter(AuditRecord.run_id == run.run_id).delete()
            for event in run.audit_events:
                session.add(
                    AuditRecord(
                        run_id=run.run_id,
                        sequence=event.sequence,
                        event_hash=event.event_hash,
                        payload=event.model_dump_json(),
                    )
                )
            session.commit()

    def load_run(self, run_id: str) -> WorkflowRun:
        with Session(self.engine) as session:
            record = session.get(WorkflowRecord, run_id)
            if record is None:
                raise KeyError(f"Unknown run: {run_id}")
            return WorkflowRun.model_validate_json(record.payload)

    def list_runs(self, limit: int = 100) -> list[WorkflowRun]:
        with Session(self.engine) as session:
            records = session.scalars(
                select(WorkflowRecord).order_by(WorkflowRecord.created_at.desc()).limit(limit)
            )
            return [WorkflowRun.model_validate_json(record.payload) for record in records]

    def save_company(self, company: CompanyProfile, actor: str) -> None:
        with Session(self.engine) as session:
            record = session.get(CompanyRecord, company.id)
            if record is None:
                session.add(
                    CompanyRecord(company_id=company.id, payload=company.model_dump_json(), updated_by=actor)
                )
            else:
                record.payload = company.model_dump_json()
                record.updated_by = actor
                record.updated_at = utc_now()
            session.commit()

    def list_companies(self) -> list[CompanyProfile]:
        with Session(self.engine) as session:
            records = session.scalars(select(CompanyRecord).order_by(CompanyRecord.company_id))
            return [CompanyProfile.model_validate_json(record.payload) for record in records]

    def save_policy_draft(
        self, policy: Policy, source_sha256: str, actor: str, status: str = "draft"
    ) -> int:
        with Session(self.engine) as session:
            latest = session.scalar(
                select(PolicyRecord)
                .where(PolicyRecord.policy_id == policy.id)
                .order_by(PolicyRecord.version.desc())
            )
            version = 1 if latest is None else latest.version + 1
            session.add(
                PolicyRecord(
                    policy_id=policy.id,
                    version=version,
                    status=status,
                    payload=policy.model_dump_json(),
                    source_sha256=source_sha256,
                    created_by=actor,
                )
            )
            session.commit()
            return version

    def review_policy(self, policy_id: str, version: int, reviewer: str, status: str) -> Policy:
        if status not in {"approved", "rejected"}:
            raise ValueError("status must be approved or rejected")
        with Session(self.engine) as session:
            record = session.scalar(
                select(PolicyRecord).where(
                    PolicyRecord.policy_id == policy_id, PolicyRecord.version == version
                )
            )
            if record is None:
                raise KeyError(f"Unknown policy draft: {policy_id} v{version}")
            record.status = status
            record.reviewed_by = reviewer
            record.reviewed_at = utc_now()
            session.commit()
            return Policy.model_validate_json(record.payload)

    def list_policy_records(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            records = session.scalars(
                select(PolicyRecord).order_by(PolicyRecord.created_at.desc())
            )
            return [
                {
                    "policy_id": r.policy_id,
                    "version": r.version,
                    "status": r.status,
                    "source_sha256": r.source_sha256,
                    "created_by": r.created_by,
                    "reviewed_by": r.reviewed_by,
                    "created_at": r.created_at.isoformat(),
                    "policy": json.loads(r.payload),
                }
                for r in records
            ]

    def list_approved_policies(self) -> list[Policy]:
        with Session(self.engine) as session:
            records = session.scalars(
                select(PolicyRecord)
                .where(PolicyRecord.status == "approved")
                .order_by(PolicyRecord.reviewed_at.desc())
            )
            latest: dict[str, Policy] = {}
            for record in records:
                latest.setdefault(record.policy_id, Policy.model_validate_json(record.payload))
            return list(latest.values())

    def create_job(self, job_id: str, job_type: str, payload: dict[str, Any]) -> None:
        with Session(self.engine) as session:
            session.add(JobRecord(job_id=job_id, job_type=job_type, status="queued", payload=_json(payload)))
            session.commit()

    def update_job(
        self, job_id: str, status: str, result: Any = None, error: str | None = None
    ) -> None:
        with Session(self.engine) as session:
            record = session.get(JobRecord, job_id)
            if record is None:
                raise KeyError(f"Unknown job: {job_id}")
            record.status = status
            record.result = _json(result) if result is not None else None
            record.error = error
            record.updated_at = utc_now()
            session.commit()

    def get_job(self, job_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            record = session.get(JobRecord, job_id)
            if record is None:
                raise KeyError(f"Unknown job: {job_id}")
            return {
                "job_id": record.job_id,
                "job_type": record.job_type,
                "status": record.status,
                "payload": json.loads(record.payload),
                "result": json.loads(record.result) if record.result else None,
                "error": record.error,
            }
