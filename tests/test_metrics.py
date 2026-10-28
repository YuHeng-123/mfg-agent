"""指标：证明 /metrics 暴露的是真数字，不是常量。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from core.observability import metrics


def setup_function() -> None:
    metrics.reset()


def test_metrics_move_when_requests_happen():
    client = TestClient(app)
    before = client.get("/api/metrics").json()

    client.post("/api/ask", json={"domain": "equipment", "query": "AX300 报 E05 怎么处理"})
    client.post("/api/ask", json={"domain": "equipment", "query": "带电拆开接线盒检查"})
    after = client.get("/api/metrics").json()

    assert after["ask_total"] == before["ask_total"] + 2
    assert after["requests_total"] > before["requests_total"]
    assert after["latency_ms"]["samples"] > 0
    # 一次应答 + 一次安全拒答
    assert after["answered"] >= 1
    assert after["refused"] >= 1
    assert 0 < after["refusal_rate"] <= 1
    assert after["latency_ms"]["p50"] >= 0 and after["latency_ms"]["p95"] >= after["latency_ms"]["p50"]


def test_prometheus_endpoint_exposes_the_four_required_signals():
    client = TestClient(app)
    client.post("/api/ask", json={"domain": "equipment", "query": "AX300 报 E05 怎么处理"})

    res = client.get("/metrics")
    assert res.status_code == 200
    assert "text/plain" in res.headers["content-type"]
    body = res.text

    # QPS / P95 / 错误率 / 拒答率
    for name in ("mfg_qps_60s", "mfg_ask_latency_ms", "mfg_error_rate", "mfg_refusal_rate"):
        assert name in body, f"缺指标 {name}"
    assert 'mfg_ask_total{domain="equipment",outcome="answered"}' in body
    assert 'mfg_http_requests_total{path="/api/ask",status="200"}' in body


def test_latency_header_is_present():
    client = TestClient(app)
    res = client.get("/healthz")
    assert float(res.headers["X-Response-Time-ms"]) >= 0
