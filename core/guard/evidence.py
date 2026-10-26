"""Evidence gate: did the knowledge base have anything to say?

The numbers used here were measured, not guessed. On the sample corpus a real
question matched 3-6 distinct terms with an IDF mass above 3.6, while "这台泵的
轴承型号是多少" matched a single incidental term ("轴承" appears once in an
unrelated paragraph). The gate is therefore a count and a mass, not a score
ratio — the first version of this file used a ratio and called that case 0.47
confident, which is how the design got corrected.

Thresholds live in settings and are quoted in every report.
"""

from __future__ import annotations

from core.config import settings
from core.types import EvidenceStats, Refusal


def gate(evidence: EvidenceStats | None, question: str) -> Refusal | None:
    if evidence is None:
        return Refusal(
            kind="insufficient_evidence",
            reason="检索未返回可用结果",
            missing=["未在主检索中获得任何片段"],
            action="建议转人工或补充设备信息",
        )

    if evidence.unknowns:
        missing = [f"知识库未收录：{u}" for u in evidence.unknowns]
        return Refusal(
            kind="insufficient_evidence",
            reason="问题涉及知识库未收录的对象",
            missing=missing,
            action="建议查设备铭牌、订货资料或转设备科确认",
        )

    if evidence.hit_count < settings.evidence_min_hits:
        return Refusal(
            kind="insufficient_evidence",
            reason=f"命中片段不足（{evidence.hit_count} < {settings.evidence_min_hits}）",
            missing=["主检索命中片段过少，不足以支撑结论"],
            action="建议补充现象描述或转人工",
        )

    if (
        evidence.matched_terms < settings.evidence_min_terms
        or evidence.matched_mass < settings.evidence_min_mass
    ):
        return Refusal(
            kind="insufficient_evidence",
            reason=(
                f"关键内容覆盖不足（命中词 {evidence.matched_terms} 个 / 阈值 {settings.evidence_min_terms}，"
                f"信息量 {evidence.matched_mass} / 阈值 {settings.evidence_min_mass}）"
            ),
            missing=["知识库未收录该问题的关键内容（型号、规格或部件信息）"],
            action="建议查设备铭牌、订货资料或转设备科确认",
        )

    return None
