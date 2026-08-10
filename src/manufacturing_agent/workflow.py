from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4

from .audit import AuditStore
from .consistency import find_consistency_issues
from .drafting import ApplicationDraftBuilder
from .eligibility import (
    check_materials,
    eligibility_status,
    evaluate_rule,
    policy_window,
)
from .models import (
    ApprovalRequest,
    EligibilityStatus,
    Policy,
    PolicyAssessment,
    RuleStatus,
    WorkflowRun,
)
from .repository import Repository
from .retrieval import CitationRetriever


STATUS_ZH = {
    EligibilityStatus.ELIGIBLE: "条件匹配",
    EligibilityStatus.NOT_ELIGIBLE: "当前条件不匹配",
    EligibilityStatus.NEEDS_INFORMATION: "需要补充信息",
}


class ManufacturingApplicationAgent:
    def __init__(self, repository: Repository | None = None) -> None:
        self.repository = repository or Repository()
        self.store = AuditStore(self.repository.root / "data" / "runtime")

    def list_policies(self) -> list[Policy]:
        return self.repository.list_policies()

    def retrieve(self, query: str, top_k: int = 5):
        return CitationRetriever(
            self.list_policies(), extra_chunks=self.repository.source_chunks()
        ).search(query, top_k=top_k)

    def assess(
        self,
        company_id: str,
        policy_ids: list[str] | None = None,
        as_of: date | None = None,
        actor: str = "analyst",
    ) -> WorkflowRun:
        effective_date = as_of or date.today()
        company = self.repository.get_company(company_id)
        if not company.fictional:
            raise ValueError("公开演示模式仅允许使用 fictional=true 的企业档案")
        policies = self.list_policies()
        if policy_ids:
            selected = set(policy_ids)
            policies = [p for p in policies if p.id in selected]
            unknown = selected - {p.id for p in policies}
            if unknown:
                raise KeyError(f"Unknown policies: {sorted(unknown)}")

        run = WorkflowRun(
            run_id=uuid4().hex[:12],
            as_of=effective_date,
            company_id=company.id,
            company_name=company.name,
            assessments=[],
            draft_markdown="",
            application_drafts={},
        )
        self.store.append_event(run, "run_started", actor, company_id=company.id, as_of=effective_date)

        consistency_findings = find_consistency_issues(company)
        self.store.append_event(
            run,
            "consistency_checked",
            "consistency_tool",
            finding_count=len(consistency_findings),
        )

        for policy in policies:
            window_status, window_reason = policy_window(policy, effective_date)
            rule_results = [evaluate_rule(rule, company) for rule in policy.rules]
            status = eligibility_status(rule_results)
            material_results = check_materials(policy, company)
            missing = [result.label for result in rule_results if result.status == RuleStatus.UNKNOWN]
            conclusion = self._conclusion(policy, status, window_reason, rule_results, material_results)
            assessment = PolicyAssessment(
                policy_id=policy.id,
                policy_title=policy.title,
                window_status=window_status,
                window_reason=window_reason,
                eligibility_status=status,
                rule_results=rule_results,
                material_results=material_results,
                consistency_findings=consistency_findings,
                missing_information=missing,
                conclusion=conclusion,
                amount_note=policy.amount_note,
            )
            run.assessments.append(assessment)
            run.application_drafts[policy.id] = ApplicationDraftBuilder().build(policy, company)
            self.store.append_event(
                run,
                "policy_assessed",
                "eligibility_tool",
                policy_id=policy.id,
                window_status=window_status,
                eligibility_status=status,
                failed_rules=sum(r.status == RuleStatus.FAIL for r in rule_results),
                unknown_rules=sum(r.status == RuleStatus.UNKNOWN for r in rule_results),
            )

        run.draft_markdown = self._build_draft(run)
        self.store.append_event(
            run,
            "draft_generated",
            "draft_tool",
            characters=len(run.draft_markdown),
            application_draft_count=len(run.application_drafts),
        )
        self.store.append_event(
            run,
            "approval_required",
            "permission_gate",
            operation="export_or_submit",
            reason="任何导出正式材料或对外提交均需人工审批",
        )
        self.store.save(run)
        return run

    @staticmethod
    def _conclusion(policy, status, window_reason, rules, materials) -> str:
        failed = [r.label for r in rules if r.status == RuleStatus.FAIL and r.blocking]
        unknown = [r.label for r in rules if r.status == RuleStatus.UNKNOWN and r.blocking]
        missing_materials = [m.label for m in materials if m.status == RuleStatus.FAIL]
        parts = [f"{STATUS_ZH[status]}；{window_reason}。"]
        if failed:
            parts.append("未满足的硬性条件：" + "、".join(failed) + "。")
        if unknown:
            parts.append("待补充核验：" + "、".join(unknown) + "。")
        if missing_materials:
            parts.append("缺少材料：" + "、".join(missing_materials) + "。")
        parts.append(policy.amount_note)
        return "".join(parts)

    def approve(self, run_id: str, request: ApprovalRequest, role: str) -> WorkflowRun:
        if role not in {"approver", "admin"}:
            raise PermissionError("Only approver or admin may decide an approval gate")
        run = self.store.load(run_id)
        run.approval_status = request.decision
        run.approved_by = request.reviewer if request.decision == "approved" else None
        self.store.append_event(
            run,
            "approval_decided",
            request.reviewer,
            decision=request.decision,
            comment=request.comment,
            role=role,
        )
        self.store.save(run)
        return run

    def export(self, run_id: str, role: str) -> Path:
        if role not in {"approver", "admin"}:
            raise PermissionError("Only approver or admin may export")
        run = self.store.load(run_id)
        if run.approval_status != "approved":
            raise PermissionError("Export blocked: approval is required")
        export_dir = self.repository.root / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / f"{run.run_id}_assessment.md"
        sections = [run.draft_markdown]
        for policy_id, draft in run.application_drafts.items():
            sections.extend(["", "---", "", f"<!-- policy_id: {policy_id} -->", "", draft])
        path.write_text("\n".join(sections), encoding="utf-8")
        self.store.append_event(run, "report_exported", role, path=str(path))
        self.store.save(run)
        return path

    @staticmethod
    def _build_draft(run: WorkflowRun) -> str:
        lines = [
            f"# {run.company_name}项目申报预评估",
            "",
            "> 本报告由公开政策与虚构企业数据生成，仅用于软件演示，不构成申报、法律或财务意见。",
            "",
            f"- 评估日期：{run.as_of.isoformat()}",
            f"- 执行编号：{run.run_id}",
            "- 对外导出状态：等待人工审批",
            "",
        ]
        for assessment in run.assessments:
            lines.extend(
                [
                    f"## {assessment.policy_title}",
                    "",
                    f"结论：{assessment.conclusion}",
                    "",
                    "### 条件核验",
                    "",
                    "| 条件 | 结果 | 企业值 | 依据 |",
                    "|---|---|---:|---|",
                ]
            )
            for result in assessment.rule_results:
                evidence = "；".join(
                    f"[{c.locator}]({c.url})" for c in result.citations[:2]
                ) or "无"
                lines.append(
                    f"| {result.label} | {result.status.value} | {result.actual} | {evidence} |"
                )
            lines.extend(["", "### 材料检查", ""])
            for material in assessment.material_results:
                lines.append(f"- [{material.status.value}] {material.label}：{material.reason}")
            if assessment.consistency_findings:
                lines.extend(["", "### 一致性风险", ""])
                for finding in assessment.consistency_findings:
                    lines.append(f"- {finding.severity.upper()}：{finding.message}")
            lines.append("")
        lines.extend(
            [
                "## 人工审批",
                "",
                "本报告当前仅为内部草稿。导出正式材料或任何模拟/真实提交动作前，必须由 approver 或 admin 角色明确批准。",
                "",
            ]
        )
        return "\n".join(lines)
