"""配额：证明超阈值真的被拦，而不是日志里写了一句。

两类断言：
1. 配额用完之后返回 429，且带 Retry-After / X-RateLimit-Remaining 响应头；
2. 拦截发生在**调用检索之前**——即 429 的响应时间里没有 ask 的痕迹
   （用 metrics 里 ask_total 不增长来证明，而不是靠读代码相信）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app, limiter
from core.config import settings
from core.observability import metrics


@pytest.fixture
def tiny_quota(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_per_minute", 2)
    limiter.per_minute = 2
    limiter.reset()
    metrics.reset()
    yield 2
    limiter.per_minute = settings.rate_limit_per_minute
    limiter.reset()


def test_third_request_in_the_window_is_429(tiny_quota):
    client = TestClient(app)
    body = {"domain": "equipment", "query": "AX300 报 E05 怎么处理"}

    first = client.post("/api/ask", json=body)
    second = client.post("/api/ask", json=body)
    third = client.post("/api/ask", json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.json()["detail"] == "请求过于频繁，请稍后再试"
    assert third.headers["Retry-After"].isdigit()
    assert third.headers["X-RateLimit-Remaining"] == "0"
    assert first.headers["X-RateLimit-Remaining"] == "1"


def test_blocked_requests_never_reach_retrieval(tiny_quota):
    client = TestClient(app)
    body = {"domain": "equipment", "query": "AX300 报 E05 怎么处理"}

    for _ in range(2):
        client.post("/api/ask", json=body)
    before = metrics.snapshot()["ask_total"]

    assert client.post("/api/ask", json=body).status_code == 429
    assert metrics.snapshot()["ask_total"] == before, "被限流的请求不该进到 ask 里"


def test_quota_is_per_caller(tiny_quota):
    client = TestClient(app)
    body = {"domain": "equipment", "query": "AX300 报 E05 怎么处理"}

    for _ in range(2):
        client.post("/api/ask", json=body, headers={"X-API-Key": "alice"})
    # alice 用完了，bob 还有自己的额度
    assert client.post("/api/ask", json=body, headers={"X-API-Key": "alice"}).status_code == 429
    assert client.post("/api/ask", json=body, headers={"X-API-Key": "bob"}).status_code == 200


def test_probe_endpoints_are_not_quota_limited(tiny_quota):
    client = TestClient(app)
    for _ in range(10):
        assert client.get("/healthz").status_code == 200
        assert client.get("/metrics").status_code == 200


def test_429_shows_up_in_metrics(tiny_quota):
    client = TestClient(app)
    body = {"domain": "equipment", "query": "AX300 报 E05 怎么处理"}
    for _ in range(3):
        client.post("/api/ask", json=body)
    text = client.get("/metrics").text
    assert 'status="429"' in text
