"""HTTP-level tests: the page is served, and the write paths stay drafts."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from domains.equipment import tools as eq_tools


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_index_page_is_served(client: TestClient):
    res = client.get("/")
    assert res.status_code == 200
    assert "设备知识 Agent" in res.text
    assert "equipment" in res.text and "compliance" in res.text


def test_ask_over_http_returns_claims_with_citations(client: TestClient):
    res = client.post("/api/ask", json={"domain": "equipment", "query": "3 号线空压机报 E05，排气温度 118℃，怎么处理？"})
    body = res.json()
    assert res.status_code == 200
    assert body["refusal"] is None
    assert body["claims"] and all(c["citation_ids"] for c in body["claims"])
    assert body["findings"] == []


def test_refusal_over_http(client: TestClient):
    body = client.post("/api/ask", json={"domain": "equipment", "query": "带电拆开接线盒检查"}).json()
    assert body["refusal"]["kind"] == "safety_blocked"


def test_compliance_findings_reach_the_client(client: TestClient):
    body = client.post(
        "/api/ask",
        json={"domain": "compliance", "query": "对照新版 7.1.6 组织知识，我们质量手册要改哪几处"},
    ).json()
    ids = {f["gap_id"] for f in body["findings"]}
    assert {"G-01", "G-02"} <= ids


def test_draft_is_never_confirmed_automatically(client: TestClient, tmp_path, monkeypatch):
    monkeypatch.setattr(eq_tools, "DRAFT_PATH", tmp_path / "drafts.jsonl")
    body = client.post(
        "/api/tickets/draft",
        json={"device_id": "AC-300-03", "fault_code": "E05", "symptom": "排气温度高"},
    ).json()
    assert body["draft"]["status"] == "draft"
    assert body["needs_confirmation"] is True


def test_eval_endpoint_quotes_a_real_report(client: TestClient):
    body = client.get("/api/eval/latest").json()
    if not body.get("available"):
        pytest.skip("no report yet")
    assert body["file"].endswith(".json")
    assert 0.0 <= body["equipment"]["recall@1"] <= 1.0
    assert 0.0 <= body["compliance"]["gap_recall"] <= 1.0


def test_unknown_domain_is_rejected(client: TestClient):
    res = client.post("/api/ask", json={"domain": "nope", "query": "你好"})
    assert res.status_code == 404
