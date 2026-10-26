"""Core data contracts shared by every domain.

These are the only types that cross the core/domain boundary. If a domain
wants to hand data back to the core, it must do it through ToolResult so that
citations travel with the data. That is what makes "no unsourced claim" a type
constraint instead of a prompt instruction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

CitationKind = Literal["manual", "ticket", "sensor", "standard", "internal", "rule"]
RefusalKind = Literal["safety_blocked", "insufficient_evidence"]
Confidence = Literal["high", "low"]


@dataclass(frozen=True)
class Chunk:
    """A retrievable unit of text with stable provenance."""

    chunk_id: str
    doc_id: str
    doc_title: str
    text: str
    page: int | None = None
    section: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def cite(self, snippet_len: int = 300) -> "Citation":
        snippet = self.text[:snippet_len]
        if len(self.text) > snippet_len:
            snippet += "…"
        kind = "standard" if self.meta.get("doc_type") == "standard" else (
            "internal" if self.meta.get("doc_type") == "internal" else "manual"
        )
        return Citation(
            chunk_id=self.chunk_id,
            doc_title=self.doc_title,
            page=self.page,
            section=self.section,
            snippet=snippet,
            kind=kind,
        )


@dataclass(frozen=True)
class Citation:
    chunk_id: str
    doc_title: str
    page: int | None = None
    section: str | None = None
    snippet: str = ""
    kind: CitationKind = "manual"
    score: float = 0.0


@dataclass(frozen=True)
class EvidenceStats:
    """How much of the question the knowledge base could speak to.

    Produced by whichever tool did the primary retrieval. The core gates on these
    numbers without knowing what the domain indexes, which is why they are part
    of the contract rather than a domain-private detail.
    """

    matched_terms: int
    matched_mass: float
    hit_count: int
    unknowns: tuple[str, ...] = ()


@dataclass
class ToolResult:
    """Every tool must return this. `citations` may be empty, but it must exist.

    An empty list means "this tool produced no evidence", which the core reads as
    "this step cannot support any claim". Domains cannot bypass that check.
    """

    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    citations: list[Citation] = field(default_factory=list)
    elapsed_ms: int = 0
    error: str | None = None
    evidence: EvidenceStats | None = None
    note: str = ""


@dataclass
class TraceStep:
    step: int
    tool: str | None
    args: dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    elapsed_ms: int = 0
    hit_chunk_ids: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "tool": self.tool,
            "args": self.args,
            "ok": self.ok,
            "elapsed_ms": self.elapsed_ms,
            "hit_chunk_ids": self.hit_chunk_ids,
            "note": self.note,
        }


@dataclass
class Claim:
    """One sentence of the answer, with the evidence it stands on."""

    text: str
    citation_ids: list[str] = field(default_factory=list)
    confidence: Confidence = "high"


@dataclass
class Refusal:
    kind: RefusalKind
    reason: str
    missing: list[str] = field(default_factory=list)
    action: str = "转人工"


@dataclass
class Answer:
    text: str
    claims: list[Claim] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    refusal: Refusal | None = None
    confidence: Confidence = "high"
