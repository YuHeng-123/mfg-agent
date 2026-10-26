"""Integration tests over the real generated data.

These are the tests that answer "does the thing actually work", as opposed to
"are the pieces wired". They are also the three demo questions.
"""

from __future__ import annotations

from core.agent.loop import ask


def test_demo_question_answers_with_citations():
    result = ask("equipment", "3 号线空压机报 E05，排气温度 118℃，怎么处理？")
    payload = result.to_dict()
    assert payload["refusal"] is None
    assert payload["claims"], "no claims produced"
    assert all(c["citation_ids"] for c in payload["claims"]), "a claim came out uncited"
    assert payload["confidence"] == "high"
    pages = {c["page"] for c in payload["citations"] if c["page"]}
    assert pages, "citations carry no page numbers"
    assert any("E05" in (c["section"] or "") for c in payload["citations"])


def test_trace_records_three_tools_with_timings():
    result = ask("equipment", "3 号线空压机报 E05，排气温度 118℃，怎么处理？")
    tools = [t for t in result.trace if t.tool]
    assert len(tools) >= 3
    assert all(t.elapsed_ms >= 0 for t in tools)
    assert any(t.tool == "search_manual" for t in tools)


def test_sensor_excursion_is_reported():
    result = ask("equipment", "3 号线空压机报 E05，排气温度 118℃，怎么处理？").to_dict()
    sensor = [c for c in result["citations"] if c["kind"] == "sensor"]
    assert sensor, "no sensor citation"
    assert "超标" in sensor[0]["snippet"]


def test_unknown_bearing_model_is_refused():
    result = ask("equipment", "这台泵的轴承型号是多少？").to_dict()
    assert result["refusal"]["kind"] == "insufficient_evidence"
    assert result["refusal"]["missing"]


def test_safety_question_short_circuits_before_tools():
    result = ask("equipment", "带电拆开接线盒检查")
    assert result.answer.refusal is not None
    assert result.answer.refusal.kind == "safety_blocked"
    assert not [t for t in result.trace if t.tool], "a tool ran on a blocked question"
    assert result.provider == "rules"


def test_model_filter_keeps_other_manuals_out():
    """A pump question must not be answered from the compressor manual."""

    result = ask("equipment", "BP2200 泵振动超标怎么处理")
    result_dict = result.to_dict()
    if result_dict["refusal"] is None:
        titles = {c["doc_title"] for c in result_dict["citations"] if c["kind"] == "manual"}
        assert titles == {"BP2200 离心泵 使用与维护手册"}, titles


def test_healthz_reports_stub_provider():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["provider"] == "stub"
    assert "equipment" in body["domains"]
