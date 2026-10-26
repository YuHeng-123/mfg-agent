"""P0 probe: can we get clean text, page numbers and section titles out of the PDFs?

This is the risk gate for the whole data plan. It reports:
  - section recall      did we recover the section boundaries at all
  - page accuracy       does the extracted page equal the page the section really starts on
  - table rebuild       did the bordered fault-code table survive extraction
  - header pollution    did running headers or footers leak into any chunk

Run:  python scripts/probe_pdf.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.rag.loader import load_pdf  # noqa: E402

MAN_DIR = ROOT / "data" / "equipment" / "manuals"


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def main() -> int:
    truth = json.loads((MAN_DIR / "_truth.json").read_text(encoding="utf-8"))
    rows = []
    failures: list[str] = []

    for doc in truth["docs"]:
        pdf = MAN_DIR / doc["pdf"]
        chunks = load_pdf(
            pdf,
            {
                "doc_id": doc["doc_id"],
                "doc_title": doc["doc_title"],
                "model_id": doc["model_id"],
                "doc_type": "manual",
            },
        )
        by_section = {}
        for c in chunks:
            if c.section:
                by_section.setdefault(norm(c.section), c)

        hit = page_ok = 0
        for sec in doc["sections"]:
            key = norm(sec["title"])
            chunk = by_section.get(key)
            if chunk:
                hit += 1
                if chunk.page == sec["page"]:
                    page_ok += 1

        table_rows = sum(1 for c in chunks if " | " in c.text)
        header_leak = [
            c.chunk_id
            for c in chunks
            if "共 " in c.text and "页" in c.text and len(c.text) < 40
        ]
        if hit < len(doc["sections"]):
            failures.append(
                f"{doc['doc_id']}: 漏检章节 {len(doc['sections']) - hit}/{len(doc['sections'])}"
            )
        if page_ok < hit:
            failures.append(f"{doc['doc_id']}: 页码错位 {hit - page_ok}/{hit}")
        if table_rows == 0:
            failures.append(f"{doc['doc_id']}: 表格未重建")
        if header_leak:
            failures.append(f"{doc['doc_id']}: 页眉页脚污染 {len(header_leak)} 处")

        rows.append(
            {
                "doc_id": doc["doc_id"],
                "pages": doc["pages"],
                "chunks": len(chunks),
                "sections_truth": len(doc["sections"]),
                "sections_found": hit,
                "page_ok": page_ok,
                "table_rows": table_rows,
                "avg_chars": round(sum(len(c.text) for c in chunks) / max(len(chunks), 1)),
            }
        )

    print(f"{'doc':16s}{'pages':>6s}{'chunks':>8s}{'sections':>10s}{'page_ok':>9s}{'table_rows':>12s}{'avg_chars':>11s}")
    for r in rows:
        print(
            f"{r['doc_id']:16s}{r['pages']:>6d}{r['chunks']:>8d}"
            f"{r['sections_found']:>4d}/{r['sections_truth']:<5d}{r['page_ok']:>9d}"
            f"{r['table_rows']:>12d}{r['avg_chars']:>11d}"
        )

    total_sec = sum(r["sections_truth"] for r in rows)
    total_hit = sum(r["sections_found"] for r in rows)
    total_page = sum(r["page_ok"] for r in rows)
    print()
    print(f"章节召回   {total_hit}/{total_sec} = {total_hit / max(total_sec, 1):.3f}")
    print(f"页码准确   {total_page}/{total_hit} = {total_page / max(total_hit, 1):.3f}")

    if failures:
        print("\n问题：")
        for f in failures:
            print(" -", f)
        return 1

    print("\n结论：PDF 抽取可用于真实手册线，无需降级为纯 Markdown。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
