"""真模型接入：开关、解析、以及"模型胡说时闸还管不管用"。

这里不联网。httpx.post 被替换成假的返回值，测的是三件事：
  1. 默认还是 stub（pytest 和评测不能依赖网络）
  2. PROVIDER=openai 且给了 key 时，会走真 provider，并把 JSON 解析成 claims
  3. **真模型编出来的引用，照样过不了引用校验**——这是整个项目最想证明的一条：
     模型的可靠性靠生成之后的校验，不靠提示词
"""

from __future__ import annotations

import json as _json

import httpx
import pytest

from core.agent import providers
from core.agent.loop import ask
from core.config import settings


class _FakeResponse:
    def __init__(self, payload: dict | str) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        content = (
            self._payload
            if isinstance(self._payload, str)
            else _json.dumps(self._payload, ensure_ascii=False)
        )
        return {"choices": [{"message": {"content": content}}]}


@pytest.fixture
def real_provider(monkeypatch):
    monkeypatch.setattr(settings, "provider", "openai")
    monkeypatch.setattr(settings, "api_key", "sk-test-not-used")
    yield


def test_default_provider_is_stub():
    status = providers.provider_status()
    assert status["effective"] == "stub"
    assert isinstance(providers.get_provider(), providers.StubProvider)


def test_missing_key_falls_back_to_stub_but_says_so(monkeypatch):
    monkeypatch.setattr(settings, "provider", "openai")
    monkeypatch.setattr(settings, "api_key", "")
    status = providers.provider_status()
    assert status["effective"] == "stub"
    assert "LLM_API_KEY" in status["reason"], "静默降级必须能查出来"


def test_real_provider_parses_json_into_claims(real_provider, monkeypatch):
    """真 provider 走通了：模型返回的 JSON 变成带 citation_ids 的结论。"""

    seen: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        # evidence 在 messages[1] 的 content 里（provider 把整段请求体打包成一个 JSON 字符串）
        body = _json.loads(json["messages"][1]["content"])
        evidence = body["evidence"]
        seen["chunks"] = [e["chunk_id"] for e in evidence]
        first = evidence[0]["chunk_id"]
        return _FakeResponse({"claims": [{"text": "排气温度超过 105℃ 报警。", "citation_ids": [first]}]})

    monkeypatch.setattr("httpx.post", fake_post)
    result = ask("equipment", "AX300 报 E05 怎么处理")

    assert result.provider == "openai_compat"
    assert result.answer.refusal is None
    assert result.answer.claims[0].text == "排气温度超过 105℃ 报警。"
    assert seen["chunks"], "provider 应该把检索到的证据一起发给模型"


def test_fabricated_citation_from_a_real_model_is_rejected(real_provider, monkeypatch):
    """模型编一个不存在的 chunk_id → 这条结论降级，整体转拒答。"""

    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse(
            {
                "claims": [
                    {"text": "排气温度超过 105℃ 报警。", "citation_ids": ["AX300_manual#p99#s99#c01"]},
                    {"text": "按厂家要求每 500 小时更换油滤。", "citation_ids": ["made-up-chunk-id"]},
                ]
            }
        )

    monkeypatch.setattr("httpx.post", fake_post)
    result = ask("equipment", "AX300 报 E05 怎么处理")

    assert result.answer.refusal is not None
    assert result.answer.refusal.kind == "insufficient_evidence"
    assert result.answer.text == "", "整条答案不该展示出来"


def test_unparsable_model_output_fails_closed(real_provider, monkeypatch):
    """模型返回不是 JSON → provider 返回空 claims → 拒答，而不是把原文糊上去。"""

    monkeypatch.setattr("httpx.post", lambda *a, **k: _FakeResponse("抱歉，我无法回答。"))
    result = ask("equipment", "AX300 报 E05 怎么处理")
    assert result.answer.refusal is not None
    assert result.answer.refusal.kind == "insufficient_evidence"


def test_network_error_fails_closed(real_provider, monkeypatch):
    def boom(*_a, **_k):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr("httpx.post", boom)
    result = ask("equipment", "AX300 报 E05 怎么处理")
    assert result.answer.refusal is not None
