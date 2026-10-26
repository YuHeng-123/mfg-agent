"""Citation gate: every claim must stand on a chunk_id this run actually touched.

The allowed set is built from what the tools returned, nothing else. A claim that
cites something we never retrieved, or cites nothing at all, is downgraded to low
confidence. If no claim survives, the whole answer becomes a refusal — the system
would rather say "I don't know" than hand a technician an untraceable instruction.
"""

from __future__ import annotations

from core.types import Claim, Refusal, ToolResult


def allowed_ids(tool_outputs: list[tuple[str, ToolResult]]) -> set[str]:
    ids: set[str] = set()
    for _, result in tool_outputs:
        for cite in result.citations:
            ids.add(cite.chunk_id)
    return ids


def verify(
    claims: list[Claim], tool_outputs: list[tuple[str, ToolResult]]
) -> tuple[list[Claim], list[str], Refusal | None]:
    allowed = allowed_ids(tool_outputs)
    kept: list[Claim] = []
    rejected: list[str] = []

    for claim in claims:
        cited = set(claim.citation_ids)
        if cited and cited <= allowed:
            kept.append(claim)
        else:
            rejected.append(" ".join(claim.citation_ids) or f"(no citation) {claim.text[:24]}")
            claim.confidence = "low"
            claim.citation_ids = []
            kept.append(claim)

    if not any(c.confidence == "high" for c in kept):
        return (
            kept,
            rejected,
            Refusal(
                kind="insufficient_evidence",
                reason=f"生成内容无法回溯到已检索的原文（{len(rejected)} 条引用未通过校验）",
                missing=["所有结论均缺少可核对的出处"],
                action="建议转人工，勿直接执行",
            ),
        )
    return kept, rejected, None
