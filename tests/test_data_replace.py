"""数据可替换：换一本手册只该是"丢个 PDF + 写一行 JSON"。

这条不是新功能，是这个项目的核心卖点之一，之前只有口头承诺（README 写了、
`MANUAL_META` 看起来也确实好改），但没有一条测试证明它真的不用改代码。
"""

from __future__ import annotations

import json

import pymupdf
import pytest

from domains.equipment import store


@pytest.fixture
def temp_corpus(tmp_path, monkeypatch):
    """把真实手册目录指向 tmp，测完把缓存清干净，别污染后面的用例。"""

    real = tmp_path / "real"
    real.mkdir()
    monkeypatch.setattr(store, "REAL_DIR", real)
    monkeypatch.setattr(store, "REAL_META", real / "_meta.json")
    store.chunks.cache_clear()
    store.index.cache_clear()
    yield real
    store.chunks.cache_clear()
    store.index.cache_clear()


def _write_pdf(path, heading: str, body: list[str]) -> None:
    """两页：封面（抽取会跳过）+ 正文。

    章节标题要用大于等于 12.5 的字号，否则抽取器认不出这是标题，
    整页会被当成一段正文——这本身就是抽取器的规则，测试不该绕开它。
    """

    doc = pymupdf.open()
    cover = doc.new_page()
    cover.insert_text((72, 72), "TEST900 安装手册", fontname="china-s", fontsize=20)
    page = doc.new_page()
    page.insert_text((72, 72), heading, fontname="china-s", fontsize=14)
    y = 100
    for line in body:
        page.insert_text((72, y), line, fontname="china-s", fontsize=11)
        y += 18
    doc.save(str(path))
    doc.close()


def test_a_new_manual_is_a_file_plus_one_json_line(temp_corpus):
    baseline = len(store.chunks())

    _write_pdf(temp_corpus / "TEST900_manual.pdf", "8.1 过载跳闸", ["现象：输出电流超过额定值。"])
    (temp_corpus / "_meta.json").write_text(
        json.dumps({"TEST900_manual": {"doc_title": "TEST900 测试手册", "model_id": "TEST900"}}),
        encoding="utf-8",
    )
    # 索引是缓存过的：加了文件必须显式失效，否则读到的是旧快照。
    # 生产环境这条由管理员的 reload 接口负责，不是"自动就生效"。
    store.chunks.cache_clear()
    store.index.cache_clear()

    chunks = store.chunks()
    added = [c for c in chunks if c.chunk_id.startswith("TEST900_manual#")]
    assert added, "丢进 real/ 并登记后，索引里应该出现这本手册"
    assert len(chunks) > baseline

    # 型号过滤立刻可用：不需要任何代码改动
    hits = store.index().search("过载跳闸怎么处理", top_k=3, model_id="TEST900")
    assert hits and all(h.chunk.meta.get("model_id") == "TEST900" for h in hits)


def test_unregistered_pdf_is_ignored(temp_corpus):
    """只丢 PDF 不登记，不该悄悄进索引——否则没人说得清这堆引用从哪来。"""

    baseline = len(store.chunks())
    _write_pdf(temp_corpus / "GHOST_manual.pdf", "9.1 未登记的手册", ["这段不该被检索到。"])
    assert len(store.chunks()) == baseline


def test_missing_meta_file_is_not_an_error(temp_corpus):
    assert store.real_meta() == {}
    assert store.manual_meta()  # 合成那部分照常可用
    assert store.manual_path("AX300_manual") is not None
    assert store.manual_path("NO_SUCH_MODEL") is None
