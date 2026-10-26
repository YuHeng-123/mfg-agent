"""测一次提问要多久：冷启动 vs 预热后。

预热前第一问要抽 PDF、建索引，这段时间是"服务看起来卡住了"的来源。
这个脚本把它量化：先清掉索引缓存测冷启动，再预热测 p50/p95。

用法：python scripts/bench_latency.py
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.agent.loop import ask  # noqa: E402
from domains.equipment import store  # noqa: E402

QUESTIONS = [
    "3 号线空压机报 E05，排气温度 118℃，怎么处理？",
    "AX300 报 E01 排气压力过高怎么办",
    "BP2200 机械密封泄漏怎么处理",
    "HE800 外漏怎么补紧",
    "空压机安全阀多久校验一次",
    "AX300 油滤多久换一次",
    "BP2200 轴承温度超过 95 度要不要停机",
    "HE800 压降超过多少要报警",
    "AX310 排气温度高怎么处理，润滑油多久换",
    "BP2200 汽蚀怎么处理，检修前要注意什么",
]


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    idx = min(len(ordered) - 1, round((len(ordered) - 1) * p))
    return ordered[idx]


def run(label: str) -> list[float]:
    times = []
    for q in QUESTIONS:
        began = time.perf_counter()
        ask("equipment", q)
        times.append((time.perf_counter() - began) * 1000)
    print(
        f"{label:<10} p50 {percentile(times, 0.5):7.1f} ms   "
        f"p95 {percentile(times, 0.95):7.1f} ms   "
        f"均值 {statistics.mean(times):7.1f} ms   首问 {times[0]:7.1f} ms"
    )
    return times


def main() -> int:
    store.index.cache_clear()
    store.chunks.cache_clear()
    run("冷启动")
    print("  预热（构建索引）…")
    store.index()
    warm = run("预热后")
    print(f"\n首问从 {warm[0]:.0f} ms 量级看，预热把 2 秒的索引构建挪到了启动时。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
