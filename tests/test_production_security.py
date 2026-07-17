from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def production_client(monkeypatch):
    monkeypatch.setenv("GLC_ENV", "production")
    monkeypatch.setenv("GLC_GATEWAY_AUTH_TOKEN", "prod-test-token")

    import glc.main as m

    importlib.reload(m)
    with TestClient(m.app) as client:
        yield client

    # Restore non-production behavior for the rest of the suite.
    monkeypatch.delenv("GLC_ENV", raising=False)
    monkeypatch.delenv("GLC_GATEWAY_AUTH_TOKEN", raising=False)
    importlib.reload(m)


def test_production_blocks_all_routes_without_bearer(production_client):
    r = production_client.get("/healthz")
    assert r.status_code == 401


def test_production_hides_openapi_and_docs_without_auth(production_client):
    docs = production_client.get("/docs")
    assert docs.status_code == 404

    openapi = production_client.get("/openapi.json")
    assert openapi.status_code == 404


def test_production_requires_correct_bearer(production_client):
    r = production_client.get("/healthz", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 403

    ok = production_client.get("/healthz", headers={"Authorization": "Bearer prod-test-token"})
    assert ok.status_code == 200


def test_production_hides_openapi_and_docs_even_when_authenticated(production_client):
    h = {"Authorization": "Bearer prod-test-token"}

    docs = production_client.get("/docs", headers=h)
    assert docs.status_code == 404

    openapi = production_client.get("/openapi.json", headers=h)
    assert openapi.status_code == 404
