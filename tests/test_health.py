from fastapi.testclient import TestClient

from src.config.settings import get_settings
from src.main import app

client = TestClient(app)
settings = get_settings()


def test_root_health() -> None:
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "agentic-job-applier"
    assert data["status"] == "ok"


def test_api_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "agentic-job-applier"


def test_cors_header_present_for_allowed_origin() -> None:
    allowed_origin = settings.cors_origins[0]
    response = client.get("/api/health", headers={"Origin": allowed_origin})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == allowed_origin


def test_cors_header_absent_for_foreign_origin() -> None:
    foreign_origin = "https://evil.example.com"
    assert foreign_origin not in settings.cors_origins  # guard the premise
    response = client.get("/api/health", headers={"Origin": foreign_origin})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_cors_preflight_allowed_origin_lists_configured_methods() -> None:
    allowed_origin = settings.cors_origins[0]
    response = client.options(
        "/api/health",
        headers={
            "Origin": allowed_origin,
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == allowed_origin
    assert "POST" in response.headers["access-control-allow-methods"]
