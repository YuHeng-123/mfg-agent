"""The agent loop: plan, run tools in parallel, gate, generate, verify, trace.

Six steps maximum, a whitelist of tools per domain, a per-tool timeout that does
not abort the run, and one trace record per step. The loop is deliberately small:
everything expensive or domain-specific lives behind the Domain protocol, so a
reviewer can read this file in two minutes and see there is no hidden magic.
"""

from __future__ import annotations

import inspect
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace

from core.agent.providers import get_provider
from core.config import settings
from core.guard import citation as citation_guard
from core.guard import evidence as evidence_guard
from core.guard import safety as safety_guard
from core.guard.safety import SafetyHit
from core.types import Answer, Citation, Refusal, ToolResult, TraceStep
from domains.base import Domain, Tool, load_domain

RE_CODE = re.compile(r"\b[A-Z]{1,2}\d{2,3}\b")
# Clause boundaries. Deliberately punctuation-level and language-agnostic: the
# core is not allowed to know that a question might contain a fault code, so it
# cannot parse "which section answers which part" either. It just splits.
RE_CLAUSE = re.compile(r"[，,；;。]|以及|另外|并且|同时|还有")
MIN_CLAUSE_LEN = 6


@dataclass
class AskResult:
    domain: str
    question: str
    answer: Answer
    trace: list[TraceStep] = field(default_factory=list)
    provider: str = "stub"
    elapsed_ms: int = 0
    findings: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "question": self.question,
            "answer": self.answer.text,
            "claims": [
                {"text": c.text, "citation_ids": c.citation_ids, "confidence": c.confidence}
                for c in self.answer.claims
            ],
            "citations": [
                {
                    "chunk_id": c.chunk_id,
                    "doc_title": c.doc_title,
                    "page": c.page,
                    "section": c.section,
                    "snippet": c.snippet,
                    "kind": c.kind,
                }
                for c in self.answer.citations
            ],
            "refusal": (
                {
                    "kind": self.answer.refusal.kind,
                    "reason": self.answer.refusal.reason,
                    "missing": self.answer.refusal.missing,
                    "action": self.answer.refusal.action,
                }
                if self.answer.refusal
                else None
            ),
            "confidence": self.answer.confidence,
            "trace": [t.to_dict() for t in self.trace],
            "provider": self.provider,
            "elapsed_ms": self.elapsed_ms,
            "findings": self.findings,
        }


def _build_args(tool: Tool, question: str, context: dict) -> dict | None:
    """Bind whatever the tool's signature accepts; skip it if something required is missing."""

    params = inspect.signature(tool.fn).parameters
    available = {
        "query": question,
        "question": question,
        "model_id": context.get("model_id"),
        "device_id": context.get("device_id"),
        "fault_code": context.get("fault_code") or _extract_code(question),
        "top_k": settings.top_k,
        "limit": 3,
        "level": "P2",
        "symptom": question,
    }
    args: dict = {}
    for name, param in params.items():
        if name in ("self", "kwargs", "args"):
            continue
        if name in available and available[name] is not None:
            args[name] = available[name]
        elif param.default is inspect.Parameter.empty:
            return None
    return args


def _extract_code(question: str) -> str | None:
    match = RE_CODE.search(question.upper())
    return match.group(0) if match else None


def _decompose(question: str) -> list[str]:
    """Split a question into clauses that can be retrieved separately.

    "AX300 报 E05 怎么处置，备件型号是什么" is two retrieval problems sharing one
    string. Ranked as one query, whichever half matches more terms wins and the
    other half never reaches the answer. Splitting costs one extra tool call per
    clause and is the reason multi-hop questions are answerable at all.
    """

    parts: list[str] = []
    for raw in RE_CLAUSE.split(question):
        clause = raw.strip()
        if len(clause) >= MIN_CLAUSE_LEN and clause not in parts:
            parts.append(clause)
    # The whole string is still retrieved once as well: the clause split is a
    # supplement, not a replacement, and tools that are not a text search
    # (sensor replay, ticket history) should still see the original question.
    return parts if len(parts) > 1 else []


def _plan(domain: Domain, question: str) -> tuple[list[Tool], str]:
    tools = domain.tools()
    primary = [t for t in tools.values() if t.primary]
    chosen = list(primary)
    reasons = []
    for tool in tools.values():
        if tool.primary or not tool.trigger or not tool.read_only:
            continue
        if re.search(tool.trigger, question):
            chosen.append(tool)
            reasons.append(tool.name)
    note = "主检索" + (f" + 触发：{','.join(reasons)}" if reasons else "（无其他触发）")
    return chosen, note


