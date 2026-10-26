"""Print the evidence-gate statistics for every eval item so thresholds are chosen, not guessed."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from domains.equipment import store  # noqa: E402


def main() -> None:
    index = store.index()
    rows = []
    for line in (ROOT / "evals" / "equipment.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        stats = index.query_stats(item["q"])
        hits = index.search(item["q"], top_k=5, model_id=item.get("model_id"))
        rows.append((item["type"], stats.matched_terms, stats.matched_mass, len(hits), item["id"], item["q"]))

    rows.sort(key=lambda r: (r[0], r[2]))
    print(f"{'type':10s}{'terms':>6s}{'mass':>8s}{'hits':>6s}  id     question")
    for r in rows:
        print(f"{r[0]:10s}{r[1]:>6d}{r[2]:>8.2f}{r[3]:>6d}  {r[4]}  {r[5]}")

    ans = [r for r in rows if r[0] == "retrieval"]
    ref = [r for r in rows if r[0] == "refuse"]
    print(f"\n应答样本 mass 最小 {min(r[2] for r in ans):.2f}  terms 最小 {min(r[1] for r in ans)}")
    print(f"拒答样本 mass 最大 {max(r[2] for r in ref):.2f}  terms 最大 {max(r[1] for r in ref)}")


if __name__ == "__main__":
    main()
