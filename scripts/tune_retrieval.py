"""Compare retrieval configurations on a train/test split.

The point is to not fool ourselves: three variants were tried on the same 25
questions before this script existed, which is exactly how a metric gets inflated.
Here the split comes first, the choice is made on train, and the test number is
printed once.
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.evals import metrics  # noqa: E402
from core.rag.index import Index  # noqa: E402
from domains.equipment import store  # noqa: E402


def split(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Deterministic 2/3-1/3 split, stratified by model."""

    train, test = [], []
    for model in sorted({i["model_id"] for i in items}):
        group = [i for i in items if i["model_id"] == model]
        for n, item in enumerate(group):
            (test if n % 3 == 2 else train).append(item)
    return train, test


def evaluate(ix: Index, items: list[dict]) -> dict:
    r1 = h1 = r5 = mrr = 0.0
    for item in items:
        gold = item["gold_chunk_ids"]
        ids = [h.chunk.chunk_id for h in ix.search(item["q"], top_k=5, model_id=item["model_id"])]
        r1 += metrics.recall_at_k(ids, gold, 1)
        h1 += metrics.hit_at_k(ids, gold, 1)
        r5 += metrics.recall_at_k(ids, gold, 5)
        mrr += metrics.reciprocal_rank(ids, gold)
    n = len(items) or 1
    return {"n": len(items), "recall@1": r1 / n, "hit@1": h1 / n, "recall@5": r5 / n, "mrr": mrr / n}


def main() -> None:
    items = [
        json.loads(line)
        for line in (ROOT / "evals" / "equipment.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    items = [i for i in items if i["type"] == "retrieval"]
    train, test = split(items)
    chunks = list(store.chunks())

    configs = []
    for drop_title, penalty in itertools.product([False, True], [1.0, 0.5]):
        configs.append({"drop_title_terms": drop_title, "low_info_penalty": penalty})

    print(f"训练 {len(train)} 条 / 测试 {len(test)} 条（按型号分层切分）\n")
    print(f"{'配置':46s}{'train R@1':>10s}{'train Hit@1':>12s}{'train R@5':>11s}")
    print("-" * 82)
    results = []
    for cfg in configs:
        ix = Index(chunks, **cfg)
        tr = evaluate(ix, train)
        label = f"drop_title={cfg['drop_title_terms']}, penalty={cfg['low_info_penalty']}"
        print(f"{label:46s}{tr['recall@1'] * 100:>9.1f}%{tr['hit@1'] * 100:>11.1f}%{tr['recall@5'] * 100:>10.1f}%")
        results.append((cfg, tr))

    best_cfg, _ = max(results, key=lambda pair: (pair[1]["recall@1"], pair[1]["hit@1"]))
    print("\n按训练集选定：", best_cfg)
    ix = Index(chunks, **best_cfg)
    te = evaluate(ix, test)
    print(f"测试集（只跑这一次）：Recall@1 {te['recall@1'] * 100:.1f}%  "
          f"Hit@1 {te['hit@1'] * 100:.1f}%  Recall@5 {te['recall@5'] * 100:.1f}%  MRR {te['mrr']:.3f}")


if __name__ == "__main__":
    main()
