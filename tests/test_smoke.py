"""Smoke test for Step 1: the app starts and the database layer works.

Run from the project root:  python -m pytest -q
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_index():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "running" in resp.json()["message"]