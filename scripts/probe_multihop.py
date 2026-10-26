"""临时诊断：候选多跳问题的 top5 命中情况，用来确认标注是否公平。

标注前先做这一步。如果一个"多跳"问题的第二跳根本进不了 top5，那它不是检索排序问题，
而是召回问题，标成多跳 gold 会不公平——这两种失败要分开记。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from domains.equipment import store  # noqa: E402

CASES: list[tuple[str, str, list[str]]] = [
    (
        "AX300 E05 排气温度高处置完要换哪些备件",
        "AX300",
        [["AX300_manual#p4#s08#c01", "AX300_manual#p5#s14#c01"]],
    ),
    (
        "AX300 报 E05 处置前要不要挂牌上锁，具体怎么处置",
        "AX300",
        [["AX300_manual#p2#s03#c01", "AX300_manual#p4#s08#c01"]],
    ),
    (
        "AX300 油温高 E06 怎么处置，油滤多久换一次",
        "AX300",
        [["AX300_manual#p4#s09#c01", "AX300_manual#p5#s13#c01"]],
    ),
    (
        "AX300 排气压力高 E01 怎么处置，要准备哪些备件",
        "AX300",
        [["AX300_manual#p3#s07#c01", "AX300_manual#p5#s14#c01"]],
    ),
    (
        "AX300 振动大怎么处置，点检周期是怎么定的",
        "AX300",
        [["AX300_manual#p4#s11#c01", "AX300_manual#p5#s13#c01"]],
    ),
    (
        "AX300 主机过电流停机怎么处理，要备哪些电气件",
        "AX300",
        [["AX300_manual#p5#s12#c01", "AX300_manual#p5#s14#c01"]],
    ),
    (
        "AX300 冷却水流量低于多少会报警，排气温度高怎么处置",
        "AX300",
        [["AX300_manual#p3#s05#c01", "AX300_manual#p4#s08#c01"]],
    ),
    (
        "AX300 额定排气量是多少，空气滤芯多久换",
        "AX300",
        [["AX300_manual#p2#s04#c01", "AX300_manual#p5#s13#c01"]],
    ),
    (
        "AX300 报 E05 处置步骤是什么，事后按什么周期点检，备件型号是什么",
        "AX300",
        ["AX300_manual#p4#s08#c01", "AX300_manual#p5#s13#c01", "AX300_manual#p5#s14#c01"],
    ),
    (
        "AX310 排气温度高怎么处理，润滑油多久换",
        "AX310",
        [["AX310_manual#p3#s05#c01", "AX310_manual#p3#s07#c01"]],
    ),
    (
        "AX310 振动报警怎么处置，维护周期有哪些",
        "AX310",
        [["AX310_manual#p3#s06#c01", "AX310_manual#p3#s07#c01"]],
    ),
    (
        "AX310 和 AX300 有什么差别，排气温度高时怎么处置",
        "AX310",
        [["AX310_manual#p2#s01#c01", "AX310_manual#p3#s05#c01"]],
    ),
    (
        "AX310 额定排气量是多少，滤芯更换周期呢",
        "AX310",
        [["AX310_manual#p2#s03#c01", "AX310_manual#p3#s07#c01"]],
    ),
    (
        "BP2200 机械密封泄漏怎么处理，备件规格是什么",
        "BP2200",
        [["BP2200_manual#p4#s09#c01", "BP2200_manual#p5#s13#c01"]],
    ),
    (
        "BP2200 汽蚀怎么处理，检修前要注意什么",
        "BP2200",
        [["BP2200_manual#p3#s08#c01", "BP2200_manual#p2#s03#c01"]],
    ),
    (
        "BP2200 轴承温度高怎么处置，润滑脂多久补一次",
        "BP2200",
        [["BP2200_manual#p4#s10#c01", "BP2200_manual#p4#s12#c01"]],
    ),
    (
        "BP2200 出口压力不足是什么原因，处理时要换哪些备件",
        "BP2200",
        [["BP2200_manual#p3#s07#c01", "BP2200_manual#p5#s13#c01"]],
    ),
    (
        "BP2200 振动大怎么处理，检修前要做什么",
        "BP2200",
        [["BP2200_manual#p4#s11#c01", "BP2200_manual#p2#s03#c01"]],
    ),
    (
        "BP2200 氯离子浓度限制是多少，密封备件型号是什么",
        "BP2200",
        [["BP2200_manual#p2#s02#c01", "BP2200_manual#p5#s13#c01"]],
    ),
    (
        "BP2200 汽蚀怎么处置，润滑脂补充周期是多久",
        "BP2200",
        [["BP2200_manual#p3#s08#c01", "BP2200_manual#p4#s12#c01"]],
    ),
    (
        "HE800 外漏怎么处置，要准备哪些备件",
        "HE800",
        [["HE800_manual#p3#s09#c01", "HE800_manual#p4#s12#c01"]],
    ),
    (
        "HE800 换热效率下降怎么处理，压降超过多少报警",
        "HE800",
        [["HE800_manual#p3#s07#c01", "HE800_manual#p4#s11#c01"]],
    ),
    (
        "HE800 拆解前要做什么安全措施，板片备件库存多少",
        "HE800",
        [["HE800_manual#p2#s03#c01", "HE800_manual#p4#s12#c01"]],
    ),
    (
        "HE800 压降升高怎么处置，压降记录多久做一次",
        "HE800",
        [["HE800_manual#p3#s08#c01", "HE800_manual#p4#s11#c01"]],
    ),
    (
        "HE800 内漏是什么原因，拆解前必须做什么",
        "HE800",
        [["HE800_manual#p4#s10#c01", "HE800_manual#p2#s03#c01"]],
    ),
    (
        "HE800 垫片材质有什么限制，外漏怎么处置",
        "HE800",
        [["HE800_manual#p2#s02#c01", "HE800_manual#p3#s09#c01"]],
    ),
    (
        "HE800 板片数量和换热面积是多少，外漏怎么补紧",
        "HE800",
        [["HE800_manual#p2#s04#c01", "HE800_manual#p3#s09#c01"]],
    ),
]


def main() -> int:
    index = store.index()
    reachable = 0
    for q, model, gold in CASES:
        hits = index.search(q, top_k=5, model_id=model)
        ids = [h.chunk.chunk_id for h in hits]
        covered = [g for g in gold if g in ids]
        reachable += int(len(covered) == len(gold))
        flag = "OK " if len(covered) == len(gold) else "MISS"
        print(f"{flag} [{len(covered)}/{len(gold)}] {q}")
        for g in gold:
            if g not in ids:
                print(f"        未进 top5: {g}")
    print(f"\n{reachable}/{len(CASES)} 个候选全部 gold 进入 top5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
