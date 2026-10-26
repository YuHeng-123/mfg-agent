"""Data access for the compliance domain: one standard excerpt, five internal docs."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache

from core.config import DATA_DIR
from core.rag.index import Index
from core.rag.loader import load_markdown
from core.store import records
from core.types import Chunk

CP = DATA_DIR / "compliance"
STANDARD_DIR = CP / "standards"
INTERNAL_DIR = CP / "internal"

STANDARD_META = {
    "GB19001-2026_excerpt": {
        "doc_title": "GB/T 19001—2026 质量管理体系 要求（节选）",
        "doc_type": "standard",
    }
}

INTERNAL_META = {
    "quality_manual": {"doc_title": "质量手册（节选）"},
    "inspection_procedure": {"doc_title": "检验规程（节选）"},
    "work_instruction": {"doc_title": "复配岗位作业指导书（节选）"},
    "training_material": {"doc_title": "岗位培训教材（节选）"},
    "record_form": {"doc_title": "记录表单清单（节选）"},
}


@lru_cache(maxsize=1)
def chunks() -> tuple[Chunk, ...]:
    out: list[Chunk] = []

    for stem, meta in STANDARD_META.items():
        path = STANDARD_DIR / f"{stem}.md"
        if path.is_file():
            out.extend(
                load_markdown(
                    path,
                    {
                        "doc_id": stem,
                        "doc_title": meta["doc_title"],
                        "doc_type": "standard",
                        "clause": stem,
                    },
                )
            )

    for stem, meta in INTERNAL_META.items():
        path = INTERNAL_DIR / f"{stem}.md"
        if path.is_file():
            out.extend(
                load_markdown(
                    path,
                    {"doc_id": stem, "doc_title": meta["doc_title"], "doc_type": "internal"},
                )
            )
    return tuple(out)


@lru_cache(maxsize=1)
def index() -> Index:
    return Index(list(chunks()))


def record_gap(payload: dict) -> dict:
    """Same write side as a ticket: drafted by the agent, signed by a human."""

    row = {
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        **payload,
    }
    return records.create("gap", ref=str(payload.get("gap_id", "")), payload=row)


def recorded(status: str | None = None, include_drafts: bool = True) -> list[dict]:
    return records.list_records(
        kind="gap", status=status, include_drafts=include_drafts, limit=50
    )


def clause_chunk(section_hint: str) -> Chunk | None:
    for chunk in chunks():
        if chunk.meta.get("doc_type") == "standard" and chunk.section and section_hint in chunk.section:
            return chunk
    return None


def doc_chunk(doc_title_prefix: str, section_hint: str = "") -> Chunk | None:
    """Prefer the chunk inside the named document that the gap actually points at."""

    candidates = [
        c
        for c in chunks()
        if c.meta.get("doc_type") == "internal" and doc_title_prefix in c.doc_title
    ]
    if section_hint:
        for chunk in candidates:
            if chunk.section and section_hint in chunk.section:
                return chunk
    return candidates[0] if candidates else None
