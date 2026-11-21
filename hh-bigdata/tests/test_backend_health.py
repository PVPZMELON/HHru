from fastapi.testclient import TestClient

from backend.app.main import app


def test_health_endpoint_is_live():
    response = TestClient(app).get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "hhru-api"


def test_openapi_is_available():
    response = TestClient(app).get("/api/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "HHru Vacancy Analytics API"
