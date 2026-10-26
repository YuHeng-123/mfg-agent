"""生成多跳评测样本（P3）。

与单跳样本的区别：gold 是 2-3 个段落，分布在不同章节（常常不同页）。
回答这类问题必须把多段证据拼起来，只命中一段就算答了一半。

标注前用 scripts/probe_multihop.py 逐个确认 gold 能进 top5——
"第二跳根本没召回"和"召回了但没拼进去"是两种不同的失败，不能混在一起看。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "evals" / "equipment.jsonl"

# (问题, 型号, gold 段落, 备注)
CASES: list[tuple[str, str, list[str], str]] = [
    (
        "AX300 E05 排气温度高处置完要换哪些备件",
        "AX300",
        ["AX300_manual#p4#s08#c01", "AX300_manual#p5#s14#c01"],
        "处置步骤 + 备件清单",
    ),
    (
        "AX300 报 E05 处置前要不要挂牌上锁，具体怎么处置",
        "AX300",
        ["AX300_manual#p2#s03#c01", "AX300_manual#p4#s08#c01"],
        "安全前置条件 + 处置步骤",
    ),
    (
        "AX300 油温高 E06 怎么处置，油滤多久换一次",
        "AX300",
        ["AX300_manual#p4#s09#c01", "AX300_manual#p5#s13#c01"],
        "故障处置 + 维护周期表",
    ),
    (
        "AX300 振动大怎么处置，点检周期是怎么定的",
        "AX300",
        ["AX300_manual#p4#s11#c01", "AX300_manual#p5#s13#c01"],
        "故障处置 + 维护周期表",
    ),
    (
        "AX300 主机过电流停机怎么处理，要备哪些电气件",
        "AX300",
        ["AX300_manual#p5#s12#c01", "AX300_manual#p5#s14#c01"],
        "故障处置 + 备件清单（第二跳未进 top5，如实保留）",
    ),
    (
        "AX300 报 E05 处置步骤是什么，事后按什么周期点检，备件型号是什么",
        "AX300",
        ["AX300_manual#p4#s08#c01", "AX300_manual#p5#s13#c01", "AX300_manual#p5#s14#c01"],
        "三跳：处置 + 周期 + 备件",
    ),
    (
        "AX310 排气温度高怎么处理，润滑油多久换",
        "AX310",
        ["AX310_manual#p3#s05#c01", "AX310_manual#p3#s07#c01"],
        "故障处置 + 维护周期表",
    ),
    (
        "AX310 振动报警怎么处置，维护周期有哪些",
        "AX310",
        ["AX310_manual#p3#s06#c01", "AX310_manual#p3#s07#c01"],
        "故障处置 + 维护周期表",
    ),
    (
        "AX310 和 AX300 有什么差别，排气温度高时怎么处置",
        "AX310",
        ["AX310_manual#p2#s01#c01", "AX310_manual#p3#s05#c01"],
        "机型差异说明 + 故障处置",
    ),
    (
        "AX310 额定排气量是多少，滤芯更换周期呢",
        "AX310",
        ["AX310_manual#p2#s03#c01", "AX310_manual#p3#s07#c01"],
        "参数表 + 维护周期表",
    ),
    (
        "BP2200 机械密封泄漏怎么处理，备件规格是什么",
        "BP2200",
        ["BP2200_manual#p4#s09#c01", "BP2200_manual#p5#s13#c01"],
        "故障处置 + 备件清单",
    ),
    (
        "BP2200 汽蚀怎么处理，检修前要注意什么",
        "BP2200",
        ["BP2200_manual#p3#s08#c01", "BP2200_manual#p2#s03#c01"],
        "故障处置 + 安全前置条件",
    ),
    (
        "BP2200 轴承温度高怎么处置，润滑脂多久补一次",
        "BP2200",
        ["BP2200_manual#p4#s10#c01", "BP2200_manual#p4#s12#c01"],
        "故障处置 + 维护周期表",
    ),
    (
        "BP2200 出口压力不足是什么原因，处理时要换哪些备件",
        "BP2200",
        ["BP2200_manual#p3#s07#c01", "BP2200_manual#p5#s13#c01"],
        "故障处置 + 备件清单",
    ),
    (
        "BP2200 氯离子浓度限制是多少，密封备件型号是什么",
        "BP2200",
        ["BP2200_manual#p2#s02#c01", "BP2200_manual#p5#s13#c01"],
        "介质限制 + 备件清单",
    ),
    (
        "HE800 外漏怎么处置，要准备哪些备件",
        "HE800",
        ["HE800_manual#p3#s09#c01", "HE800_manual#p4#s12#c01"],
        "故障处置 + 备件清单",
    ),
    (
        "HE800 换热效率下降怎么处理，压降超过多少报警",
        "HE800",
        ["HE800_manual#p3#s07#c01", "HE800_manual#p4#s11#c01"],
        "故障处置 + 维护周期表（阈值）",
    ),
    (
        "HE800 拆解前要做什么安全措施，板片备件库存多少",
        "HE800",
        ["HE800_manual#p2#s03#c01", "HE800_manual#p4#s12#c01"],
        "安全前置条件 + 备件清单",
    ),
    (
        "HE800 压降升高怎么处置，压降记录多久做一次",
        "HE800",
        ["HE800_manual#p3#s08#c01", "HE800_manual#p4#s11#c01"],
        "故障处置 + 点检周期",
    ),
    (
        "HE800 内漏是什么原因，拆解前必须做什么",
        "HE800",
        ["HE800_manual#p4#s10#c01", "HE800_manual#p2#s03#c01"],
        "故障处置 + 安全前置条件",
    ),
]


def build() -> list[dict]:
    rows = []
    for i, (q, model, gold, note) in enumerate(CASES, start=1):
        rows.append(
            {
                "id": f"M-{i:02d}",
                "domain": "equipment",
                "q": q,
                "model_id": model,
                "type": "multihop",
                "hops": len(gold),
                "gold_chunk_ids": gold,
                "note": note,
            }
        )
    return rows


def main() -> int:
    existing = [
        json.loads(line)
        for line in OUT.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    keep = [r for r in existing if r.get("type") != "multihop"]
    rows = keep + build()
    OUT.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    print(f"{OUT}: {len(keep)} 条保留 + {len(build())} 条多跳 = {len(rows)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
