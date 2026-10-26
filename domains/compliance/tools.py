"""The four compliance tools.

`check_gaps` is the interesting one: it runs the deterministic coverage rules and
returns the uncovered clauses together with the clause text they violate. The
model never decides whether a gap exists - it only gets to phrase the finding.
"""

from __future__ import annotations

import dataclasses
import functools
import re
import time

from core.rag.tokenize import tokenize
from core.types import Citation, EvidenceStats, ToolResult
from domains.compliance import requirements as cov
from domains.compliance.rules import OUT_OF_SCOPE
from domains.compliance import store

# Gap findings must outrank ordinary retrieval hits in the answer, because that is
# what the user asked for. Scores are internal ranking only, never shown.
GAP_CLAUSE_SCORE = 100.0
GAP_DOC_SCORE = 90.0


def _timed(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> ToolResult:
        started = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    return wrapper


@_timed
def search_standard(query: str, top_k: int = 5) -> ToolResult:
    ix = store.index()
    hits = ix.search(query, top_k=top_k, doc_type="standard")
    stats = ix.query_stats(query)
    unknowns = [label for pattern, label in OUT_OF_SCOPE if re.search(pattern, query)]
    citations = [dataclasses.replace(h.chunk.cite(), score=round(h.score, 4)) for h in hits]
    return ToolResult(
        ok=bool(hits),
        data={
            "hits": [
                {
                    "chunk_id": h.chunk.chunk_id,
                    "section": h.chunk.section,
                    "score": round(h.score, 3),
                    "text": h.chunk.text[:300],
                }
                for h in hits
            ],
            "query_stats": {
                "matched_terms": stats.matched_terms,
                "matched_mass": stats.matched_mass,
            },
        },
        citations=citations,
        evidence=EvidenceStats(
            matched_terms=stats.matched_terms,
            matched_mass=stats.matched_mass,
            hit_count=len(hits) if not unknowns else 0,
            unknowns=tuple(unknowns),
        ),
        note=f"条款命中 {len(hits)} 条" + (f"，超出范围：{unknowns}" if unknowns else ""),
    )


@_timed
def search_internal_doc(query: str, top_k: int = 5) -> ToolResult:
    ix = store.index()
    hits = ix.search(query, top_k=top_k, doc_type="internal")
    stats = ix.query_stats(query)
    citations = [dataclasses.replace(h.chunk.cite(), score=round(h.score, 4)) for h in hits]
    return ToolResult(
        ok=bool(hits),
        data={
            "hits": [
                {
                    "chunk_id": h.chunk.chunk_id,
                    "doc_title": h.chunk.doc_title,
                    "section": h.chunk.section,
                    "score": round(h.score, 3),
                }
                for h in hits
            ]
        },
        citations=citations,
        evidence=EvidenceStats(
            matched_terms=stats.matched_terms,
            matched_mass=stats.matched_mass,
            hit_count=len(hits),
        ),
        note=f"厂内文件命中 {len(hits)} 处",
    )


def _narrow(gaps: list, query: str) -> list:
    """Keep only the gaps this question is actually about.

    First by clause number if one is named, otherwise by term overlap with the
    clause title, the advice text and the required words. Without this the tool
    dumps the entire register on every question, which produced 56 false
    positives on the first compliance run.
    """

    codes = re.findall(r"\d+\.\d+(?:\.\d+)?", query)
    if codes:
        picked = [
            g for g in gaps if any(g.clause_id.startswith(c) or c.startswith(g.clause_id) for c in codes)
        ]
        if picked:
            return picked

    tokens = set(tokenize(query))
    scored = []
    for gap in gaps:
        text = f"{gap.clause_section}{gap.advice}{gap.target_doc}{''.join(gap.required)}"
        scored.append((sum(1 for t in tokens if t in text), gap))
    best = max((score for score, _ in scored), default=0)
    if best <= 0:
        return []
    cutoff = max(2, int(best * 0.6))
    return [gap for score, gap in scored if score >= cutoff]


@_timed
def check_gaps(query: str = "", only_uncovered: bool = True) -> ToolResult:
    """Run the clause coverage rules and return the gaps relevant to the question."""

    results = cov.evaluate(list(store.chunks()))
    if only_uncovered:
        results = [r for r in results if not r.covered]

    results = _narrow(results, query)
    codes = re.findall(r"\d+\.\d+(?:\.\d+)?", query)

    citations: list[Citation] = []
    payload: list[dict] = []
    for gap in results:
        clause = store.clause_chunk(gap.clause_section.split(" ")[0])
        if clause:
            citations.append(dataclasses.replace(clause.cite(160), score=GAP_CLAUSE_SCORE))
        if gap.target_doc and gap.target_doc != "（缺失）":
            doc = store.doc_chunk(gap.target_doc, gap.target_section)
            if doc:
                citations.append(dataclasses.replace(doc.cite(200), score=GAP_DOC_SCORE))
        ids = []
        if clause:
            ids.append(clause.chunk_id)
        if gap.target_doc and gap.target_doc != "（缺失）":
            doc = store.doc_chunk(gap.target_doc, gap.target_section)
            if doc:
                ids.append(doc.chunk_id)
        payload.append(
            {
                "gap_id": gap.gap_id,
                "clause_id": gap.clause_id,
                "kind": gap.kind,
                "target_doc": gap.target_doc,
                "advice": gap.advice,
                "clause_chunk": clause.chunk_id if clause else None,
                "text": f"{gap.gap_id}（{gap.clause_id}）{gap.advice}",
                "citation_ids": ids,
            }
        )

    return ToolResult(
        ok=bool(payload),
        data={"gaps": payload, "findings": payload, "count": len(payload)},
        citations=citations,
        note=f"{len(payload)} 项差距" + (f"（条款 {'、'.join(codes)}）" if codes else ""),
        error=None if payload else "未发现差距",
    )


@_timed
def record_gap(gap_id: str, clause_id: str = "", target_doc: str = "", note: str = "") -> ToolResult:
    row = store.record_gap(
        {"gap_id": gap_id, "clause_id": clause_id, "target_doc": target_doc, "note": note}
    )
    return ToolResult(ok=True, data={"recorded": row}, citations=[], note="差距项已记入草稿")


TOOLS = {
    "search_standard": {
        "fn": search_standard,
        "description": "检索新版标准的条款原文，返回条款号与正文。",
        "read_only": True,
        "parallel_safe": True,
        "primary": True,
        "trigger": None,
    },
    "search_internal_doc": {
        "fn": search_internal_doc,
        "description": "检索厂内现有体系文件（质量手册、检验规程、作业指导书、培训教材、表单）。",
        "read_only": True,
        "parallel_safe": True,
        # Always run: this domain compares two corpora, so both sides are needed
        # on every question, not only when the wording happens to mention a doc.
        "primary": True,
        "trigger": None,
    },
    "check_gaps": {
        "fn": check_gaps,
        "description": "按条款覆盖规则比对厂内文件，列出未覆盖的差距项。",
        "read_only": True,
        "parallel_safe": True,
        "primary": False,
        "trigger": r"(差距|改哪|影响|符合|对照|缺|覆盖|换版|新增)",
    },
    "record_gap": {
        "fn": record_gap,
        "description": "把一条差距写入差距清单草稿，须人工确认后定稿。",
        "read_only": False,
        "parallel_safe": False,
        "primary": False,
        "trigger": None,
    },
}
