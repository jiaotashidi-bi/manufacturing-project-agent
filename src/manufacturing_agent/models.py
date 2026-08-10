from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class RuleStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class EligibilityStatus(StrEnum):
    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    NEEDS_INFORMATION = "needs_information"


class WindowStatus(StrEnum):
    OPEN = "open"
    UPCOMING = "upcoming"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class Citation(BaseModel):
    source_id: str
    title: str
    url: str
    locator: str
    quote: str
    official: bool = True
    accessed_at: date = Field(default_factory=date.today)


class Rule(BaseModel):
    id: str
    label: str
    fact: str
    operator: Literal[
        "eq",
        "neq",
        "gte",
        "lte",
        "gt",
        "lt",
        "in",
        "not_in",
        "contains",
        "all_true",
        "any_true",
    ]
    expected: Any
    blocking: bool = True
    unit: str | None = None
    explanation: str | None = None
    citations: list[Citation] = Field(default_factory=list)


class MaterialRequirement(BaseModel):
    id: str
    label: str
    description: str
    required: bool = True
    citations: list[Citation] = Field(default_factory=list)


class Policy(BaseModel):
    id: str
    title: str
    issuer: str
    document_number: str | None = None
    jurisdiction: str = "中国大陆"
    published_at: date
    application_start: date | None = None
    application_deadline: date | None = None
    amount_cny: float | None = None
    amount_note: str
    application_url: str | None = None
    program_level: str
    summary: str
    sources: list[Citation]
    rules: list[Rule]
    materials: list[MaterialRequirement]
    tags: list[str] = Field(default_factory=list)


class CompanyProfile(BaseModel):
    id: str
    name: str
    fictional: bool
    profile_version: str
    facts: dict[str, Any]
    available_materials: list[str] = Field(default_factory=list)
    document_claims: dict[str, dict[str, Any]] = Field(default_factory=dict)


class RuleResult(BaseModel):
    rule_id: str
    label: str
    status: RuleStatus
    actual: Any = None
    expected: Any = None
    reason: str
    blocking: bool
    citations: list[Citation] = Field(default_factory=list)


class MaterialResult(BaseModel):
    material_id: str
    label: str
    status: RuleStatus
    reason: str
    citations: list[Citation] = Field(default_factory=list)


class ConsistencyFinding(BaseModel):
    id: str
    severity: Literal["error", "warning", "info"]
    message: str
    fields: list[str] = Field(default_factory=list)


class RetrievedEvidence(BaseModel):
    text: str
    score: float
    citation: Citation


class PolicyAssessment(BaseModel):
    policy_id: str
    policy_title: str
    window_status: WindowStatus
    window_reason: str
    eligibility_status: EligibilityStatus
    rule_results: list[RuleResult]
    material_results: list[MaterialResult]
    consistency_findings: list[ConsistencyFinding]
    missing_information: list[str]
    conclusion: str
    amount_note: str


class AuditEvent(BaseModel):
    sequence: int
    timestamp: datetime = Field(default_factory=datetime.now)
    event_type: str
    actor: str
    details: dict[str, Any] = Field(default_factory=dict)


class WorkflowRun(BaseModel):
    run_id: str
    created_at: datetime = Field(default_factory=datetime.now)
    as_of: date
    company_id: str
    company_name: str
    assessments: list[PolicyAssessment]
    draft_markdown: str
    application_drafts: dict[str, str] = Field(default_factory=dict)
    approval_status: Literal["not_requested", "pending", "approved", "rejected"] = "pending"
    approved_by: str | None = None
    audit_events: list[AuditEvent] = Field(default_factory=list)


class AssessRequest(BaseModel):
    company_id: str
    policy_ids: list[str] | None = None
    as_of: date = Field(default_factory=date.today)
    actor: str = "analyst"


class ApprovalRequest(BaseModel):
    reviewer: str
    decision: Literal["approved", "rejected"]
    comment: str = ""
