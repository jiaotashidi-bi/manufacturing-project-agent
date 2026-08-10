from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .audit import AuditStore
from .auth import CurrentUser, UserDependency, require_roles
from .config import get_settings
from .jobs import JobQueue
from .models import (
    ApprovalRequest,
    AssessRequest,
    CompanyUpsertRequest,
    PolicyReviewRequest,
)
from .observability import configure_observability
from .policy_intake import PolicyIntakeService
from .workflow import ManufacturingApplicationAgent

settings = get_settings()
agent = ManufacturingApplicationAgent(settings=settings)
intake = PolicyIntakeService(settings, agent.database)
jobs = JobQueue(agent.database)

app = FastAPI(
    title="制造业项目申报 Agent",
    version="0.2.0",
    description="基于公开政策和虚构企业数据的可追溯申报预评估与材料审核 API。",
)
configure_observability(app, settings.log_level)


def _role_for_export(user: CurrentUser) -> str:
    return "admin" if "admin" in user.roles else "approver"


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "0.2.0",
        "mode": "public-demo-only" if settings.public_demo_only else "configured",
        "auth_mode": settings.auth_mode,
        "llm_provider": settings.llm_provider,
        "database": "postgresql" if settings.database_url.startswith("postgres") else "sqlite",
    }


@app.get("/auth/me")
def current_user(user: UserDependency):
    return {"subject": user.subject, "roles": sorted(user.roles), "auth_mode": user.auth_mode}


@app.get("/policies")
def policies():
    return agent.list_policies()


@app.get("/policy-drafts")
def policy_drafts(
    _user: Annotated[CurrentUser, Depends(require_roles("analyst", "approver", "admin"))],
):
    return agent.database.list_policy_records()


@app.post("/policy-drafts/upload")
async def upload_policy(
    user: Annotated[CurrentUser, Depends(require_roles("analyst", "approver", "admin"))],
    file: Annotated[UploadFile, File()],
    source_url: Annotated[str, Form()],
    confirmed_public: Annotated[bool, Form()],
    title: Annotated[str | None, Form()] = None,
    issuer: Annotated[str | None, Form()] = None,
):
    content = await file.read()
    try:
        draft, version = intake.ingest(
            file.filename or "upload",
            content,
            source_url,
            actor=user.subject,
            confirmed_public=confirmed_public,
            title=title,
            issuer=issuer,
        )
        return {"version": version, "draft": draft}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/policy-drafts/{policy_id}/versions/{version}/review")
def review_policy(
    policy_id: str,
    version: int,
    request: PolicyReviewRequest,
    user: Annotated[CurrentUser, Depends(require_roles("approver", "admin"))],
):
    try:
        policy = agent.database.review_policy(policy_id, version, user.subject, request.decision)
        return {"status": request.decision, "policy": policy, "reviewer": user.subject}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/companies")
def companies():
    return agent.list_companies()


@app.put("/companies/{company_id}")
def upsert_company(
    company_id: str,
    request: CompanyUpsertRequest,
    user: Annotated[CurrentUser, Depends(require_roles("analyst", "admin"))],
):
    if request.company.id != company_id:
        raise HTTPException(status_code=400, detail="Path and payload company IDs differ")
    if settings.public_demo_only and not request.company.fictional:
        raise HTTPException(status_code=403, detail="公开演示模式仅允许 fictional=true 的企业档案")
    agent.database.save_company(request.company, user.subject)
    return request.company


@app.post("/assess")
def assess(request: AssessRequest, user: UserDependency):
    if not user.has_any_role({"analyst", "approver", "admin"}):
        raise HTTPException(status_code=403, detail="Assessment requires analyst role")
    try:
        return agent.assess(
            company_id=request.company_id,
            policy_ids=request.policy_ids,
            as_of=request.as_of,
            actor=user.subject,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/jobs/assess", status_code=202)
def assess_in_background(
    request: AssessRequest,
    user: Annotated[CurrentUser, Depends(require_roles("analyst", "approver", "admin"))],
):
    job_id = jobs.submit(
        "assessment",
        request.model_dump(mode="json"),
        lambda: agent.assess(
            company_id=request.company_id,
            policy_ids=request.policy_ids,
            as_of=request.as_of,
            actor=user.subject,
        ).model_dump(mode="json"),
    )
    return {"job_id": job_id, "status": "queued"}


@app.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    _user: Annotated[CurrentUser, Depends(require_roles("analyst", "approver", "admin"))],
):
    try:
        return agent.database.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/runs")
def list_runs(
    user: Annotated[CurrentUser, Depends(require_roles("analyst", "approver", "admin"))],
    limit: int = 50,
):
    del user
    return agent.database.list_runs(limit=min(max(limit, 1), 200))


@app.get("/runs/{run_id}")
def get_run(run_id: str, _user: UserDependency):
    try:
        return agent.store.load(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/runs/{run_id}/audit/verify")
def verify_audit(
    run_id: str,
    _user: Annotated[CurrentUser, Depends(require_roles("approver", "admin"))],
):
    try:
        run = agent.store.load(run_id)
        return {"run_id": run_id, "valid": AuditStore.verify(run), "events": len(run.audit_events)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/runs/{run_id}/approval")
def approve(
    run_id: str,
    request: ApprovalRequest,
    user: Annotated[CurrentUser, Depends(require_roles("approver", "admin"))],
):
    try:
        normalized = request.model_copy(update={"reviewer": user.subject})
        return agent.approve(run_id, normalized, role=_role_for_export(user))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/runs/{run_id}/export")
def export_legacy(
    run_id: str,
    user: Annotated[CurrentUser, Depends(require_roles("approver", "admin"))],
):
    try:
        path = agent.export(run_id, role=_role_for_export(user))
        return {"status": "exported", "path": str(path), "format": "md"}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/runs/{run_id}/exports/{format_name}")
def export_document(
    run_id: str,
    format_name: str,
    user: Annotated[CurrentUser, Depends(require_roles("approver", "admin"))],
):
    try:
        path = agent.export_document(run_id, _role_for_export(user), format_name)
        media_types = {
            "md": "text/markdown",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "pdf": "application/pdf",
        }
        return FileResponse(path, media_type=media_types[format_name.lower()], filename=path.name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/search")
def search(q: str, _user: UserDependency, top_k: int = 5):
    return agent.retrieve(q, top_k=min(max(top_k, 1), 20))
