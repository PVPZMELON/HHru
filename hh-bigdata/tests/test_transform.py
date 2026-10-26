from datetime import datetime, timezone

from src.etl.transform import (clean_text, compute_hash, deduplicate, html_to_text, norm_key, normalize_record,
                               quality_summary, transform_batch)
from tests.conftest import hh_item


def test_clean_and_html():
    assert clean_text("  a \n  b &amp; c ") == "a b & c"
    assert clean_text("   ") is None and clean_text(None) is None
    assert html_to_text("<p>Один</p><ul><li>Два</li><li>Три</li></ul>") == "Один\nДва\nТри"
    assert html_to_text("") is None and len(html_to_text("x" * 20000)) == 8000


def test_norm_key_employer_legal_forms():
    assert norm_key('ООО «Ромашка»', strip_legal_form=True) == "ромашка"
    assert norm_key("ПАО  Ёлка", strip_legal_form=True) == "елка"
    assert norm_key("Москва ") == "москва"


def test_normalize_full_record():
    rec, issues = normalize_record(hh_item(1), "api")
    assert issues == []
    assert rec["source_id"] == "1" and rec["salary_kind"] == "range" and rec["salary_mid"] == 150000
    assert rec["salary_currency"] == "RUB" and rec["salary_gross"] is True
    assert rec["employer_norm"] == "ромашка" and rec["region_norm"] == "москва"
    assert rec["published_at"] == datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc)
    assert [s["name"] for s in rec["skills"] if s["origin"] == "structured"] == ["Python", "SQL"]
    assert {"name": "Docker", "origin": "text"} in rec["skills"]       # навык из описания
    assert rec["data_origin"] == "api" and len(rec["content_hash"]) == 64


def test_missing_fields_are_kept_as_none_not_invented():
    rec, issues = normalize_record({"id": 5, "name": "Тест"}, "import")
    assert rec["employer_name"] is None and rec["region_name"] is None and rec["published_at"] is None
    assert rec["salary_kind"] == "none" and rec["skills"] == [] and rec["url"] is None
    assert {i.issue_type for i in issues} == {"missing_region", "missing_employer", "missing_role"}


def test_rejected_records():
    assert normalize_record({"name": "без id"}, "api")[0] is None
    r, iss = normalize_record({"id": 1}, "api")
    assert r is None and iss[0].issue_type == "missing_title"
    assert normalize_record("строка", "api")[0] is None


def test_invalid_salary_not_stored_but_logged():
    rec, issues = normalize_record(hh_item(1, salary={"from": 300000, "to": 100000, "currency": "RUR"}), "api")
    assert rec["salary_kind"] == "invalid" and rec["salary_from"] is None and rec["salary_to"] is None
    issue = next(i for i in issues if i.issue_type == "invalid_salary")
    assert "300000" in issue.details    # исходное значение сохранено в журнале


def test_hash_changes_with_content_only():
    a, _ = normalize_record(hh_item(1), "api")
    b, _ = normalize_record(hh_item(1), "api")
    c, _ = normalize_record(hh_item(1, salary={"from": 1, "to": 2, "currency": "RUR", "gross": True}), "api")
    assert a["content_hash"] == b["content_hash"] != c["content_hash"]


def test_deduplicate_exact_and_conflicting():
    older = hh_item(1, updated_at="2026-10-01T10:00:00+0300")
    newer = hh_item(1, updated_at="2026-10-02T10:00:00+0300", name="Новое название")
    res = transform_batch([hh_item(2), older, dict(hh_item(2)), newer], "api")
    assert res.fetched == 4 and len(res.records) == 2 and res.duplicates_removed == 2
    kept = {r["source_id"]: r for r in res.records}
    assert kept["1"]["title"] == "Новое название"                       # оставлена самая свежая версия
    assert any(i.issue_type == "conflicting_duplicate" and i.source_id == "1" for i in res.issues)
    assert not any(i.issue_type == "conflicting_duplicate" and i.source_id == "2" for i in res.issues)  # точный дубль


def test_possible_duplicates_flagged_not_removed():
    a = hh_item(1, employer={"id": None, "name": "Альфа"})
    b = hh_item(2, employer={"id": None, "name": "Альфа"}, name=a["name"])
    b["name"] = a["name"]
    res = transform_batch([a, b], "api")
    assert len(res.records) == 2
    assert {i.source_id for i in res.issues if i.issue_type == "possible_duplicate"} == {"1", "2"}


def test_empty_batch():
    res = transform_batch([], "api")
    assert res.records == [] and res.fetched == 0 and res.rejected == 0
    assert quality_summary([]) == {}


def test_quality_summary_shares():
    res = transform_batch([hh_item(1), hh_item(2, salary=None), {"id": 3, "name": "x"}], "api")
    q = quality_summary(res.records)
    assert q["salary_none"] == round(2 / 3, 4) and q["employer_name"] == round(1 / 3, 4)
