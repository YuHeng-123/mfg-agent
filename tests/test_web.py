"""HTTP-level tests: the page is served, and the write paths stay drafts."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from core.store import records


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_index_page_is_served(client: TestClient):
    res = client.get("/")
    assert res.status_code == 200
    assert "设备知识 Agent" in res.text
    assert "equipment" in res.text and "compliance" in res.text


def test_ask_over_http_returns_claims_with_citations(client: TestClient):
    res = client.post(
        "/api/ask",
        json={"domain": "equipment", "query": "3 号线空压机报 E05，排气温度 118℃，怎么处理？"},
    )
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
    monkeypatch.setattr(records, "DB_PATH", tmp_path / "state.sqlite3")
    body = client.post(
        "/api/tickets/draft",
        json={"device_id": "AC-300-03", "fault_code": "E05", "symptom": "排气温度高"},
    ).json()
    assert body["draft"]["status"] == "draft"
    assert body["needs_confirmation"] is True


def test_unconfirmed_record_is_not_in_the_official_list(client: TestClient, tmp_path, monkeypatch):
    """The rule that matters: a draft is not an instruction yet."""

    monkeypatch.setattr(records, "DB_PATH", tmp_path / "state.sqlite3")
    created = client.post(
        "/api/tickets/draft",
        json={"device_id": "AC-300-03", "fault_code": "E05", "symptom": "排气温度高"},
    ).json()["draft"]

    body = client.get("/api/records", params={"kind": "ticket"}).json()
    assert any(r["id"] == created["id"] for r in body["items"])
    assert all(r["id"] != created["id"] for r in body["official"])

    confirmed = client.post(f"/api/records/{created['id']}/confirm").json()["record"]
    assert confirmed["status"] == "confirmed"
    body = client.get("/api/records", params={"kind": "ticket"}).json()
    assert any(r["id"] == created["id"] for r in body["official"])


def test_record_state_machine_rejects_backwards_moves(client: TestClient, tmp_path, monkeypatch):
    monkeypatch.setattr(records, "DB_PATH", tmp_path / "state.sqlite3")
    client.post(
        "/api/gaps/record", json={"gap_id": "G-01", "clause_id": "7.1.6", "target_doc": "质量手册"}
    ).json()
    rid = client.get("/api/records", params={"kind": "gap"}).json()["items"][0]["id"]

    client.post(f"/api/records/{rid}/confirm").json()
    client.post(f"/api/records/{rid}/close").json()
    assert client.get("/api/records", params={"kind": "gap"}).json()["items"][0]["status"] == "closed"

    # closed -> confirmed, and confirming twice, are both illegal
    assert client.post(f"/api/records/{rid}/confirm").status_code == 409
    assert client.post(f"/api/records/{rid}/close").status_code == 409
    assert client.post("/api/records/99999/confirm").status_code == 404


def test_healthz_reports_a_warm_index(client: TestClient):
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["index_ready"] is True
    assert body["issues"] == []
    assert body["corpus"]["equipment"]["chunks"] > 0
    assert body["corpus"]["compliance"]["chunks"] > 0


def test_startup_self_check_names_the_missing_file(monkeypatch):
    """An empty corpus and a broken retrieval look identical from the outside.

    Saying which file is absent is the whole point of the self-check.
    """

    from pathlib import Path

    from app import boot
    from domains.base import load_domain

    domain = load_domain("equipment")
    monkeypatch.setattr(domain, "sources", lambda: [Path("data/equipment/manuals/nope.pdf")])
    state = boot.warm()
    assert any("equipment" in i and "nope.pdf" in i for i in state["issues"])
    assert state["ready"] is False
    boot.warm()  # put the global state back for the rest of the suite


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
