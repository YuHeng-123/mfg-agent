from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.rag.loader import load_pdf

ROOT = Path(__file__).resolve().parent.parent
MAN = ROOT / "data" / "equipment" / "manuals" / "AX300_manual.pdf"


@pytest.fixture(scope="module")
def chunks():
    return load_pdf(
        MAN,
        {
            "doc_id": "AX300_manual",
            "doc_title": "AX300 螺杆空压机 使用与维护手册",
            "model_id": "AX300",
            "doc_type": "manual",
        },
    )


def test_extracts_chunks_with_page_and_section(chunks):
    assert len(chunks) > 10
    assert all(c.page and c.section for c in chunks)


def test_section_titles_are_clean(chunks):
    for c in chunks:
        assert not c.section.startswith("第"), c.section
        assert re.match(r"\d+(\.\d+)+", c.section), c.section


def test_no_running_header_or_footer_leaks(chunks):
    for c in chunks:
        assert "使用与维护手册" not in c.text[:20]
        assert not re.match(r"^第\s*\d+\s*页", c.text)
        assert "共 5 页" not in c.text


def test_e05_content_is_present(chunks):
    joined = "\n".join(c.text for c in chunks)
    assert "E05" in joined
    assert "冷却水" in joined
    assert "0.15" in joined


def test_table_rows_are_rebuilt(chunks):
    joined = "\n".join(c.text for c in chunks if " | " in c.text)
    assert joined, "no table survived extraction"
    assert "E05 | 排气温度过高" in joined, joined[:200]
    assert "E01 | 排气压力过高" in joined


def test_chunk_ids_are_unique(chunks):
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
