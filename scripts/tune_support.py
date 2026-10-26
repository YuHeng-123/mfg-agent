"""支撑段选择（support selection）的切分对比。

上一轮检索调参踩过一次坑：一个改动在全量上 +6 分，在训练集上是负的。
所以这次先切分再选配置——多跳样本是新增的，还没被反复看过，正好能用。

用法：python scripts/tune_support.py
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.agent.loop import ask  # noqa: E402
from core.evals import metrics  # noqa: E402

ITEMS = [
    json.loads(line)
    for line in (ROOT / "evals" / "equipment.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
ANSWERABLE = [i for i in ITEMS if i["type"] in ("retrieval", "multihop")]

# 每隔第三条进测试集，与上一轮检索切分同一套做法
TRAIN = [i for n, i in enumerate(ANSWERABLE) if n % 3 != 0]
TEST = [i for n, i in enumerate(ANSWERABLE) if n % 3 == 0]

CONFIGS = [
    ("基线 filter/0.6/不分解", {"SUPPORT_CODE_MODE": "filter", "SUPPORT_SCORE_RATIO": "0.6", "DECOMPOSE_CLAUSES": "0"}),
    ("prefer/0.6/分解", {"SUPPORT_CODE_MODE": "prefer", "SUPPORT_SCORE_RATIO": "0.6", "DECOMPOSE_CLAUSES": "1"}),
    ("prefer/0.7/分解", {"SUPPORT_CODE_MODE": "prefer", "SUPPORT_SCORE_RATIO": "0.7", "DECOMPOSE_CLAUSES": "1"}),
    ("prefer/0.75/分解", {"SUPPORT_CODE_MODE": "prefer", "SUPPORT_SCORE_RATIO": "0.75", "DECOMPOSE_CLAUSES": "1"}),
    ("prefer/0.9/分解", {"SUPPORT_CODE_MODE": "prefer", "SUPPORT_SCORE_RATIO": "0.9", "DECOMPOSE_CLAUSES": "1"}),
]


def measure(items: list[dict]) -> dict:
    precisions, hits, single, multi = [], [], [], []
    for item in items:
        result = ask("equipment", item["q"]).to_dict()
        gold = item["gold_chunk_ids"]
        doc_ids = {
            c["chunk_id"] for c in result["citations"] if c["kind"] in ("manual", "standard", "internal")
        }
        cited = list({cid for c in result["claims"] for cid in c["citation_ids"] if cid in doc_ids})
        precisions.append(metrics.citation_precision(cited, gold))
        hits.append(metrics.citation_recall(cited, gold))
        (multi if item["type"] == "multihop" else single).append(
            metrics.citation_coverage(cited, gold)
        )
    avg = lambda xs: round(sum(xs) / len(xs) * 100, 1) if xs else 0.0
    return {"precision": avg(precisions), "hit": avg(hits), "single": avg(single), "multi": avg(multi)}


def apply_config(env: dict) -> None:
    """直接改 settings 单例。

    不能用 importlib.reload：其余模块是 `from core.config import settings`，
    reload 只会新建一个对象，旧引用还在，改了等于没改。
    """

    from core.config import settings

    settings.support_code_mode = env["SUPPORT_CODE_MODE"]
    settings.support_score_ratio = float(env["SUPPORT_SCORE_RATIO"])
    settings.decompose_clauses = env["DECOMPOSE_CLAUSES"] == "1"


def main() -> int:
    print(f"训练 {len(TRAIN)} 条 / 测试 {len(TEST)} 条\n")
    train_cols = ["精(训)", "命(训)", "单(训)", "多(训)"]
    test_cols = ["精(测)", "命(测)", "单(测)", "多(测)"]
    head = "配置".ljust(24) + "".join(t.rjust(8) for t in train_cols)
    head += "   |" + "".join(t.rjust(8) for t in test_cols)
    print(head)
    for label, env in CONFIGS:
        apply_config(env)
        tr, te = measure(TRAIN), measure(TEST)
        print(
            f"{label:<24}{tr['precision']:>8.1f}{tr['hit']:>8.1f}{tr['single']:>8.1f}{tr['multi']:>8.1f}   |"
            f"{te['precision']:>8.1f}{te['hit']:>8.1f}{te['single']:>8.1f}{te['multi']:>8.1f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
