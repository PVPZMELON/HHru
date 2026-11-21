from fastapi.testclient import TestClient

from backend.app import main as api
from src.pipeline import run_etl
from tests.conftest import hh_item


def _client_with_db(monkeypatch, db):
    monkeypatch.setattr(api, "get_engine_for_test", lambda: db, raising=False)
    monkeypatch.setattr("src.db.session.get_engine", lambda: db)
    return TestClient(api.app)


def test_filter_options_returns_real_dictionary_values(db, monkeypatch):
    run_etl(db, [hh_item(1), hh_item(2, area={"id": "2", "name": "Казань"})],
            origin="import", description="test", params={})
    client = _client_with_db(monkeypatch, db)

    response = client.get("/api/v1/filters/options")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert set(payload["regions"]) == {"Москва", "Казань"}
    assert payload["origins"] == ["import"]
    assert payload["date_min"] == "2026-10-01"


def test_overview_uses_existing_metrics_and_supports_filters(db, monkeypatch):
    run_etl(db, [
        hh_item(1),
        hh_item(2),
        hh_item(3, area={"id": "2", "name": "Казань"}),
        hh_item(4, salary=None),
    ], origin="import", description="test", params={})
    client = _client_with_db(monkeypatch, db)

    all_response = client.get("/api/v1/overview")
    filtered_response = client.get("/api/v1/overview", params={"region": "Москва"})

    assert all_response.status_code == 200
    all_data = all_response.json()
    assert all_data["sample"]["vacancies"] == 4
    assert all_data["sample"]["employers"] == 4
    assert all_data["salary"]["comparable_count"] == 3
    assert all_data["salary_disclosure"]["count"] == 3
    assert all_data["top_skill"]["name"] == "Docker"

    assert filtered_response.status_code == 200
    assert filtered_response.json()["sample"]["vacancies"] == 3
    assert filtered_response.json()["filters"]["region"] == ["Москва"]


def test_overview_rejects_inverted_date_range():
    response = TestClient(api.app).get(
        "/api/v1/overview",
        params={"date_from": "2026-10-10", "date_to": "2026-10-01"},
    )
    assert response.status_code == 400