SCOPE_KEYS = ("model_id", "device_id", "fault_code")


def _scope_from(outputs: list[tuple[str, ToolResult]], tools: list[Tool]) -> dict:
    """Entity scope the primary retrieval resolved from the whole question.

    A clause is not a question. "AX300 报 E05 怎么处置，备件是什么" splits into
    "备件是什么", which names no model at all — retrieving it without the scope
    resolved from the full string searches every manual in the library and hands
    the answer an AX310 spare-part table. Clause retrieval must inherit the
    scope, not re-derive it.
    """

    primary = {t.name for t in tools if t.primary}
    scope: dict = {}
    for name, result in outputs:
        if name not in primary:
            continue
        for key in SCOPE_KEYS:
            value = (result.data or {}).get(key)
            if value and key not in scope:
                scope[key] = value
    return scope


def _run_parallel(
    jobs: list[tuple[Tool, dict, str]],
    trace: list[TraceStep],
    start_step: int,
) -> list[tuple[str, ToolResult]]:
    def work(tool: Tool, args: dict) -> ToolResult:
        if settings.tool_latency_ms:
            time.sleep(settings.tool_latency_ms / 1000)
        return tool(**args)

    outputs: list[tuple[str, ToolResult]] = []
    with ThreadPoolExecutor(max_workers=max(len(jobs), 1)) as pool:
        futures = [(tool, pool.submit(work, tool, args), note) for tool, args, note in jobs]
        for tool, future, note in futures:
            try:
                result = future.result(timeout=settings.tool_timeout_s + settings.tool_latency_ms / 1000)
            except Exception as exc:  # timeout or crash: record it, keep going
                result = ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")
            outputs.append((tool.name, result))
            suffix = result.error or result.note or ""
            trace.append(
                TraceStep(
                    step=start_step,
                    tool=tool.name,
                    args={k: v for k, v in (result.data or {}).items() if k in SCOPE_KEYS},
                    ok=result.ok,
                    elapsed_ms=result.elapsed_ms,
                    hit_chunk_ids=[c.chunk_id for c in result.citations],
                    note=f"{note}{'｜' if note and suffix else ''}{suffix}",
                )
            )
    return outputs


def _build_jobs(tools: list[Tool], question: str, context: dict, trace: list[TraceStep]) -> list[tuple[Tool, dict, str]]:
    jobs: list[tuple[Tool, dict, str]] = []
    for tool in tools:
        args = _build_args(tool, question, context)
        if args is None:
            trace.append(TraceStep(step=3, tool=tool.name, ok=False, note="参数不满足，跳过"))
            continue
        jobs.append((tool, args, ""))
    return jobs


def _collect_citations(outputs: list[tuple[str, ToolResult]]) -> list[Citation]:
    seen: dict[str, Citation] = {}
    for _, result in outputs:
        for cite in result.citations:
            seen.setdefault(cite.chunk_id, cite)
    return list(seen.values())


