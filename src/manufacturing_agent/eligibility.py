from __future__ import annotations

from datetime import date
from typing import Any

from .models import (
    CompanyProfile,
    EligibilityStatus,
    MaterialResult,
    Policy,
    Rule,
    RuleResult,
    RuleStatus,
    WindowStatus,
)


MISSING = object()


def get_fact(facts: dict[str, Any], path: str) -> Any:
    current: Any = facts
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current


def policy_window(policy: Policy, as_of: date) -> tuple[WindowStatus, str]:
    if policy.application_start and as_of < policy.application_start:
        return WindowStatus.UPCOMING, f"申报尚未开始，将于 {policy.application_start.isoformat()} 开放"
    if policy.application_deadline and as_of > policy.application_deadline:
        return WindowStatus.CLOSED, f"申报已于 {policy.application_deadline.isoformat()} 截止"
    if policy.application_deadline:
        return WindowStatus.OPEN, f"申报开放，截止日期为 {policy.application_deadline.isoformat()}"
    return WindowStatus.UNKNOWN, "公开文件未明确统一申报窗口"


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    if operator == "eq":
        return actual == expected
    if operator == "neq":
        return actual != expected
    if operator == "gte":
        return actual >= expected
    if operator == "lte":
        return actual <= expected
    if operator == "gt":
        return actual > expected
    if operator == "lt":
        return actual < expected
    if operator == "in":
        return actual in expected
    if operator == "not_in":
        return actual not in expected
    if operator == "contains":
        return expected in actual
    if operator == "all_true":
        return isinstance(actual, (list, tuple)) and all(actual) and len(actual) >= int(expected)
    if operator == "any_true":
        return isinstance(actual, (list, tuple)) and any(actual)
    raise ValueError(f"Unsupported operator: {operator}")


def evaluate_rule(rule: Rule, company: CompanyProfile) -> RuleResult:
    actual = get_fact(company.facts, rule.fact)
    if actual is MISSING or actual is None:
        return RuleResult(
            rule_id=rule.id,
            label=rule.label,
            status=RuleStatus.UNKNOWN,
            actual=None,
            expected=rule.expected,
            reason=f"企业档案缺少字段：{rule.fact}",
            blocking=rule.blocking,
            citations=rule.citations,
        )
    try:
        passed = _compare(actual, rule.operator, rule.expected)
    except (TypeError, ValueError) as exc:
        return RuleResult(
            rule_id=rule.id,
            label=rule.label,
            status=RuleStatus.UNKNOWN,
            actual=actual,
            expected=rule.expected,
            reason=f"字段无法可靠比较：{exc}",
            blocking=rule.blocking,
            citations=rule.citations,
        )
    unit = f" {rule.unit}" if rule.unit else ""
    return RuleResult(
        rule_id=rule.id,
        label=rule.label,
        status=RuleStatus.PASS if passed else RuleStatus.FAIL,
        actual=actual,
        expected=rule.expected,
        reason=(
            f"企业值 {actual}{unit} 满足要求"
            if passed
            else f"企业值 {actual}{unit} 不满足要求（要求 {rule.operator} {rule.expected}{unit}）"
        ),
        blocking=rule.blocking,
        citations=rule.citations,
    )


def eligibility_status(results: list[RuleResult]) -> EligibilityStatus:
    if any(r.status == RuleStatus.FAIL and r.blocking for r in results):
        return EligibilityStatus.NOT_ELIGIBLE
    if any(r.status == RuleStatus.UNKNOWN and r.blocking for r in results):
        return EligibilityStatus.NEEDS_INFORMATION
    return EligibilityStatus.ELIGIBLE


def check_materials(policy: Policy, company: CompanyProfile) -> list[MaterialResult]:
    available = set(company.available_materials)
    results: list[MaterialResult] = []
    for material in policy.materials:
        present = material.id in available
        if present:
            status = RuleStatus.PASS
            reason = "企业材料清单中已登记"
        elif material.required:
            status = RuleStatus.FAIL
            reason = "必需材料尚未登记"
        else:
            status = RuleStatus.NOT_APPLICABLE
            reason = "选填或条件性材料未登记"
        results.append(
            MaterialResult(
                material_id=material.id,
                label=material.label,
                status=status,
                reason=reason,
                citations=material.citations,
            )
        )
    return results

