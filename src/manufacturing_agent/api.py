from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException

from .models import ApprovalRequest, AssessRequest
from .workflow import ManufacturingApplicationAgent


app = FastAPI(
    title="制造业项目申报 Agent",
    version="0.1.0",
    description="基于公开政策和虚构企业数据的可追溯申报预评估 API。",
)
agent = ManufacturingApplicationAgent()


@app.get("/health")
def health():
    return {"status": "ok", "mode": "public-demo-only"}


@app.get("/policies")
def policies():
    return agent.list_policies()


@app.get("/companies")
def companies():
    return agent.repository.list_companies()


@app.post("/assess")
def assess(request: AssessRequest):
    try:
        return agent.assess(
            company_id=request.company_id,
            policy_ids=request.policy_ids,
            as_of=request.as_of,
            actor=request.actor,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    try:
        return agent.store.load(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/runs/{run_id}/approval")
def approve(run_id: str, request: ApprovalRequest, x_role: str = Header(default="analyst")):
    try:
        return agent.approve(run_id, request, role=x_role)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/runs/{run_id}/export")
def export(run_id: str, x_role: str = Header(default="analyst")):
    try:
        path = agent.export(run_id, role=x_role)
        return {"status": "exported", "path": str(path)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/search")
def search(q: str, top_k: int = 5):
    return agent.retrieve(q, top_k=top_k)

