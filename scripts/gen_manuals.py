"""Render the hand-written manuals into PDFs that look like real factory manuals.

Why generate PDFs instead of shipping markdown only:
  - the retrieval path we want to defend is "PDF in, chunked text with page and
    section out". Skipping the PDF step would make that claim hollow;
  - generating the PDFs ourselves gives us ground truth: we know on which page
    every section landed, so extraction accuracy can be measured instead of
    asserted.

Deliberately included so extraction is non-trivial: running headers, page
footers, bordered tables, shaded warning boxes, and sections that break across
a page boundary.

Run:  python scripts/gen_manuals.py
Out:  data/equipment/manuals/*.pdf, data/equipment/manuals/_truth.json,
      data/equipment/registry/devices.json
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "equipment" / "manuals" / "src"
OUT = ROOT / "data" / "equipment" / "manuals"

FONT_REG = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"

PAGE_W, PAGE_H = 595, 842
MARGIN_L, MARGIN_R = 64, 64
BODY_TOP, BODY_BOTTOM = 96, 782
HEADER_Y, FOOTER_Y = 52, 812

SIZE_BODY = 10.5
SIZE_H1 = 19
SIZE_H2 = 13.5
LEADING = 16.5

RE_SECTION = re.compile(r"^\d+\.\d+(\.\d+)?\s")

CATALOG = {
    "AX300": {"model_id": "AX300", "kind": "螺杆空压机", "doc_id": "AX300_manual"},
    "AX310": {"model_id": "AX310", "kind": "螺杆空压机", "doc_id": "AX310_manual"},
    "BP2200": {"model_id": "BP2200", "kind": "离心泵", "doc_id": "BP2200_manual"},
    "HE800": {"model_id": "HE800", "kind": "板式换热器", "doc_id": "HE800_manual"},
}


@dataclass
class Block:
    kind: str  # h1 | h2 | p | table | warn
    text: str = ""
    rows: list[list[str]] = field(default_factory=list)


def parse(md: str) -> list[Block]:
    blocks: list[Block] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if not line:
            i += 1
            continue
        if line.startswith("# "):
            blocks.append(Block("h1", line[2:].strip()))
        elif line.startswith("## "):
            blocks.append(Block("h2", line[3:].strip()))
        elif line.startswith(">"):
            blocks.append(Block("warn", line.lstrip("> ").strip()))
        elif line.startswith("|"):
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                # separator row like |---|---|
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            blocks.append(Block("table", rows=rows))
            continue
        else:
            blocks.append(Block("p", line))
        i += 1
    return blocks


class Renderer:
    def __init__(self, doc_title: str) -> None:
        self.doc = pymupdf.open()
        self.doc_title = doc_title
        self.reg = pymupdf.Font(fontfile=FONT_REG)
        self.bold = pymupdf.Font(fontfile=FONT_BOLD)
        self.y = BODY_TOP
        self.section = ""
        self.page_sections: dict[int, str] = {}
        self.truth_sections: list[dict] = []
        self.truth_paras: list[dict] = []
        self.new_page()

    # ---- page plumbing ---------------------------------------------------

    @property
    def page_no(self) -> int:
        return len(self.doc)  # 1-based

    def new_page(self) -> None:
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.page.insert_font(fontname="cjk", fontfile=FONT_REG)
        self.page.insert_font(fontname="cjkb", fontfile=FONT_BOLD)
        self.y = BODY_TOP

    def ensure(self, needed: float) -> None:
        if self.y + needed > BODY_BOTTOM:
            self.new_page()
            if self.section:
                self.page_sections.setdefault(self.page_no, self.section)

    def wrap(self, text: str, width: float, size: float, bold: bool = False) -> list[str]:
        font = self.bold if bold else self.reg
        lines: list[str] = []
        cur = ""
        cur_w = 0.0
        for ch in text:
            w = font.text_length(ch, fontsize=size)
            if cur_w + w > width and cur:
                # avoid starting a line with common closing punctuation
                lines.append(cur)
                cur, cur_w = ch, w
            else:
                cur += ch
                cur_w += w
        if cur:
            lines.append(cur)
        return lines or [""]

    def put(self, x: float, text: str, size: float = SIZE_BODY, bold: bool = False, gray: int = 0) -> None:
        self.page.insert_text(
            (x, self.y),
            text,
            fontname="cjkb" if bold else "cjk",
            fontsize=size,
            color=(gray / 255, gray / 255, gray / 255),
        )

    # ---- blocks ---------------------------------------------------------

    def cover(self, title: str, meta: dict) -> None:
        self.y = 250
        for line in self.wrap(title, PAGE_W - 2 * MARGIN_L, SIZE_H1, bold=True):
            w = self.bold.text_length(line, fontsize=SIZE_H1)
            self.put((PAGE_W - w) / 2, line, SIZE_H1, bold=True)
            self.y += 30
        self.y += 20
        sub = f"{meta['kind']} · 使用与维护手册"
        w = self.reg.text_length(sub, fontsize=13)
        self.put((PAGE_W - w) / 2, sub, 13, gray=90)
        self.y += 60
        for label in (
            f"文件编号：{meta['doc_id'].upper()}-2026",
            "版本：第 3 版",
            "编制：设备科",
            "发布日期：2026-03-01",
        ):
            w = self.reg.text_length(label, fontsize=10)
            self.put((PAGE_W - w) / 2, label, 10, gray=110)
            self.y += 20
        self.new_page()

    def h2(self, text: str) -> None:
        self.section = text
        self.ensure(60)
        self.y += 12
        for line in self.wrap(text, PAGE_W - 2 * MARGIN_L, SIZE_H2, bold=True):
            self.put(MARGIN_L, line, SIZE_H2, bold=True)
            self.y += 22
        self.y += 2
        self.truth_sections.append(
            {"title": text, "page": self.page_no, "doc_title": self.doc_title}
        )
        self.page_sections.setdefault(self.page_no, self.section)

    def para(self, text: str) -> None:
        width = PAGE_W - MARGIN_L - MARGIN_R
        lines = self.wrap(text, width, SIZE_BODY)
        for line in lines:
            self.ensure(LEADING)
            self.put(MARGIN_L, line, SIZE_BODY)
            self.y += LEADING
        self.y += 4
        self.truth_paras.append({"page": self.page_no, "section": self.section, "text": text[:40]})

    def warn(self, text: str) -> None:
        width = PAGE_W - MARGIN_L - MARGIN_R - 24
        lines = self.wrap(text, width, SIZE_BODY)
        box_h = len(lines) * LEADING + 12
        self.ensure(box_h + 8)
        rect = pymupdf.Rect(MARGIN_L, self.y - 12, PAGE_W - MARGIN_R, self.y - 12 + box_h)
        self.page.draw_rect(rect, color=(0.75, 0.6, 0.2), fill=(0.99, 0.96, 0.88), width=0.8)
        self.y += 2
        for line in lines:
            self.put(MARGIN_L + 12, line, SIZE_BODY)
            self.y += LEADING
        self.y += 12

    def table(self, rows: list[list[str]]) -> None:
        if not rows:
            return
        ncol = max(len(r) for r in rows)
        avail = PAGE_W - MARGIN_L - MARGIN_R
        # column widths proportional to the longest cell, clamped
        want = []
        for c in range(ncol):
            longest = max(
                (self.reg.text_length(r[c], fontsize=9.5) if c < len(r) else 0) for r in rows
            )
            want.append(max(48, min(longest + 18, avail * 0.55)))
        scale = avail / sum(want)
        widths = [w * scale for w in want]

        for ri, row in enumerate(rows):
            cells: list[list[str]] = []
            for c in range(ncol):
                txt = row[c] if c < len(row) else ""
                cells.append(self.wrap(txt, widths[c] - 10, 9.5, bold=(ri == 0)))
            row_h = max(len(cl) for cl in cells) * 13 + 8
            self.ensure(row_h)
            x = MARGIN_L
            top = self.y - 11
            for c in range(ncol):
                self.page.draw_rect(
                    pymupdf.Rect(x, top, x + widths[c], top + row_h),
                    color=(0.6, 0.6, 0.6),
                    width=0.5,
                )
                ty = top + 12
                for line in cells[c]:
                    self.page.insert_text(
                        (x + 5, ty),
                        line,
                        fontname="cjkb" if ri == 0 else "cjk",
                        fontsize=9.5,
                    )
                    ty += 13
                x += widths[c]
            self.y += row_h + 2
        self.y += 6

    def finish(self) -> pymupdf.Document:
        total = len(self.doc)
        for i, page in enumerate(self.doc, start=1):
            page.insert_font(fontname="cjk", fontfile=FONT_REG)
            page.draw_line(
                pymupdf.Point(MARGIN_L, HEADER_Y + 10),
                pymupdf.Point(PAGE_W - MARGIN_R, HEADER_Y + 10),
                color=(0.7, 0.7, 0.7),
                width=0.5,
            )
            page.insert_text(
                (MARGIN_L, HEADER_Y),
                self.doc_title,
                fontname="cjk",
                fontsize=8,
                color=(0.45, 0.45, 0.45),
            )
            sec = self.page_sections.get(i, "")
            if i > 1 and sec:
                w = self.reg.text_length(sec, fontsize=8)
                page.insert_text(
                    (PAGE_W - MARGIN_R - w, HEADER_Y),
                    sec,
                    fontname="cjk",
                    fontsize=8,
                    color=(0.45, 0.45, 0.45),
                )
            foot = f"第 {i} 页  共 {total} 页"
            w = self.reg.text_length(foot, fontsize=8)
            page.insert_text(
                ((PAGE_W - w) / 2, FOOTER_Y),
                foot,
                fontname="cjk",
                fontsize=8,
                color=(0.45, 0.45, 0.45),
            )
        return self.doc


def build(model_id: str, md_path: Path) -> dict:
    meta = CATALOG[model_id]
    blocks = parse(md_path.read_text(encoding="utf-8"))
    title = next((b.text for b in blocks if b.kind == "h1"), meta["doc_id"])
    r = Renderer(title)
    r.cover(title, meta)
    for b in blocks:
        if b.kind == "h1":
            continue
        if b.kind == "h2":
            r.h2(b.text)
        elif b.kind == "p":
            r.para(b.text)
        elif b.kind == "warn":
            r.warn(b.text)
        elif b.kind == "table":
            r.table(b.rows)
    doc = r.finish()
    out_pdf = OUT / f"{meta['doc_id']}.pdf"
    # Without subsetting every PDF carries the whole CJK font (~19 MB each).
    doc.subset_fonts()
    doc.save(str(out_pdf), garbage=4, deflate=True)
    doc.close()
    return {
        "model_id": model_id,
        "doc_id": meta["doc_id"],
        "doc_title": title,
        "kind": meta["kind"],
        "pdf": out_pdf.name,
        "pages": len(pymupdf.open(str(out_pdf))),
        "sections": r.truth_sections,
        "paragraphs": r.truth_paras,
    }


def devices() -> list[dict]:
    return [
        {"device_id": "AC-300-01", "model_id": "AX300", "name": "1 号空压机", "line": "3 号线动力站",
         "location": "动力站东侧", "manual": "AX300_manual",
         "thresholds": {"exhaust_temp_c": 105, "vibration_mm_s": 4.5, "current_a": 118}},
        {"device_id": "AC-300-02", "model_id": "AX300", "name": "2 号空压机", "line": "3 号线动力站",
         "location": "动力站东侧", "manual": "AX300_manual",
         "thresholds": {"exhaust_temp_c": 105, "vibration_mm_s": 4.5, "current_a": 118}},
        {"device_id": "AC-300-03", "model_id": "AX300", "name": "3 号空压机", "line": "3 号线动力站",
         "location": "动力站西侧", "manual": "AX300_manual",
         "thresholds": {"exhaust_temp_c": 105, "vibration_mm_s": 4.5, "current_a": 118}},
        {"device_id": "AC-310-01", "model_id": "AX310", "name": "1 号空压机", "line": "4 号线动力站",
         "location": "动力站北侧", "manual": "AX310_manual",
         "thresholds": {"exhaust_temp_c": 108, "vibration_mm_s": 4.0, "current_a": 110}},
        {"device_id": "PU-2200-01", "model_id": "BP2200", "name": "1 号工艺泵", "line": "2 号线输送单元",
         "location": "泵房 A 列", "manual": "BP2200_manual",
         "thresholds": {"vibration_mm_s": 4.5, "bearing_temp_c": 80, "current_a": 96}},
        {"device_id": "PU-2200-02", "model_id": "BP2200", "name": "2 号工艺泵", "line": "2 号线输送单元",
         "location": "泵房 A 列", "manual": "BP2200_manual",
         "thresholds": {"vibration_mm_s": 4.5, "bearing_temp_c": 80, "current_a": 96}},
        {"device_id": "HX-800-01", "model_id": "HE800", "name": "1 号板式换热器", "line": "1 号线换热单元",
         "location": "换热区", "manual": "HE800_manual",
         "thresholds": {"pressure_drop_mpa": 0.08, "outlet_temp_c": 45}},
    ]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    truth = {"generated_by": "scripts/gen_manuals.py", "docs": []}
    for model_id, meta in CATALOG.items():
        md_path = SRC / f"{model_id}.md"
        if not md_path.is_file():
            print(f"skip {model_id}: {md_path} missing")
            continue
        info = build(model_id, md_path)
        truth["docs"].append(info)
        print(
            f"{meta['doc_id']:14s} pages={info['pages']:2d} "
            f"sections={len(info['sections']):2d} paras={len(info['paragraphs']):3d}"
        )
    (OUT / "_truth.json").write_text(
        json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    reg_dir = ROOT / "data" / "equipment" / "registry"
    reg_dir.mkdir(parents=True, exist_ok=True)
    (reg_dir / "devices.json").write_text(
        json.dumps(devices(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"truth -> {OUT / '_truth.json'}")
    print(f"registry -> {reg_dir / 'devices.json'}")


if __name__ == "__main__":
    main()
