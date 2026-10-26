from __future__ import annotations

import pytest

from core.rag.index import Index, rrf
from core.types import Chunk

CORPUS = [
    Chunk(
        chunk_id="AX300#p87#s53#c01",
        doc_id="AX300_manual",
        doc_title="AX300 螺杆空压机使用手册",
        page=87,
        section="5.3 故障代码 E05",
        text="E05 表示排气温度过高，通常由冷却水中断或空气滤芯堵塞引起。应先检查冷却水阀开度。",
        meta={"model_id": "AX300", "doc_type": "manual"},
    ),
    Chunk(
        chunk_id="AX300#p88#s532#c01",
        doc_id="AX300_manual",
        doc_title="AX300 螺杆空压机使用手册",
        page=88,
        section="5.3.2 滤芯维护",
        text="空气滤芯压差超过 0.15MPa 时应更换滤芯，更换前必须停机泄压。",
        meta={"model_id": "AX300", "doc_type": "manual"},
    ),
    Chunk(
        chunk_id="AX300#p12#s21#c01",
        doc_id="AX300_manual",
        doc_title="AX300 螺杆空压机使用手册",
        page=12,
        section="2.1 安全注意",
        text="检修前须断电挂牌上锁，高温管路禁止带压拆检。",
        meta={"model_id": "AX300", "doc_type": "manual"},
    ),
    Chunk(
        chunk_id="BX400#p71#s44#c01",
        doc_id="BX400_manual",
        doc_title="BX400 离心泵使用手册",
        page=71,
        section="4.4 振动报警",
        text="振动速度超过 4.5mm/s 时触发报警，检查联轴器对中与轴承磨损。",
        meta={"model_id": "BX400", "doc_type": "manual"},
    ),
    Chunk(
        chunk_id="BX400#p73#s45#c01",
        doc_id="BX400_manual",
        doc_title="BX400 离心泵使用手册",
        page=73,
        section="4.5 机械密封泄漏",
        text="机械密封泄漏时应停泵检修，禁止在运行状态下紧固压盖。",
        meta={"model_id": "BX400", "doc_type": "manual"},
    ),
]


@pytest.fixture(scope="module")
def index() -> Index:
    return Index(CORPUS)


def test_finds_the_right_paragraph(index: Index):
    hits = index.search("AX300 报 E05 排气温度高怎么处理", top_k=3)
    assert hits, "no hits at all"
    assert hits[0].chunk.chunk_id == "AX300#p87#s53#c01"


def test_model_filter_blocks_wrong_manual(index: Index):
    unfiltered = index.search("振动报警 4.5mm/s 怎么处理", top_k=5, model_id=None)
    filtered = index.search("振动报警 4.5mm/s 怎么处理", top_k=5, model_id="AX300")
    assert unfiltered[0].chunk.meta["model_id"] == "BX400"
    # Ask about pump vibration but restrict to the compressor manual: nothing may
    # come back, because answering with another model's procedure is the exact
    # failure this filter exists to prevent.
    assert filtered == []


def test_max_possible_is_an_upper_bound(index: Index):
    q = "排气温度高"
    hits = index.search(q, top_k=5)
    mp = index.max_possible(q)
    assert mp > 0
    assert all(h.score <= mp + 1e-9 for h in hits)


def test_normalised_top1_in_unit_range(index: Index):
    q = "E05 排气温度过高"
    hits = index.search(q, top_k=5)
    ratio = index.normalised_top1(q, hits)
    assert 0.0 < ratio <= 1.0


def test_unrelated_query_matches_one_incidental_term(index: Index):
    """The gate must see "no material", even though "轴承" does appear once.

    Real finding from the first run: a score ratio called this 0.47 confident,
    because conversational filler inflated the denominator. Counting matched
    distinct terms separates it cleanly (1 vs 3+).
    """

    stats = index.query_stats("这台泵的轴承型号是多少")
    assert stats.matched_terms == 1
    assert stats.matched_mass < 2.5


def test_relevant_query_matches_enough_terms(index: Index):
    stats = index.query_stats("滤芯压差多少要换")
    assert stats.matched_terms >= 2
    assert stats.matched_mass >= 2.5


def test_query_with_no_corpus_overlap(index: Index):
    stats = index.query_stats("今天天气怎么样")
    assert stats.matched_terms == 0
    assert index.search("今天天气怎么样", top_k=5) == []


def test_section_field_carries_weight(index: Index):
    # "故障代码" only appears in the section title of the E05 chunk.
    hits = index.search("故障代码", top_k=3)
    assert hits[0].chunk.chunk_id == "AX300#p87#s53#c01"
    assert hits[0].parts["section"] > 0


def test_doc_type_filter(index: Index):
    assert index.search("排气温度", top_k=5, doc_type="standard") == []


def test_rrf_merges_rankings():
    a = ["x", "y", "z"]
    b = ["y", "x", "w"]
    fused = dict(rrf([a, b]))
    assert fused["y"] > fused["z"]
    assert fused["x"] == pytest.approx(fused["y"])


def test_empty_query_returns_nothing(index: Index):
    assert index.search("", top_k=5) == []
    assert index.normalised_top1("", []) == 0.0
