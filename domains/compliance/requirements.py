"""Clause requirements: the deterministic half of the compliance domain.

Each rule says: clause X requires the organisation to have *these* words in one
documented place. Coverage is then a substring check over the internal documents.

Why so crude: a gap analysis that leans on a model's opinion is unauditable. An
assessor asks "why do you say this is missing", and "no document in your set
contains the phrase 更改控制" is an answer they can verify in ten seconds. The
model's job is the language around the finding, not the finding itself.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClauseReq:
    gap_id: str
    clause_id: str
    clause_section: str          # section title of the clause chunk
    required: tuple[str, ...]    # all of these must co-occur in one internal chunk
    kind: str                    # missing_section | missing_doc | outdated_term
    target_doc: str              # where a fix would go
    advice: str
    target_section: str = ""     # section inside that doc, for a precise citation


REQUIREMENTS: list[ClauseReq] = [
    ClauseReq(
        "G-01",
        "7.1.6-a",
        "7.1.6 组织知识",
        ("知识", "来源", "更新"),
        "missing_section",
        "质量手册",
        "质量手册 §4.2.3 只写了经验积累，未规定知识的来源与更新方式",
        "4.2.3",
    ),
    ClauseReq(
        "G-02",
        "7.1.6-b",
        "7.1.6 组织知识",
        ("经验", "流失"),
        "missing_section",
        "培训教材",
        "培训教材 §3 未覆盖经验流失风险及应对措施",
        "3 岗位培训",
    ),
    ClauseReq(
        "G-03",
        "6.3",
        "6.3 变更的策划",
        ("变更", "影响评估"),
        "missing_section",
        "质量手册",
        "质量手册 §7.5 文件控制未包含变更影响评估要求",
        "7.5 文件控制",
    ),
    ClauseReq(
        "G-04",
        "7.5.3",
        "7.5.3 成文信息的控制",
        ("版本", "更改控制"),
        "missing_section",
        "质量手册",
        "质量手册 §7.5 缺版本控制与更改控制条款",
        "7.5 文件控制",
    ),
    ClauseReq(
        "G-05",
        "10.2",
        "10.2 不合格和纠正措施",
        ("不合格", "原因", "纠正措施"),
        "missing_section",
        "检验规程",
        "检验规程 §6 只写到隔离与处置，未要求原因分析与纠正措施",
        "6 不合格品处置",
    ),
    ClauseReq(
        "G-06",
        "7.1.6",
        "7.1.6 组织知识",
        ("知识管理程序",),
        "missing_doc",
        "（缺失）",
        "厂内未收录《组织知识管理程序》，条款整体无对应程序文件",
    ),
    ClauseReq(
        "G-07",
        "5.1.1",
        "5.1.1 领导作用与承诺",
        ("质量文化",),
        "missing_doc",
        "（缺失）",
        "未见质量文化相关证据文件（沟通记录、激励与约束机制）",
    ),
]


@dataclass(frozen=True)
class Coverage:
    gap_id: str
    clause_id: str
    clause_section: str
    kind: str
    target_doc: str
    advice: str
    target_section: str
    required: tuple[str, ...]
    covered: bool
    evidence_doc: str | None = None
    evidence_snippet: str | None = None


def evaluate(chunks) -> list[Coverage]:
    """Walk every rule against the internal document chunks."""

    results: list[Coverage] = []
    internal = [c for c in chunks if c.meta.get("doc_type") == "internal"]

    for req in REQUIREMENTS:
        hit = None
        for chunk in internal:
            text = chunk.text.replace(" ", "")
            if all(term.replace(" ", "") in text for term in req.required):
                hit = chunk
                break
        results.append(
            Coverage(
                gap_id=req.gap_id,
                clause_id=req.clause_id,
                clause_section=req.clause_section,
                kind=req.kind,
                target_doc=req.target_doc,
                advice=req.advice,
                target_section=req.target_section,
                required=req.required,
                covered=hit is not None,
                evidence_doc=hit.doc_title if hit else None,
                evidence_snippet=(hit.text[:160] if hit else None),
            )
        )
    return results
