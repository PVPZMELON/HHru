"""Тесты клиента hh.ru на имитированных ответах (реальный API в тестах не вызывается)."""
import pytest
import requests

from src.collectors.hh_client import AccessDenied, ApiError, HhClient, HH_MAX_DEPTH
from src.config import CollectorSettings


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeSession:
    """handler(url, params) -> Resp | Exception; фиксирует все обращения."""
    def __init__(self, handler):
        self.handler, self.headers, self.calls = handler, {}, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        out = self.handler(url, params or {})
        if isinstance(out, Exception):
            raise out
        return out


def cfg(**kw):
    base = dict(queries=["python"], areas=["1"], per_page=2, max_pages=5, max_vacancies=100, fetch_details=False,
                delay_sec=0, max_retries=2, max_requests=100, user_agent="Test/1.0 (t@example.com)", token="SECRET")
    base.update(kw)
    return CollectorSettings(**base)


def page_body(ids, page=0, pages=1, found=None):
    return {"items": [{"id": str(i), "name": f"v{i}"} for i in ids], "page": page, "pages": pages, "found": found or len(ids)}


def make(handler, **kw):
    sleeps = []
    session = FakeSession(handler)
    return HhClient(cfg(**kw), session=session, sleep=sleeps.append), session, sleeps


def test_headers_and_params():
    client, session, _ = make(lambda u, p: Resp(200, page_body([1])))
    client.collect()
    assert session.headers["Authorization"] == "Bearer SECRET" and "HH-User-Agent" in session.headers
    url, params = session.calls[0]
    assert url == "https://api.hh.ru/vacancies" and params == {"text": "python", "area": "1", "page": 0, "per_page": 2}


def test_period_param_only_when_set():
    client, session, _ = make(lambda u, p: Resp(200, page_body([1])), period_days=7)
    client.collect()
    assert session.calls[0][1]["period"] == 7


def test_pagination_and_dedup_across_queries():
    def handler(url, params):
        pg = params["page"]
        return Resp(200, page_body([pg * 2 + 1, pg * 2 + 2], pg, 3))
    client, session, _ = make(handler, queries=["a", "b"])
    res = client.collect()
    assert [i["id"] for i in res.items] == ["1", "2", "3", "4", "5", "6"]   # дубли между запросами удалены
    assert len(session.calls) == 6 and res.complete


def test_max_vacancies_limit():
    client, session, _ = make(lambda u, p: Resp(200, page_body([p["page"] * 2 + 1, p["page"] * 2 + 2], p["page"], 50)), max_vacancies=3)
    assert len(client.collect().items) == 3


def test_depth_limit_2000():
    client, session, _ = make(lambda u, p: Resp(200, page_body([p["page"] * 100 + 1], p["page"], 50)),
                              per_page=100, max_pages=50, max_vacancies=10_000)
    client.collect()
    assert len(session.calls) == HH_MAX_DEPTH // 100


def test_retry_on_429_honours_retry_after():
    answers = [Resp(429, {}, {"Retry-After": "3"}), Resp(200, page_body([1]))]
    client, session, sleeps = make(lambda u, p: answers.pop(0))
    res = client.collect()
    assert len(res.items) == 1 and 3.0 in sleeps and res.complete


def test_retry_on_network_error_then_success():
    answers = [requests.ConnectionError("x"), requests.Timeout("y"), Resp(200, page_body([1]))]
    client, session, sleeps = make(lambda u, p: answers.pop(0))
    assert len(client.collect().items) == 1 and sleeps == [1.0, 2.0]


def test_no_infinite_retry_on_500():
    client, session, sleeps = make(lambda u, p: Resp(503, {}))
    res = client.collect()
    assert len(session.calls) == 3 and res.items == [] and res.errors and res.stopped_reason == "search_error"


def test_403_is_not_retried_or_bypassed():
    client, session, sleeps = make(lambda u, p: Resp(403, {"errors": [{"type": "captcha_required"}]}))
    res = client.collect()
    assert len(session.calls) == 1 and sleeps == []
    assert res.stopped_reason == "access_denied" and "не обходится" in res.errors[0]


def test_401_access_denied_message_mentions_import():
    client, _, _ = make(lambda u, p: Resp(401, {}))
    with pytest.raises(AccessDenied, match="импорт"):
        client.search_page("python", "1", 0)


def test_request_budget():
    client, session, _ = make(lambda u, p: Resp(200, page_body([p["page"] + 1], p["page"], 10)), max_requests=2)
    res = client.collect()
    assert len(session.calls) == 2 and res.stopped_reason == "request_budget"
    assert len(res.items) == 2     # собранное сохраняется


def test_bad_structure_and_non_json():
    client, _, _ = make(lambda u, p: Resp(200, {"unexpected": 1}))
    with pytest.raises(ApiError, match="items"):
        client.search_page("python", "1", 0)
    client, _, _ = make(lambda u, p: Resp(200, None))
    with pytest.raises(ApiError, match="JSON"):
        client.search_page("python", "1", 0)
    client, _, _ = make(lambda u, p: Resp(400, {}))
    with pytest.raises(ApiError, match="400"):
        client.search_page("python", "1", 0)


def test_details_merged_and_failures_tolerated():
    def handler(url, params):
        if url.endswith("/vacancies"):
            return Resp(200, page_body([1, 2, 3]))
        vid = url.rsplit("/", 1)[1]
        if vid == "2":
            return Resp(404, {})
        return Resp(200, {"id": vid, "key_skills": [{"name": "Python"}], "description": "<p>d</p>"})
    client, _, _ = make(handler, fetch_details=True, per_page=3)
    res = client.collect()
    assert [i["id"] for i in res.items] == ["1", "2", "3"]
    assert res.items[0]["key_skills"] and "key_skills" not in res.items[1]   # для 404 остаётся запись из выдачи
    assert res.details_fetched == 2 and any("404" in e for e in res.errors) and not res.complete


def test_details_access_denied_keeps_listing():
    def handler(url, params):
        return Resp(200, page_body([1, 2])) if url.endswith("/vacancies") else Resp(403, {})
    client, session, _ = make(handler, fetch_details=True)
    res = client.collect()
    assert len(res.items) == 2 and res.stopped_reason == "access_denied"
    assert len([c for c in session.calls if not c[0].endswith("/vacancies")]) == 1   # после отказа детали не запрашиваются
