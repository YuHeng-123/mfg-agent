"""Ablation: switch each guard off, measure what it was holding back.

Why this exists: with no API key we cannot compare model quality, and pretending
otherwise would be dishonest. But the interesting claim was never "our model is
good" - it is "these three mechanisms are doing work". That claim can be tested
offline, by removing one mechanism at a time and watching the numbers move.

Three switches:
  citation_gate   off -> claims that cite nothing reach the user
  evidence_gate   off -> questions with no material get answered anyway
  model_filter    off -> paragraphs from another machine's manual get cited

Run:  python scripts/ablation.py
Out:  console table + evals/reports/ablation_<commit>.json
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.agent import loop  # noqa: E402
from core.types import Claim  # noqa: E402
from core.guard import citation as citation_guard  # noqa: E402
from core.guard import evidence as evidence_guard  # noqa: E402
from domains.equipment import store as eq_store  # noqa: E402

DATASETS = {
    "equipment": ROOT / "evals" / "equipment.jsonl",
    "compliance": ROOT / "evals" / "compliance.jsonl",
}


def load(domain: str) -> list[dict]:
    path = DATASETS[domain]
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@contextmanager
def citation_off():
    original = citation_guard.verify

    def passthrough(claims, tool_outputs):
        return claims, [], None

    loop.citation_guard.verify = passthrough
    try:
        yield
    finally:
        loop.citation_guard.verify = original


@contextmanager
def evidence_off():
    original = evidence_guard.gate

    def passthrough(evidence, question):
        return None

    loop.evidence_guard.gate = passthrough
    try:
        yield
    finally:
        loop.evidence_guard.gate = original


@contextmanager
def model_filter_off():
    m_model = eq_store.resolve_model
    m_models = eq_store.resolve_models
    eq_store.resolve_model = lambda *a, **k: None
    eq_store.resolve_models = lambda *a, **k: None
    try:
        yield
    finally:
        eq_store.resolve_model = m_model
        eq_store.resolve_models = m_models


class FabricatingProvider:
    """A model that writes confidently and makes up its citations.

    We cannot call a real model without a key, but we can absolutely simulate the
    failure mode this architecture exists to stop. The claims below are plausible
    shop-floor sentences whose citations do not exist.
    """

    name = "fabricating"

    def generate(self, question, profile, tool_outputs, findings=None):
        claims = [
            Claim(text="该型号轴承为 6308-2Z，复紧力矩 210 N·m。", citation_ids=["FAKE#p99#s99#c01"]),
            Claim(text="滤芯更换周期为 500 小时。", citation_ids=["FAKE#p98#s98#c02"]),
        ]
        return "\n".join(f"{i}. {c.text}" for i, c in enumerate(claims, 1)), claims


@contextmanager
def provider_fabricating():
    original = loop.get_provider
    loop.get_provider = lambda *a, **k: FabricatingProvider()
    try:
        yield
    finally:
        loop.get_provider = original


def chunk_models() -> dict[str, str]:
    return {c.chunk_id: c.meta.get("model_id") for c in eq_store.chunks() if c.meta.get("model_id")}


@contextmanager
def _chain(*ctxs):
    [c.__enter__() for c in ctxs]
    try:
        yield
    finally:
        for c in reversed(ctxs):
            c.__exit__(None, None, None)


def run_case(name: str, ctx) -> dict:
    models = chunk_models()
    answered_when_refused = refused_when_answerable = 0
    refuse_total = answerable_total = 0
    claims_total = unsourced = fabricated = 0
    doc_cites = wrong_model = 0

    for domain, items in (("equipment", load("equipment")), ("compliance", load("compliance"))):
        for item in items:
            expect_refuse = item["type"] in ("refuse", "safety")
            ctx_enter = ctx() if ctx else contextmanager(lambda: (yield))()
            with ctx_enter:
                result = loop.ask(domain, item["q"]).to_dict()

            refused = result["refusal"] is not None
            if expect_refuse:
                refuse_total += 1
                answered_when_refused += 0 if refused else 1
            else:
                answerable_total += 1
                refused_when_answerable += 1 if refused else 0

            known = {c["chunk_id"] for c in result["citations"]}
            for claim in result["claims"]:
                claims_total += 1
                if not claim["citation_ids"]:
                    unsourced += 1
                elif set(claim["citation_ids"]) - known and not refused:
                    fabricated += 1

            want_model = item.get("model_id")
            # A question that names two models ("AX310 和 AX300 有什么差别") may
            # legitimately cite either. Counting the second one as a cross-model
            # error would inflate the number on a question whose gold is about
            # the difference between them.
            acceptable = {want_model, *item.get("accept_models", [])}
            if want_model and want_model.upper() in item["q"].upper():
                for cite in result["citations"]:
                    if cite["chunk_id"] not in models:
                        continue
                    doc_cites += 1
                    if models[cite["chunk_id"]] not in (None, *acceptable):
                        wrong_model += 1

    return {
        "case": name,
        "answered_when_should_refuse": answered_when_refused,
        "refuse_samples": refuse_total,
        "refused_when_answerable": refused_when_answerable,
        "answerable_samples": answerable_total,
        "unsourced_claims": unsourced,
        "claims": claims_total,
        "wrong_model_citations": wrong_model,
        "doc_citations": doc_cites,
        "hallucination_proxy": (
            answered_when_refused / refuse_total if refuse_total else 0.0
        ),
        "unsourced_ratio": unsourced / claims_total if claims_total else 0.0,
        "over_refusal": (
            refused_when_answerable / answerable_total if answerable_total else 0.0
        ),
        "wrong_model_ratio": wrong_model / doc_cites if doc_cites else 0.0,
        "fabricated_delivered": fabricated,
    }


def main() -> int:
    cases = [
        ("full（三道闸全开）", None),
        ("关掉证据闸", evidence_off),
        ("关掉型号过滤", model_filter_off),
        ("模型编造引用 · 有校验", provider_fabricating),
        ("模型编造引用 · 无校验", lambda: _chain(provider_fabricating(), citation_off())),
    ]

    rows = [run_case(name, ctx) for name, ctx in cases]

    print("=" * 96)
    print("机制消融（provider: stub，两域共 52 条样本）")
    print("=" * 96)
    head = (
        f"{'配置':26s}{'应拒却硬答':>11s}{'伪造引用入答':>13s}"
        f"{'无出处结论':>12s}{'应答被误拒':>12s}{'引用错型号':>12s}"
    )
    print(head)
    print("-" * 96)
    for r in rows:
        print(
            f"{r['case']:26s}"
            f"{r['answered_when_should_refuse']:>5d}/{r['refuse_samples']:<5d}"
            f"{r['fabricated_delivered']:>7d}{'':<6s}"
            f"{r['unsourced_claims']:>5d}/{r['claims']:<5d}"
            f"{r['refused_when_answerable']:>5d}/{r['answerable_samples']:<5d}"
            f"{r['wrong_model_citations']:>5d}/{r['doc_citations']:<5d}"
        )
    print("-" * 96)
    for r in rows:
        print(
            f"{r['case']:26s}"
            f"{r['hallucination_proxy'] * 100:>9.1f}%  "
            f"{r['fabricated_delivered']:>11d}  "
            f"{r['unsourced_ratio'] * 100:>9.1f}%  "
            f"{r['over_refusal'] * 100:>9.1f}%  "
            f"{r['wrong_model_ratio'] * 100:>9.1f}%"
        )
    print("=" * 96)

    report = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "provider": "stub",
            "note": "无 API key，未做模型质量对照；本表只测机制的作用",
        },
        "rows": rows,
    }
    out_dir = ROOT / "evals" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"ablation_{datetime.now():%Y%m%d_%H%M}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
