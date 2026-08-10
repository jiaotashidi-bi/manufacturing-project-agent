from __future__ import annotations

from datetime import date
from time import monotonic, sleep

from docx import Document
from docx.oxml.ns import qn

from manufacturing_agent.audit import AuditStore
from manufacturing_agent.auth import CurrentUser
from manufacturing_agent.config import AppSettings
from manufacturing_agent.database import DatabaseStore
from manufacturing_agent.exporters import export_docx
from manufacturing_agent.jobs import JobQueue
from manufacturing_agent.models import ApprovalRequest, CompanyProfile
from manufacturing_agent.policy_intake import PolicyIntakeService
from manufacturing_agent.retrieval import HybridCitationRetriever
from manufacturing_agent.upload_security import detect_sensitive_text, inspect_upload
from manufacturing_agent.workflow import ManufacturingApplicationAgent


def test_database_creates_missing_sqlite_parent(tmp_path):
    database_path = tmp_path / "fresh" / "nested" / "agent.db"
    database = DatabaseStore(f"sqlite:///{database_path.as_posix()}")

    assert database_path.is_file()
    database.engine.dispose()


def test_audit_hash_chain_detects_tampering(tmp_path):
    settings = AppSettings(database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    agent = ManufacturingApplicationAgent(settings=settings, database=DatabaseStore(settings.database_url))
    run = agent.assess("huaxin_precision", policy_ids=["smart_factory_excellent_2026"])
    assert AuditStore.verify(run)
    run.audit_events[1].details["finding_count"] = 999
    assert not AuditStore.verify(run)


def test_database_company_override_is_used(tmp_path):
    settings = AppSettings(database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    agent = ManufacturingApplicationAgent(settings=settings, database=DatabaseStore(settings.database_url))
    original = agent.get_company("huaxin_precision")
    updated = CompanyProfile.model_validate(original.model_dump())
    updated.name = "虚构企业数据库版本"
    agent.database.save_company(updated, "test")
    assert agent.get_company(updated.id).name == "虚构企业数据库版本"


def test_docx_and_pdf_exports_require_approval(tmp_path):
    settings = AppSettings(database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    agent = ManufacturingApplicationAgent(settings=settings, database=DatabaseStore(settings.database_url))
    run = agent.assess(
        "huaxin_precision", policy_ids=["smart_factory_excellent_2026"], as_of=date(2026, 8, 10)
    )
    agent.approve(
        run.run_id,
        ApprovalRequest(reviewer="reviewer", decision="approved"),
        role="approver",
    )
    docx = agent.export_document(run.run_id, "approver", "docx")
    pdf = agent.export_document(run.run_id, "approver", "pdf")
    try:
        assert docx.read_bytes().startswith(b"PK")
        assert pdf.read_bytes().startswith(b"%PDF")
    finally:
        docx.unlink(missing_ok=True)
        pdf.unlink(missing_ok=True)


def test_docx_export_uses_fixed_geometry_and_non_splitting_rows(tmp_path):
    settings = AppSettings(database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    agent = ManufacturingApplicationAgent(settings=settings, database=DatabaseStore(settings.database_url))
    run = agent.assess("huaxin_precision", policy_ids=["smart_factory_excellent_2026"])
    path = export_docx(run, tmp_path / "report.docx")
    document = Document(path)
    section = document.sections[0]
    assert section.page_width.inches == 8.5
    assert section.left_margin.inches == 1
    for table in document.tables:
        assert table._tbl.tblPr.find(qn("w:tblW")).get(qn("w:w")) == "9360"
        assert table._tbl.tblPr.find(qn("w:tblInd")).get(qn("w:w")) == "120"
        assert all(row._tr.get_or_add_trPr().find(qn("w:cantSplit")) is not None for row in table.rows)


def test_policy_intake_creates_reviewable_version(tmp_path):
    source = tmp_path / "policy.docx"
    document = Document()
    document.add_paragraph("某公开政策申报截止日期为2026年8月31日。")
    document.add_paragraph("研发投入不低于1200万元，并提交审计报告和承诺书。")
    document.save(source)
    settings = AppSettings(database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    database = DatabaseStore(settings.database_url)
    service = PolicyIntakeService(settings, database)
    draft, version = service.ingest(
        source.name,
        source.read_bytes(),
        "https://example.gov.cn/policy",
        actor="analyst",
        confirmed_public=True,
        title="某公开制造业政策",
        issuer="某主管部门",
    )
    assert version == 1
    assert draft.provider == "offline-regex"
    assert draft.source_sha256
    assert database.list_policy_records()[0]["status"] == "draft"
    database.review_policy(draft.policy.id, version, "reviewer", "approved")
    assert database.list_approved_policies()[0].id == draft.policy.id


def test_upload_security_blocks_spoof_and_flags_sensitive_text():
    assert not inspect_upload("policy.pdf", b"not a pdf", 15).safe
    assert inspect_upload("policy.pdf", b"%PDF" + b"x" * 100, 15).safe
    assert "手机号" in detect_sensitive_text("联系人电话：13800138000")


def test_hybrid_retriever_empty_query_returns_empty():
    assert HybridCitationRetriever([]).search("", 5) == []


def test_current_user_role_check():
    user = CurrentUser("u1", frozenset({"approver"}), "demo")
    assert user.has_any_role({"approver", "admin"})
    assert not user.has_any_role({"analyst"})


def test_background_job_persists_result(tmp_path):
    settings = AppSettings(database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    database = DatabaseStore(settings.database_url)
    queue = JobQueue(database, workers=1)
    job_id = queue.submit("test", {"input": 1}, lambda: {"ok": True})
    deadline = monotonic() + 3
    record = database.get_job(job_id)
    while record["status"] not in {"completed", "failed"} and monotonic() < deadline:
        sleep(0.02)
        record = database.get_job(job_id)
    queue.executor.shutdown(wait=True)
    assert record["status"] == "completed"
    assert record["result"] == {"ok": True}
