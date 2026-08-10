from fastapi.testclient import TestClient

from manufacturing_agent.api import app


client = TestClient(app)


def test_health_and_catalog():
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["mode"] == "public-demo-only"
    assert len(client.get("/policies").json()) == 2
    assert len(client.get("/companies").json()) == 3


def test_assess_and_permission_gate():
    response = client.post(
        "/assess",
        json={
            "company_id": "huaxin_precision",
            "policy_ids": ["smart_factory_excellent_2026"],
            "as_of": "2026-08-10",
        },
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    blocked = client.post(f"/runs/{run_id}/export", headers={"X-Role": "analyst"})
    assert blocked.status_code == 403

    approval = client.post(
        f"/runs/{run_id}/approval",
        headers={"X-Role": "approver"},
        json={"reviewer": "api-reviewer", "decision": "approved", "comment": "test"},
    )
    assert approval.status_code == 200
    assert approval.json()["approval_status"] == "approved"

