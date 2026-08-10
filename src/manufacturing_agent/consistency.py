from __future__ import annotations

from math import isclose
from typing import Any

from .eligibility import MISSING, get_fact
from .models import CompanyProfile, ConsistencyFinding


def _number(value: Any) -> float | None:
    if value is MISSING or value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio_check(
    company: CompanyProfile,
    finding_id: str,
    numerator_path: str,
    denominator_path: str,
    declared_path: str,
    label: str,
    tolerance: float = 0.2,
) -> ConsistencyFinding | None:
    numerator = _number(get_fact(company.facts, numerator_path))
    denominator = _number(get_fact(company.facts, denominator_path))
    declared = _number(get_fact(company.facts, declared_path))
    if numerator is None or denominator in (None, 0) or declared is None:
        return None
    calculated = numerator / denominator * 100
    if isclose(calculated, declared, abs_tol=tolerance):
        return None
    return ConsistencyFinding(
        id=finding_id,
        severity="error",
        message=f"{label}声明为 {declared:.2f}%，按基础数据计算应为 {calculated:.2f}%",
        fields=[numerator_path, denominator_path, declared_path],
    )


def find_consistency_issues(company: CompanyProfile) -> list[ConsistencyFinding]:
    findings: list[ConsistencyFinding] = []
    checks = [
        (
            "main_revenue_ratio",
            "financials.2025.main_business_revenue",
            "financials.2025.revenue",
            "financials.2025.main_business_ratio",
            "2025 年主营业务收入占比",
        ),
        (
            "debt_ratio",
            "financials.2025.liabilities",
            "financials.2025.assets",
            "financials.2025.debt_ratio",
            "2025 年资产负债率",
        ),
        (
            "rd_ratio_2025",
            "financials.2025.rd_expense",
            "financials.2025.revenue",
            "financials.2025.rd_ratio",
            "2025 年研发费用占比",
        ),
        (
            "rd_ratio_2024",
            "financials.2024.rd_expense",
            "financials.2024.revenue",
            "financials.2024.rd_ratio",
            "2024 年研发费用占比",
        ),
    ]
    for args in checks:
        finding = _ratio_check(company, *args)
        if finding:
            findings.append(finding)

    for field, claims in company.document_claims.items():
        normalized = {str(value).strip() for value in claims.values() if value is not None}
        if len(normalized) > 1:
            findings.append(
                ConsistencyFinding(
                    id=f"cross_document:{field}",
                    severity="error",
                    message=f"字段 {field} 在不同材料中的取值不一致：{claims}",
                    fields=[field],
                )
            )

    completed = get_fact(company.facts, "factory.completed")
    completion_date = get_fact(company.facts, "factory.completion_date")
    if completed is True and (completion_date is MISSING or not completion_date):
        findings.append(
            ConsistencyFinding(
                id="factory_completion_evidence",
                severity="warning",
                message="档案声明智能工厂已建成，但未填写建成日期",
                fields=["factory.completed", "factory.completion_date"],
            )
        )
    return findings

