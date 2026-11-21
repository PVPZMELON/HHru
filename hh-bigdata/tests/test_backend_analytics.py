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



def test_vacancy_catalog_paginates_and_returns_salary_and_skills(db, monkeypatch):
    run_etl(db, [
        hh_item(1),
        hh_item(2, name="Java-разработчик", key_skills=[{"name": "Java"}]),
        hh_item(3, area={"id": "2", "name": "Казань"}),
    ], origin="import", description="test", params={})
    client = _client_with_db(monkeypatch, db)

    response = client.get("/api/v1/vacancies", params={"page": 1, "page_size": 2})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["page"] == 1
    assert len(payload["items"]) == 2
    assert payload["items"][0]["salary"]["currency"] == "RUB"
    assert "Python" in payload["items"][0]["skills"]

    second = client.get("/api/v1/vacancies", params={"page": 2, "page_size": 2})
    assert second.status_code == 200
    assert len(second.json()["items"]) == 1


def test_vacancy_catalog_filters_search_and_rejects_bad_sort(db, monkeypatch):
    run_etl(db, [
        hh_item(1),
        hh_item(2, name="Java-разработчик", key_skills=[{"name": "Java"}]),
        hh_item(3, area={"id": "2", "name": "Казань"}),
    ], origin="import", description="test", params={})
    client = _client_with_db(monkeypatch, db)

    filtered = client.get("/api/v1/vacancies", params={"q": "Python", "region": "Москва"})
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 2

    by_skill = client.get("/api/v1/vacancies", params=[("skills", "Python"), ("skills", "SQL")])
    assert by_skill.status_code == 200
    assert by_skill.json()["total"] == 2

    invalid = client.get("/api/v1/vacancies", params={"sort": "DROP TABLE"})
    assert invalid.status_code == 400


def test_vacancy_catalog_facets(db, monkeypatch):
    run_etl(db, [hh_item(1)], origin="import", description="test", params={})
    client = _client_with_db(monkeypatch, db)

    response = client.get("/api/v1/vacancies/facets")
    assert response.status_code == 200
    assert "От 1 года до 3 лет" in response.json()["experience"]
    assert "Python" in response.json()["skills"]


def test_salary_analytics_returns_comparable_basis_and_group_summaries(db, monkeypatch):
    items = [
        hh_item(i, area={"id": "1" if i <= 6 else "2", "name": "Москва" if i <= 6 else "Казань"})
        for i in range(1, 11)
    ]
    run_etl(db, items, origin="import", description="test", params={})
    client = _client_with_db(monkeypatch, db)

    response = client.get("/api/v1/analytics/salaries")
    assert response.status_code == 200
    payload = response.json()
    assert payload["sample"]["vacancies"] == 10
    assert payload["sample"]["comparable"] == 10
    assert payload["basis"]["currency"] == "RUB"
    assert payload["statistics"]["median"] == 150000
    assert {row["name"] for row in payload["by_region"]} == {"Москва", "Казань"}
    reliability = {row["name"]: row["reliable"] for row in payload["by_region"]}\n    assert reliability == {"Москва": True, "Казань": False}


def test_skills_analytics_returns_demand_and_salary_basis(db, monkeypatch):
    run_etl(db, [hh_item(i) for i in range(1, 8)],
            origin="import", description="test", params={})
    client = _client_with_db(monkeypatch, db)

    response = client.get("/api/v1/analytics/skills", params={"limit": 10})
    assert response.status_code == 200
    payload = response.json()
    assert payload["sample"]["vacancies"] == 7
    assert payload["items"]
    assert payload["items"][0]["name"] in {"Python", "SQL", "Docker"}
    assert 0 < payload["items"][0]["share"] <= 1
    assert payload["salary_basis"]["currency"] == "RUB"


def test_regions_analytics_returns_vacancy_counts_and_reliable_salary(db, monkeypatch):
    run_etl(db, [
        hh_item(i, area={"id": "1" if i <= 6 else "2", "name": "Москва" if i <= 6 else "Казань"})
        for i in range(1, 9)
    ], origin="import", description="test", params={})
    client = _client_with_db(monkeypatch, db)

    response = client.get("/api/v1/analytics/regions")
    assert response.status_code == 200
    payload = response.json()
    assert payload["sample"]["vacancies"] == 8
    assert payload["sample"]["regions"] == 2
    assert payload["items"][0]["region"] in {"Москва", "Казань"}
    assert payload["items"][0]["comparable_salary_count"] >= 5
    assert payload["items"][0]["reliable_salary"] is True


def test_analytics_endpoints_validate_date_filters():
    client = TestClient(api.app)
    for endpoint in ("salaries", "skills", "regions"):
        response = client.get(
            f"/api/v1/analytics/{endpoint}",
            params={"date_from": "2026-10-10", "date_to": "2026-10-01"},
        )
        assert response.status_code == 400
