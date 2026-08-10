from datetime import date

import pytest

from manufacturing_agent.models import ApprovalRequest, EligibilityStatus, WindowStatus
from manufacturing_agent.workflow import ManufacturingApplicationAgent


@pytest.fixture()
def agent():
    return ManufacturingApplicationAgent()


def by_policy(run, policy_id):
    return next(item for item in run.assessments if item.policy_id == policy_id)


def test_strong_company_matches_open_smart_factory_policy(agent):
    run = agent.assess("huaxin_precision", as_of=date(2026, 8, 10))
    assessment = by_policy(run, "smart_factory_excellent_2026")

    assert assessment.window_status == WindowStatus.OPEN
    assert assessment.eligibility_status == EligibilityStatus.ELIGIBLE
    assert all(item.status.value == "pass" for item in assessment.material_results)
    assert assessment.consistency_findings == []
    draft = run.application_drafts["smart_factory_excellent_2026"]
    assert "高精度机器人减速器用交叉滚子轴承" in draft
    assert "[待补充/核验]" in draft


def test_closed_window_does_not_change_underlying_eligibility(agent):
    run = agent.assess("huaxin_precision", as_of=date(2026, 8, 10))
    assessment = by_policy(run, "little_giant_batch_8_2026")

    assert assessment.window_status == WindowStatus.CLOSED
    assert assessment.eligibility_status == EligibilityStatus.ELIGIBLE
    assert "未承诺统一财政补助金额" in assessment.amount_note


def test_weak_company_fails_hard_conditions_and_detects_conflict(agent):
    run = agent.assess("yuanqi_components", as_of=date(2026, 8, 10))
    smart_factory = by_policy(run, "smart_factory_excellent_2026")
    little_giant = by_policy(run, "little_giant_batch_8_2026")

    assert smart_factory.eligibility_status == EligibilityStatus.NOT_ELIGIBLE
    assert little_giant.eligibility_status == EligibilityStatus.NOT_ELIGIBLE
    assert any(
        finding.id == "cross_document:2025_revenue_wan"
        for finding in little_giant.consistency_findings
    )


def test_incomplete_company_returns_unknown_instead_of_guessing(agent):
    run = agent.assess("lingyun_incomplete", as_of=date(2026, 8, 10))
    assessment = by_policy(run, "smart_factory_excellent_2026")

    assert assessment.eligibility_status == EligibilityStatus.NEEDS_INFORMATION
    assert "智能制造达到国内领先水平" in assessment.missing_information
    assert "人工智能技术场景比例不低于30%" in assessment.missing_information


def test_export_requires_approval_and_role(agent):
    run = agent.assess(
        "huaxin_precision",
        policy_ids=["smart_factory_excellent_2026"],
        as_of=date(2026, 8, 10),
    )
    with pytest.raises(PermissionError):
        agent.export(run.run_id, role="analyst")
    with pytest.raises(PermissionError):
        agent.approve(
            run.run_id,
            ApprovalRequest(reviewer="reviewer-1", decision="approved"),
            role="analyst",
        )

    approved = agent.approve(
        run.run_id,
        ApprovalRequest(reviewer="reviewer-1", decision="approved", comment="演示批准"),
        role="approver",
    )
    assert approved.approval_status == "approved"
    path = agent.export(run.run_id, role="approver")
    try:
        assert path.exists()
        assert "人工审批" in path.read_text(encoding="utf-8")
    finally:
        path.unlink(missing_ok=True)


def test_retrieval_returns_cited_policy_evidence(agent):
    results = agent.retrieve("卓越级智能工厂人工智能场景比例要求", top_k=3)

    assert results
    assert any("30%" in item.text for item in results)
    assert all(item.citation.url.startswith("https://") for item in results)


def test_raw_public_documents_can_be_indexed(agent, tmp_path):
    from manufacturing_agent.ingestion import SourceIngestor

    output, count = SourceIngestor(agent.repository.root).build_index(
        tmp_path / "source_chunks.jsonl"
    )
    assert output.exists()
    assert count > 50
