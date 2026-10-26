from __future__ import annotations

from core.rag.tokenize import bigrams_only, tokenize
from core.types import Chunk


def test_structured_tokens_survive_intact():
    toks = tokenize("AX300 报 E05，排气温度 118℃，滤芯压差 0.15MPa")
    assert "e05" in toks
    assert "ax300" in toks
    assert "118℃" in toks
    assert "0.15mpa" in toks


def test_hyphenated_model_is_one_token():
    toks = tokenize("3 号线 AX-300 空压机")
    assert "ax-300" in toks


def test_ticket_number_is_one_token():
    assert "t-0912-014" in tokenize("参考工单 T-0912-014 的处理方式")


def test_cjk_bigrams():
    toks = tokenize("排气温度高")
    for expected in ("排气", "气温", "温度", "度高"):
        assert expected in toks


def test_no_noise_bigrams_from_structured_span():
    # "E05" must not contribute "e0" / "05"
    toks = tokenize("E05")
    assert toks == ["e05"]


def test_single_cjk_char_kept():
    assert "泵" in tokenize("泵")


def test_empty_input():
    assert tokenize("") == []
    assert bigrams_only("") == []


def test_chunk_cite_kind_follows_doc_type():
    c = Chunk(
        chunk_id="S1#c1",
        doc_id="S1",
        doc_title="新版标准",
        text="组织应确定必要的知识并保持可获得。",
        section="7.1.6",
        meta={"doc_type": "standard"},
    )
    assert c.cite().kind == "standard"
    assert c.cite().snippet.startswith("组织应确定")
