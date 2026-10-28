"""审计：证明每次提问真的落了一条可查的记录，且写不进去就不应答。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from core.store import audit, records


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(records, "DB_PATH", tmp_path / "state.sqlite3")
    audit.clear()
    yield


def test_every_question_lands_one_row():
    client = TestClient(app)
    client.post("/api/ask", json={"domain": "equipment", "query": "AX300 报 E05 怎么处理"})
    client.post("/api/ask", json={"domain": "equipment", "query": "带电拆开接线盒检查"})

    rows = client.get("/api/audit").json()["items"]
    assert len(rows) == 2

    answered, refused = rows[1], rows[0]
    assert answered["question"] == "AX300 报 E05 怎么处理"
    assert answered["outcome"] == "answered"
    assert answered["chunk_count"] > 0
    assert answered["citation_ids"], "命中哪些 chunk 要能查到"
    assert answered["elapsed_ms"] >= 0
    assert answered["ts"], "要有时间戳"

    assert refused["outcome"] == "refused"
    assert refused["refusal_kind"] == "safety_blocked"


def test_audit_is_queryable_and_filterable():
    client = TestClient(app)
    for q in ("AX300 报 E05 怎么处理", "BP2200 机械密封泄漏怎么处理"):
        client.post("/api/ask", json={"domain": "equipment", "query": q})
    client.post(
        "/api/ask", json={"domain": "compliance", "query": "对照新版 7.1.6 组织知识，我们质量手册要改哪几处"}
    )

    only_equipment = client.get("/api/audit", params={"domain": "equipment"}).json()["items"]
    assert len(only_equipment) == 2
    assert all(r["domain"] == "equipment" for r in only_equipment)

    limited = client.get("/api/audit", params={"limit": 1}).json()["items"]
    assert len(limited) == 1


def test_missing_audit_write_blocks_the_answer(monkeypatch):
    """留痕失败时必须拒绝应答——答了却查不到，比不答更糟。"""

    def boom(**_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(audit, "write", boom)
    client = TestClient(app)
    res = client.post("/api/ask", json={"domain": "equipment", "query": "AX300 报 E05 怎么处理"})
    assert res.status_code == 503
    assert "审计" in res.json()["detail"]
