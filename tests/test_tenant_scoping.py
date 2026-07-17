"""Tenant scoping for usage/cost read endpoints."""

from __future__ import annotations

from glc import db


def test_calls_endpoint_scoped_by_tenant_header(app_client):
    db.log_call(provider="gemini", model="m", status="ok", tenant="tenant_a")
    db.log_call(provider="groq", model="m", status="ok", tenant="tenant_b")

    res_a = app_client.get("/v1/calls", headers={"X-GLC-Tenant": "tenant_a"})
    assert res_a.status_code == 200
    rows_a = res_a.json()
    assert rows_a, "expected rows for tenant_a"
    assert all(r.get("tenant") == "tenant_a" for r in rows_a)

    res_b = app_client.get("/v1/calls", headers={"X-GLC-Tenant": "tenant_b"})
    assert res_b.status_code == 200
    rows_b = res_b.json()
    assert rows_b, "expected rows for tenant_b"
    assert all(r.get("tenant") == "tenant_b" for r in rows_b)


def test_cost_by_agent_endpoint_scoped_by_tenant_header(app_client):
    db.log_call(
        provider="gemini",
        model="m",
        status="ok",
        input_tokens=100,
        output_tokens=50,
        agent="agent_a",
        session="s1",
        tenant="tenant_a",
    )
    db.log_call(
        provider="groq",
        model="m",
        status="ok",
        input_tokens=20,
        output_tokens=10,
        agent="agent_b",
        session="s2",
        tenant="tenant_b",
    )

    res_a = app_client.get("/v1/cost/by_agent", headers={"X-GLC-Tenant": "tenant_a"})
    assert res_a.status_code == 200
    body_a = res_a.json()
    assert "agent_a" in body_a
    assert "agent_b" not in body_a

    res_b = app_client.get("/v1/cost/by_agent", headers={"X-GLC-Tenant": "tenant_b"})
    assert res_b.status_code == 200
    body_b = res_b.json()
    assert "agent_b" in body_b
    assert "agent_a" not in body_b


def test_invalid_tenant_identifier_rejected(app_client):
    res = app_client.get("/v1/calls", headers={"X-GLC-Tenant": "bad tenant"})
    assert res.status_code == 400