def ask(domain_name: str, question: str, context: dict | None = None) -> AskResult:
    started = time.perf_counter()
    context = dict(context or {})
    domain = load_domain(domain_name)
    trace: list[TraceStep] = []

    # step 1 — safety short circuit, before any retrieval or model call
    hit: SafetyHit | None = safety_guard.check(question, domain.safety_rules())
    if hit:
        trace.append(
            TraceStep(step=1, tool=None, ok=True, note=f"安全规则 {hit.rule_id} 命中，短路")
        )
        return AskResult(
            domain=domain.name,
            question=question,
            answer=Answer(
                text=f"该问题须由持证人员处理：{hit.message}。",
                refusal=hit.to_refusal(),
                confidence="high",
            ),
            trace=trace,
            provider="rules",
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    # step 2 — plan
    tools, note = _plan(domain, question)
    trace.append(TraceStep(step=2, tool=None, note=f"计划 {len(tools)} 个工具：{note}"))

    if not tools:
        refusal = Refusal(
            kind="insufficient_evidence",
            reason="该领域没有可用工具",
            missing=["无主检索工具"],
            action="转人工",
        )
        return AskResult(
            domain=domain.name,
            question=question,
            answer=Answer(text="", refusal=refusal),
            trace=trace,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    # step 3 — parallel tool execution
    outputs = _run_parallel(_build_jobs(tools, question, context, trace), trace, start_step=3)

    # step 3b — clause retrieval, in a second wave because it needs the scope
    # the first wave resolved. Only the primary retrieval is decomposed: running
    # a ticket lookup once per clause would multiply the same rows.
    if settings.decompose_clauses:
        clauses = _decompose(question)
        if clauses:
            scope = {k: v for k, v in _scope_from(outputs, tools).items() if not context.get(k)}
            ctx = {**context, **scope}
            extra: list[tuple[Tool, dict, str]] = []
            for tool in tools:
                if not (tool.primary and tool.read_only):
                    continue
                for clause in clauses:
                    args = _build_args(tool, clause, ctx)
                    if args is not None:
                        extra.append((tool, args, f"子句检索「{clause}」"))
            outputs += _run_parallel(extra, trace, start_step=3)

    # Tools may report structured findings (a gap list, a suspected cause). The
    # core does not interpret them, it only carries them to the caller.
    findings: list[dict] = []
    for _, result in outputs:
        findings.extend(result.data.get("findings", []))

    # step 4 — evidence gate, using the strongest statistics any tool produced.
    # A question can be answerable from either corpus (the standard or the house
    # documents), so gating only on the primary tool refused "客户满意度调查多久做一次"
    # even though the internal manual covered it.
    with_evidence = [(name, result.evidence) for name, result in outputs if result.evidence]
    evidence_name, evidence = (
        max(with_evidence, key=lambda pair: pair[1].matched_mass) if with_evidence else (None, None)
    )
    # Unknowns must never be dropped by picking the "best" tool: an out-of-scope
    # question can look well-covered by the wrong corpus.
    if evidence is not None:
        merged = tuple(sorted({u for _, ev in with_evidence for u in ev.unknowns}))
        # Fragments are counted across every tool: two fragments from the standard
        # plus three from the house documents is five pieces of evidence, and the
        # gate is asking whether there is enough material, not which corpus won.
        total_hits = sum(ev.hit_count for _, ev in with_evidence)
        evidence = replace(evidence, unknowns=merged or evidence.unknowns, hit_count=total_hits)
    refusal = evidence_guard.gate(evidence, question)
    if refusal:
        trace.append(
            TraceStep(step=4, tool=None, ok=True, note=f"证据闸拦截：{refusal.reason}")
        )
        return AskResult(
            domain=domain.name,
            question=question,
            answer=Answer(text="", citations=_collect_citations(outputs), refusal=refusal),
            trace=trace,
            findings=findings,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
    trace.append(
        TraceStep(
            step=4,
            tool=None,
            ok=True,
            note=(
                f"证据闸通过（{evidence_name}）：命中词 {evidence.matched_terms}，"
                f"信息量 {evidence.matched_mass}，片段 {evidence.hit_count}"
            ),
        )
    )

    # step 5 — generate
    provider = get_provider()
    profile = domain.prompt_profile()
    text, claims = provider.generate(question, profile, outputs, findings)
    trace.append(
        TraceStep(step=5, tool=None, ok=bool(claims), note=f"provider={provider.name}，生成 {len(claims)} 条结论")
    )

    if not claims:
        refusal = Refusal(
            kind="insufficient_evidence",
            reason="未生成任何可挂引用的结论",
            missing=["证据不足以支撑答复"],
            action="建议转人工",
        )
        return AskResult(
            domain=domain.name,
            question=question,
            answer=Answer(text="", citations=_collect_citations(outputs), refusal=refusal),
            trace=trace,
            findings=findings,
            provider=provider.name,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    # step 6 — citation gate
    claims, rejected, refusal = citation_guard.verify(claims, outputs)
    trace.append(
        TraceStep(
            step=6,
            tool=None,
            ok=refusal is None,
            note=f"引用校验：{len(rejected)} 条未通过" + ("，整体转为拒答" if refusal else ""),
        )
    )

    citations = _collect_citations(outputs)
    if refusal:
        return AskResult(
            domain=domain.name,
            question=question,
            answer=Answer(text="", claims=claims, citations=citations, refusal=refusal),
            trace=trace,
            findings=findings,
            provider=provider.name,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    low = [c for c in claims if c.confidence == "low"]
    answer = Answer(
        text=text,
        claims=claims,
        citations=citations,
        refusal=None,
        confidence="low" if low else "high",
    )
    return AskResult(
        domain=domain.name,
        question=question,
        answer=answer,
        trace=trace,
        provider=provider.name,
        findings=findings,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
