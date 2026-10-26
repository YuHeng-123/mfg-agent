"""Evaluation runner: one command, a console table and a JSON report.

Two domains, one harness. What is measured, and kept apart on purpose:

  equipment   retrieval quality (recall@k, MRR), model-filter A/B, citation quality,
              refusal behaviour
  compliance  gap detection (rules only, no model), citation quality, refusal behaviour
  cross       how much of the code is shared, so "reusable core" is a number, not a claim

Run:  python -m evals.run
      python -m evals.run --domain compliance
      python -m evals.run --stage retrieve
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.agent.loop import ask  # noqa: E402
from core.config import REPORTS_DIR, settings  # noqa: E402
from core.evals import metrics  # noqa: E402
from core.evals.report import render_console, write_report  # noqa: E402

DATASETS = {
    "equipment": ROOT / "evals" / "equipment.jsonl",
    "compliance": ROOT / "evals" / "compliance.jsonl",
}


def load_items(domain: str) -> list[dict]:
    path = DATASETS[domain]
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def commit_hash() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip() or "no-git"
    except Exception:
        return "no-git"


def code_reuse() -> dict:
    """Line counts per layer: the reusable-core claim, measured rather than asserted."""

    def count(folder: str) -> int:
        total = 0
        for path in (ROOT / folder).rglob("*.py"):
            if "__pycache__" in str(path):
                continue
            total += len(path.read_text(encoding="utf-8").splitlines())
        return total

    core = count("core")
    domains = count("domains")
    logic = core + domains
    return {
        "core_lines": core,
        "domains_lines": domains,
        "app_lines": count("app"),
        "scripts_lines": count("scripts"),
        "tests_lines": count("tests"),
        "core_share_of_logic": round(core / logic, 3) if logic else 0.0,
    }


def _aggregate(per_item: list[dict]) -> dict:
    n = len(per_item) or 1
    keys = ("recall@1", "recall@3", "recall@5", "hit@1", "hit@3", "mrr", "all_gold_in_top5")
    out = {k: sum(i[k] for i in per_item) / n for k in keys}
    out["questions"] = len(per_item)
    return out


def run_retrieval(items: list[dict]) -> dict:
    from domains.equipment import store

    index = store.index()
    per_item, filter_hits, no_filter_wrong = [], 0, 0

    for item in items:
        gold = item["gold_chunk_ids"]
        hits = index.search(item["q"], top_k=5, model_id=item.get("model_id"))
        ids = [h.chunk.chunk_id for h in hits]
        loose = index.search(item["q"], top_k=1, model_id=None)
        wrong = bool(loose and loose[0].chunk.meta.get("model_id") not in (None, item.get("model_id")))
        no_filter_wrong += int(wrong)
        filter_hits += int(bool(ids) and ids[0] in gold)
        per_item.append(
            {
                "id": item["id"],
                "kind": item["type"],
                "hops": len(gold),
                "recall@1": metrics.recall_at_k(ids, gold, 1),
                "recall@3": metrics.recall_at_k(ids, gold, 3),
                "recall@5": metrics.recall_at_k(ids, gold, 5),
                "hit@1": metrics.hit_at_k(ids, gold, 1),
                "hit@3": metrics.hit_at_k(ids, gold, 3),
                "mrr": metrics.reciprocal_rank(ids, gold),
                "all_gold_in_top5": metrics.gold_reachable(ids, gold),
                "top1": ids[0] if ids else None,
                "no_filter_other_model": wrong,
            }
        )

    n = len(per_item) or 1
    single = [i for i in per_item if i["kind"] == "retrieval"]
    multi = [i for i in per_item if i["kind"] == "multihop"]
    return {
        "items": per_item,
        "recall@1": sum(i["recall@1"] for i in per_item) / n,
        "recall@3": sum(i["recall@3"] for i in per_item) / n,
        "recall@5": sum(i["recall@5"] for i in per_item) / n,
        "hit@1": sum(i["hit@1"] for i in per_item) / n,
        "hit@3": sum(i["hit@3"] for i in per_item) / n,
        "mrr": sum(i["mrr"] for i in per_item) / n,
        # Single-hop and multi-hop are reported apart: a multi-hop question has
        # two or three gold paragraphs, so its set-recall is structurally lower.
        # Mixing them would make every future change look like a regression.
        "singlehop": _aggregate(single),
        "multihop": _aggregate(multi),
        "model_filter": {
            "with_filter_top1_gold": filter_hits / n,
            "without_filter_wrong_model": no_filter_wrong / n,
            "questions": len(per_item),
        },
    }


def run_gap_detection(items: list[dict]) -> dict:
    """Rules only: does the coverage check find the gaps a human labelled?"""

    from domains.compliance.tools import check_gaps

    per_item, hit_total, gold_total, pred_total, false_pos = [], 0, 0, 0, 0
    no_gap_items, no_gap_clean = 0, 0

    for item in items:
        if item["type"] in ("refuse", "safety"):
            continue
        result = check_gaps(query=item["q"])
        pred = [g["gap_id"] for g in result.data.get("gaps", [])]
        gold = item["gold_gap_ids"]
        hit = len(set(pred) & set(gold))

        hit_total += hit
        gold_total += len(gold)
        pred_total += len(pred)
        false_pos += len(set(pred) - set(gold))
        if item["type"] == "no_gap":
            no_gap_items += 1
            no_gap_clean += int(not pred)

        per_item.append(
            {"id": item["id"], "type": item["type"], "pred": pred, "gold": gold, "hit": hit}
        )

    return {
        "items": per_item,
        "gap_recall": hit_total / gold_total if gold_total else 0.0,
        "gap_precision": (pred_total - false_pos) / pred_total if pred_total else 0.0,
        "false_positives": false_pos,
        "no_gap_clean_rate": no_gap_clean / no_gap_items if no_gap_items else 0.0,
        "no_gap_items": no_gap_items,
    }


def run_answers(items: list[dict], domain: str) -> dict:
    should, did = [], []
    precisions, hits, coverages = [], [], []
    single_cov, multi_cov = [], []
    detail = []

    for item in items:
        result = ask(domain, item["q"]).to_dict()
        refused = result["refusal"] is not None
        expect_refuse = item["type"] in ("refuse", "safety")
        should.append(not expect_refuse)
        did.append(not refused)

        row = {
            "id": item["id"],
            "type": item["type"],
            "refused": refused,
            "refusal_kind": (result["refusal"] or {}).get("kind"),
            "expected_kind": item.get("refuse_kind"),
        }

        if expect_refuse:
            row["refusal_ok"] = refused and item.get("refuse_kind") in (None, row["refusal_kind"])
        elif not refused:
            doc_ids = {
                c["chunk_id"]
                for c in result["citations"]
                if c["kind"] in ("manual", "standard", "internal")
            }
            cited = [cid for c in result["claims"] for cid in c["citation_ids"] if cid in doc_ids]
            cited = list(dict.fromkeys(cited))
            gold = item["gold_chunk_ids"]
            precision = metrics.citation_precision(cited, gold)
            hit = metrics.citation_recall(cited, gold)
            coverage = metrics.citation_coverage(cited, gold)
            precisions.append(precision)
            hits.append(hit)
            coverages.append(coverage)
            (multi_cov if item["type"] == "multihop" else single_cov).append(coverage)
            row.update(
                {
                    "citation_precision": round(precision, 3),
                    "citation_hit": hit,
                    "citation_coverage": round(coverage, 3),
                    "cited": len(cited),
                    "gold": len(gold),
                }
            )
        detail.append(row)

    cells = metrics.confusion(should, did)
    rates = metrics.rates(cells)
    refuse_items = [d for d in detail if d["type"] in ("refuse", "safety")]
    avg = lambda xs: sum(xs) / len(xs) if xs else 0.0  # noqa: E731
    return {
        "detail": detail,
        "citation_precision": avg(precisions),
        "citation_hit_rate": avg(hits),
        "citation_coverage": avg(coverages),
        "singlehop_coverage": avg(single_cov),
        # Only a domain with multi-hop samples gets the split. Averaging an
        # empty list into 0.0 would print "多跳 0.0%" for a domain that simply
        # has no such samples, which reads like a failure.
        **({"multihop_coverage": avg(multi_cov)} if multi_cov else {}),
        "confusion": cells,
        "rates": rates,
        "refusal_accuracy": (
            sum(1 for d in refuse_items if d.get("refusal_ok")) / len(refuse_items) if refuse_items else 0.0
        ),
        "refuse_items": len(refuse_items),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", choices=["equipment", "compliance", "all"], default="all")
    parser.add_argument("--stage", choices=["all", "retrieve", "answer"], default="all")
    parser.add_argument("--only", default=None)
    args = parser.parse_args()

    domains = ["equipment", "compliance"] if args.domain == "all" else [args.domain]
    started = time.perf_counter()

    report: dict = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "commit": commit_hash(),
            "provider": settings.provider,
            "python": platform.python_version(),
            "domains": domains,
            "settings": {
                "evidence_min_terms": settings.evidence_min_terms,
                "evidence_min_mass": settings.evidence_min_mass,
                "evidence_min_hits": settings.evidence_min_hits,
                "top_k": settings.top_k,
                "max_steps": settings.max_steps,
                "demo_now": settings.demo_now,
            },
            "code": code_reuse(),
        }
    }

    from domains.base import load_domain

    for domain in domains:
        items = load_items(domain)
        if args.only:
            items = [i for i in items if i["id"] == args.only]
        if not items:
            continue

        d = load_domain(domain)
        block: dict = {
            "corpus": {"chunks": len(d.load_chunks()), "tools": sorted(d.tools().keys())},
            "samples": len(items),
        }

        if args.stage in ("all", "retrieve"):
            if domain == "equipment":
                block["retrieval"] = run_retrieval(
                    [i for i in items if i["type"] in ("retrieval", "multihop")]
                )
            else:
                block["gaps"] = run_gap_detection(items)
        if args.stage in ("all", "answer"):
            block["answer"] = run_answers(items, domain)

        report[domain] = block

    report["meta"]["elapsed_s"] = round(time.perf_counter() - started, 2)
    render_console(report)
    path = write_report(report, REPORTS_DIR)
    print(f"\n报告：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
