import json

import pytest

from src.collectors import demo_data
from src.collectors.file_import import SourceFileError, read_records
from src.collectors.raw_store import save_jsonl
from src.etl.transform import transform_batch
from tests.conftest import hh_item


def test_jsonl_roundtrip_with_bad_lines(tmp_path):
    path = tmp_path / "x.jsonl"
    path.write_text(json.dumps(hh_item(1), ensure_ascii=False) + "\n\nне json\n[1,2]\n" + json.dumps(hh_item(2)) + "\n", encoding="utf-8")
    items, errors = read_records(path)
    assert [i["id"] for i in items] == ["1", "2"] and len(errors) == 2


def test_json_array_and_items_key(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps([hh_item(1), "x"]), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps({"items": [hh_item(1)]}), encoding="utf-8")
    assert len(read_records(tmp_path / "a.json")[0]) == 1 and len(read_records(tmp_path / "a.json")[1]) == 1
    assert len(read_records(tmp_path / "b.json")[0]) == 1


def test_csv_mapped_to_hh_structure(tmp_path):
    path = tmp_path / "v.csv"
    path.write_text("id;title;employer;area;salary_from;salary_to;currency;gross;skills;published_at\n"
                    "7;Аналитик;Альфа;Казань;100000;150000;RUR;да;\"Python; SQL\";2026-10-01\n"
                    "8;Тестер;;;;;;;;\n", encoding="utf-8-sig")
    items, errors = read_records(path)
    assert not errors and len(items) == 2
    rec = transform_batch(items, "import").records
    first = next(r for r in rec if r["source_id"] == "7")
    assert first["salary_mid"] == 125000 and first["salary_gross"] is True and first["region_name"] == "Казань"
    assert {"Python", "SQL"} <= {s["name"] for s in first["skills"]}
    second = next(r for r in rec if r["source_id"] == "8")
    assert second["salary_kind"] == "none" and second["employer_name"] is None


@pytest.mark.parametrize("name, content", [("x.txt", "a"), ("x.json", "{не json"), ("x.json", '"строка"')])
def test_bad_files(tmp_path, name, content):
    (tmp_path / name).write_text(content, encoding="utf-8")
    with pytest.raises(SourceFileError):
        read_records(tmp_path / name)


def test_missing_and_non_utf8(tmp_path):
    with pytest.raises(SourceFileError, match="не найден"):
        read_records(tmp_path / "nope.jsonl")
    (tmp_path / "w.csv").write_bytes("id,name\n1,Привет".encode("cp1251"))
    with pytest.raises(SourceFileError, match="UTF-8"):
        read_records(tmp_path / "w.csv")


def test_max_records_truncation(tmp_path):
    path = tmp_path / "x.jsonl"
    path.write_text("\n".join(json.dumps(hh_item(i)) for i in range(5)), encoding="utf-8")
    items, errors = read_records(path, max_records=3)
    assert len(items) == 3 and "первые 3" in errors[0]


def test_save_jsonl_atomic(tmp_path):
    p = save_jsonl([hh_item(1)], tmp_path / "raw", "t")
    assert p.exists() and not list(p.parent.glob("*.tmp")) and json.loads(p.read_text(encoding="utf-8"))["id"] == "1"


def test_demo_data_is_deterministic_and_labelled():
    from datetime import datetime, timezone
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    a, b = demo_data.generate(200, 1, now), demo_data.generate(200, 1, now)
    assert a == b and demo_data.generate(200, 2, now) != a
    ids = [i.get("id") for i in a if i.get("id")]
    assert all(str(i).startswith("demo-") for i in ids)
    assert all(i.get("alternate_url") is None for i in a)         # синтетика не притворяется реальной ссылкой
    res = transform_batch(a, "synthetic")
    assert res.rejected == 2 and res.duplicates_removed > 0       # намеренные дефекты обнаруживаются
    assert any(r["salary_kind"] == "invalid" for r in res.records)
