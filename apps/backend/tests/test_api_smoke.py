from fastapi.testclient import TestClient

from app.main import create_app


def test_health() -> None:
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_dashboard_endpoint() -> None:
    client = TestClient(create_app())
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert "total_jobs" in body
    assert "recent_runs" in body


def test_applied_jobs_trend_endpoint() -> None:
    client = TestClient(create_app())
    resp = client.get("/api/analytics/applied-jobs-trend")
    assert resp.status_code == 200
    body = resp.json()
    assert "source_used" in body
    assert "series" in body


def test_jobs_endpoint() -> None:
    client = TestClient(create_app())
    resp = client.get("/api/jobs?limit=10&offset=0")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body


def test_delete_jobs_endpoint() -> None:
    client = TestClient(create_app())
    resp = client.request("DELETE", "/api/jobs", json={"job_ids": [99999999]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "deleted" in body


def test_learning_topics_endpoint() -> None:
    client = TestClient(create_app())
    resp = client.get("/api/learning/topics")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert len(body["items"]) >= 4


def test_learning_quiz_endpoint() -> None:
    client = TestClient(create_app())
    topics_resp = client.get("/api/learning/topics")
    topic_key = topics_resp.json()["items"][0]["topic_key"]
    resp = client.get(f"/api/learning/quiz?topic_key={topic_key}&limit=3&lang=en")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert len(body["items"]) >= 1
