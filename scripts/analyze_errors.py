"""Error analysis: for every retrieval question, show where the gold paragraph ranked.

Diagnosis before tuning. The output is meant to be read, not parsed by a machine.
Run:  python scripts/analyze_errors.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.rag.tokenize import tokenize  # noqa: E402
from domains.equipment import store  # noqa: E402


def main() -> None:
    index = store.index()
    items = [
        json.loads(line)
        for line in (ROOT / "evals" / "equipment.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    items = [i for i in items if i["type"] == "retrieval"]

    failures = []
    for item in items:
        gold = set(item["gold_chunk_ids"])
        hits = index.search(item["q"], top_k=5, model_id=item.get("model_id"))
        ids = [h.chunk.chunk_id for h in hits]
        rank = next((r for r, cid in enumerate(ids, 1) if cid in gold), 0)
        if rank == 1:
            continue

        top1 = hits[0].chunk if hits else None
        gold_chunk = next((c for c in store.chunks() if c.chunk_id in gold), None)
        failures.append(
            {
                "id": item["id"],
                "q": item["q"],
                "model": item.get("model_id"),
                "rank": rank,
                "gold_section": gold_chunk.section if gold_chunk else "?",
                "top1_section": top1.section if top1 else "?",
                "top1_id": ids[0] if ids else "?",
                "gold_id": sorted(gold)[0] if gold else "?",
                "top1_text": (top1.text[:180].replace("\n", " ") if top1 else ""),
                "gold_text": (gold_chunk.text[:180].replace("\n", " ") if gold_chunk else ""),
                "q_tokens": tokenize(item["q"]),
                "top1_tokens": tokenize(top1.text if top1 else ""),
            }
        )

    print(f"检索样本 {len(items)} 条，Recall@1 失败 {len(failures)} 条\n")
    for f in failures:
        print("=" * 78)
        print(f"{f['id']}  gold 排名第 {f['rank']}  [{f['model']}]  {f['q']}")
        print(f"  gold : {f['gold_section']}  ({f['gold_id']})")
        print(f"  top1 : {f['top1_section']}  ({f['top1_id']})")
        # tokens of the question that the gold paragraph contains but top1 does not
        gold_only = [t for t in f["q_tokens"] if t in f["gold_text"] and t not in f["top1_text"]]
        shared = [t for t in f["q_tokens"] if t in f["top1_text"]]
        print(f"  命中 top1 的查询词: {len(shared)} 个 {shared[:8]}")
        print(f"  只在 gold 里出现的查询词: {gold_only[:8]}")
        print(f"  gold 首句: {f['gold_text'][:110]}")
        print(f"  top1 首句: {f['top1_text'][:110]}")


if __name__ == "__main__":
    main()
