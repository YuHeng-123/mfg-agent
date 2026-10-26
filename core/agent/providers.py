"""Two providers behind one protocol.

StubProvider assembles claims from the evidence the tools already returned. It is
deterministic, needs no network and no key, and exists so that the evaluation
report can be reproduced on a machine with no internet. Its answers are template
assembly, not model output, and every surface says so.

OpenAICompatProvider talks to any OpenAI-compatible endpoint. It is asked for
strict JSON, and if the JSON does not parse we return no claims at all — the
citation gate then refuses the answer. Failing closed is the whole point: a
provider that improvises when it cannot cite must never reach the user.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from core.config import settings
from core.types import Citation, Claim, ToolResult

CLAIM_LIMIT = 5
SUPPORT_LIMIT = 3
SENTENCE_END = re.compile(r"(?<=[。；;！!？?])")


class Provider(Protocol):
    name: str

    def generate(
        self,
        question: str,
        profile: dict[str, str],
        tool_outputs: list[tuple[str, ToolResult]],
        findings: list[dict] | None = None,
    ) -> tuple[str, list[Claim]]: ...


def _first_sentence(text: str) -> str:
    parts = [p.strip() for p in SENTENCE_END.split(text) if p.strip()]
    return parts[0] if parts else text.strip()


def _row_for(snippet: str, question: str) -> str:
    """A rebuilt table is many rows at once; keep the row the question is about."""

    rows = [r for r in snippet.splitlines() if "|" in r or "｜" in r]
    if not rows:
        return snippet
    body = rows[1:] or rows  # skip the header row
    scored = [
        (sum(1 for i in range(len(question) - 1) if question[i : i + 2] in row), row)
        for row in body
    ]
    best_overlap, best_row = max(scored, key=lambda pair: pair[0])
    return best_row if best_overlap else body[0]


def _clean(text: str) -> str:
    return text.replace("\n", " ").replace("|", "｜").strip()


class StubProvider:
    name = "stub"

    def generate(
        self,
        question: str,
        profile: dict[str, str],
        tool_outputs: list[tuple[str, ToolResult]],
        findings: list[dict] | None = None,
    ) -> tuple[str, list[Claim]]:
        documents: list[Citation] = []
        measured: list[Citation] = []
        history: list[Citation] = []

        for _, result in tool_outputs:
            for cite in result.citations:
                if cite.kind in ("manual", "standard", "internal"):
                    documents.append(cite)
                elif cite.kind == "sensor":
                    measured.append(cite)
                else:
                    history.append(cite)

        # Rank by retrieval score, then drop anything that is far behind the best
        # hit. Without this the builder happily cites a paragraph that shares one
        # common word with the question - which is how a heat-exchanger warning
        # ended up in an air-compressor answer during the first eval run.
        documents.sort(key=lambda c: -c.score)
        if documents and documents[0].score > 0:
            cut = documents[0].score * settings.support_score_ratio
            documents = [c for c in documents if c.score >= cut] or documents[:1]

        # If the question names a code (E05, P04, 7.1.6), the paragraph about
        # that code is the relevant one - neighbours that merely share a word
        # with the question are noise once you are writing sentences.
        codes = re.findall(r"[A-Z]{1,2}\d{2,3}|\d+\.\d+\.\d+", question.upper())
        if codes:
            # Prefer the paragraph whose *title* is about that code. A parameter
            # table can mention "E05" in passing; it is not the answer.
            in_title = [
                c for c in documents if any(code in (c.section or "").upper() for code in codes)
            ]
            in_body = [c for c in documents if any(code in c.snippet.upper() for code in codes)]
            if settings.support_code_mode == "prefer" and in_title:
                # Reorder, do not drop: on a multi-hop question the spare-part
                # table is a legitimate second half of the answer, and dropping
                # every paragraph outside the code section throws it away.
                rest = [c for c in documents if c not in in_title]
                documents = in_title + rest
            else:
                documents = in_title or in_body or documents

        # A tool can cite the same paragraph once per finding; dedupe before
        # anyone turns it into a sentence.
        seen: set[str] = set()
        unique_docs: list[Citation] = []
        for cite in documents:
            if cite.chunk_id in seen:
                continue
            seen.add(cite.chunk_id)
            unique_docs.append(cite)
        documents = unique_docs

        claims: list[Claim] = []

        # A tool may already know the conclusion (a gap, a suspected cause) and
        # hand over a ready sentence with its citations. Those go first: they are
        # the answer, the surrounding paragraphs are the support.
        for finding in findings or []:
            text = str(finding.get("text", "")).strip()
            ids = [str(i) for i in finding.get("citation_ids", []) if i]
            if text and ids:
                claims.append(Claim(text=text, citation_ids=ids, confidence="high"))

        already = {cid for claim in claims for cid in claim.citation_ids}
        support = [c for c in documents if c.chunk_id not in already][:SUPPORT_LIMIT]
        for cite in support:
            snippet = _row_for(cite.snippet, question)
            body = _first_sentence(_clean(snippet))[:100]
            where = cite.section or (f"第 {cite.page} 页" if cite.page else "原文")
            claims.append(
                Claim(text=f"{body}（{where}）", citation_ids=[cite.chunk_id], confidence="high")
            )

        for cite in measured[:1]:
            claims.append(
                Claim(
                    text=f"当前实测：{_clean(cite.snippet)}，已与设备档案阈值比对。",
                    citation_ids=[cite.chunk_id],
                    confidence="high",
                )
            )

        if history:
            ids = [c.chunk_id for c in history]
            latest = _clean(history[0].snippet)
            claims.append(
                Claim(
                    text=f"同故障码历史工单 {len(history)} 条，最近一条处置为「{latest}」。",
                    citation_ids=ids,
                    confidence="high",
                )
            )

        claims = claims[:CLAIM_LIMIT]
        if not claims:
            return "", []

        lines = [f"{i}. {c.text}" for i, c in enumerate(claims, start=1)]
        header = profile.get("answer_shape", "")
        text = "\n".join(lines)
        if header:
            text = f"{text}\n\n（{header}；stub 模式为模板拼装，不代表模型能力）"
        return text, claims


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(self) -> None:
        self.model = settings.model_name
        self.base_url = settings.base_url.rstrip("/")
        self.api_key = settings.api_key

    def generate(
        self,
        question: str,
        profile: dict[str, str],
        tool_outputs: list[tuple[str, ToolResult]],
        findings: list[dict] | None = None,
    ) -> tuple[str, list[Claim]]:
        import httpx

        evidence = []
        for tool_name, result in tool_outputs:
            for cite in result.citations:
                evidence.append(
                    {
                        "chunk_id": cite.chunk_id,
                        "source": cite.doc_title,
                        "page": cite.page,
                        "section": cite.section,
                        "text": _clean(cite.snippet)[:220],
                        "kind": cite.kind,
                    }
                )

        system = (
            "你是工业现场的辅助助手。只能使用给定的证据回答，禁止补充证据以外的任何数字、"
            "型号或步骤。每条结论必须标注它依据的 chunk_id。若证据不足以回答，返回空 claims。"
            '只输出 JSON：{"claims":[{"text":"...","citation_ids":["..."]}]}'
        )
        user = json.dumps(
            {
                "question": question,
                "answer_shape": profile.get("answer_shape", ""),
                "tool_findings": findings or [],
                "evidence": evidence,
            },
            ensure_ascii=False,
        )

        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
                timeout=45.0,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            payload = json.loads(content)
        except Exception:
            return "", []

        claims: list[Claim] = []
        for raw in payload.get("claims", [])[:CLAIM_LIMIT]:
            text = str(raw.get("text", "")).strip()
            ids = [str(i) for i in raw.get("citation_ids", [])]
            if text:
                claims.append(Claim(text=text, citation_ids=ids))

        if not claims:
            return "", []
        return "\n".join(f"{i}. {c.text}" for i, c in enumerate(claims, start=1)), claims


def get_provider(name: str | None = None) -> Provider:
    chosen = (name or settings.provider).lower()
    if chosen in ("openai", "openai_compat", "real") and settings.real_provider_ready:
        return OpenAICompatProvider()
    return StubProvider()
