"""Service key enforcement: the engine must not answer anonymous callers."""
import os

os.environ.setdefault("ENV", "test")

import pytest
from fastapi.testclient import TestClient

from app import create_app

KEY = "unit-test-service-key-0123456789abcdef"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("ALLOW_UNAUTHENTICATED_DEV", raising=False)
    monkeypatch.setenv("INTERNAL_SERVICE_KEY", KEY)
    return TestClient(create_app(), raise_server_exceptions=False)


def test_protected_routes_reject_missing_and_wrong_key(client):
    for path in ["/api/v1/models", "/api/v1/metrics", "/metrics", "/docs", "/openapi.json", "/internal/v1/worker/health"]:
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers={"x-service-key": "wrong"}).status_code == 401, path


def test_try_on_requires_key(client):
    res = client.post("/api/v1/try-on", json={"person_image": "x", "garment_image": "y", "category": "tops"})
    assert res.status_code == 401


def test_valid_key_is_accepted(client):
    res = client.get("/api/v1/models", headers={"x-service-key": KEY})
    assert res.status_code == 200


def test_probes_and_static_stay_public(client):
    assert client.get("/health").status_code == 200
    assert client.get("/live").status_code == 200
    assert client.get("/ready").status_code in (200, 503)
    # static results are public (404 for a missing file, never 401)
    assert client.get("/static/results/does-not-exist.jpg").status_code == 404


def test_root_is_minimal_without_key(client):
    body = client.get("/").json()
    assert set(body.keys()) == {"service", "status"}
    full = client.get("/", headers={"x-service-key": KEY}).json()
    assert "providers" in full


def test_fails_closed_when_key_not_configured(monkeypatch):
    monkeypatch.delenv("INTERNAL_SERVICE_KEY", raising=False)
    monkeypatch.delenv("ALLOW_UNAUTHENTICATED_DEV", raising=False)
    client = TestClient(create_app(), raise_server_exceptions=False)
    assert client.get("/api/v1/models").status_code == 503
    assert client.get("/health").status_code == 200
