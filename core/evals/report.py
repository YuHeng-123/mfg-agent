"""Console table and JSON report rendering."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def _pct(value: float) -> str:
    return f"{value * 100:5.1f}%"


def _equipment(block: dict) -> None:
    if "retrieval" in block:
        r = block["retrieval"]
        print("\n[设备域 · 检索]  同一索引，型号硬过滤开启")
        print(
            f"  Recall@1 {_pct(r['recall@1'])}   Recall@3 {_pct(r['recall@3'])}   "
            f"Recall@5 {_pct(r['recall@5'])}   MRR {r['mrr']:.3f}"
        )
        print(
            f"  Hit@1    {_pct(r['hit@1'])}   Hit@3    {_pct(r['hit@3'])}"
            "   （命中任一可接受段落，多答案题不会被判半分）"
        )
        f = r["model_filter"]
        print(f"  A/B  开启过滤 top1 命中 gold {_pct(f['with_filter_top1_gold'])}")
        print(
            f"       关闭过滤 top1 落到错误型号 {_pct(f['without_filter_wrong_model'])}"
            f"  （{f['questions']} 题）"
        )
    if "answer" in block:
        _answers(block["answer"], "设备域 · 答复")


def _compliance(block: dict) -> None:
    if "gaps" in block:
        g = block["gaps"]
        print("\n[体检域 · 差距识别]  规则比对，不经过模型")
        print(
            f"  差距召回 {_pct(g['gap_recall'])}   差距精确 {_pct(g['gap_precision'])}   "
            f"误报 {g['false_positives']} 项"
        )
        print(f"  无差距题判空正确率 {_pct(g['no_gap_clean_rate'])}（{g['no_gap_items']} 题）")
        wrong = [i for i in g["items"] if set(i["pred"]) - set(i["gold"])]
        if wrong:
            print("  误报明细：")
            for item in wrong[:5]:
                extra = sorted(set(item["pred"]) - set(item["gold"]))
                print(f"    {item['id']} 多报 {extra}")
    if "answer" in block:
        _answers(block["answer"], "体检域 · 答复")


def _answers(a: dict, title: str) -> None:
    c = a["confusion"]
    print(f"\n[{title}]")
    print(f"  引用精确率 {_pct(a['citation_precision'])}   引用命中率 {_pct(a['citation_hit_rate'])}")
    print(f"  拒答正确率 {_pct(a['refusal_accuracy'])}   误拒率 {_pct(a['rates']['over_refusal'])}")
    print(
        f"  混淆矩阵  应答/实答 {c['tp']}  应答/实拒 {c['fn']}  "
        f"应拒/实答 {c['fp']}  应拒/实拒 {c['tn']}"
    )
    bad = [d for d in a["detail"] if d["type"] in ("refuse", "safety") and not d.get("refusal_ok")]
    if bad:
        print("  拒答未达预期：")
        for d in bad[:6]:
            print(f"    {d['id']} 期望 {d['expected_kind']} 实际 {d['refusal_kind']}")


def render_console(report: dict) -> None:
    meta = report["meta"]
    print("=" * 68)
    print("设备知识 Agent · 评测报告（取用 + 体检）")
    print("=" * 68)
    print(f"时间 {meta['generated_at']}   commit {meta['commit']}   provider {meta['provider']}")
    print(f"耗时 {meta['elapsed_s']} s")
    s = meta["settings"]
    print(
        f"阈值 命中词>={s['evidence_min_terms']} 信息量>={s['evidence_min_mass']} "
        f"片段>={s['evidence_min_hits']}  top_k={s['top_k']}"
    )
    # Dispatch on which measurements the block contains, not on the domain name.
    # The renderer must not know that "equipment" exists.
    for name, block in report.items():
        if name == "meta" or not isinstance(block, dict):
            continue
        print(f"\n--- {name} | chunk {block['corpus']['chunks']} | 样本 {block['samples']} ---")
        if "retrieval" in block:
            _equipment(block)
        elif "gaps" in block:
            _compliance(block)
        elif "answer" in block:
            _answers(block["answer"], name)

    code = meta["code"]
    print("\n[跨域]  代码复用")
    print(
        f"  core {code['core_lines']} 行 / domains {code['domains_lines']} 行 "
        f"→ core 占逻辑代码 {_pct(code['core_share_of_logic'])}"
    )
    print(f"  app {code['app_lines']} 行   scripts {code['scripts_lines']} 行   tests {code['tests_lines']} 行")
    print("=" * 68)


def write_report(report: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    path = out_dir / f"{stamp}_{report['meta']['commit']}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
