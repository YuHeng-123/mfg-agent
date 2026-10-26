"""Turn manuals (PDF) and internal documents (Markdown) into Chunks.

The PDF path is the interesting one. What it has to survive:
  - running headers and page footers that would otherwise pollute every chunk;
  - tables drawn cell by cell, which come back as fragments spread across the
    page and have to be rebuilt by clustering on the y coordinate;
  - sections that continue across a page break.

Chunk granularity is (section, page). That is deliberate: a citation has to
resolve to "manual, page, section" for a technician to actually find the line,
and splitting per page stops a long section from blurring across three pages.
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from core.types import Chunk

HEADER_ZONE = 72.0
FOOTER_ZONE = 800.0
HEADING_SIZE = 12.5
LINE_TOL = 4.0
COL_GAP = 12.0
MAX_CHUNK_CHARS = 480

RE_SECTION_NO = re.compile(r"^(\d+(?:\.\d+)+)\s")
RE_DROP_LINE = re.compile(r"^(第\s*\d+\s*页\s*共\s*\d+\s*页|文件编号|版本：|编制：|发布日期)")


def _page_lines(page: pymupdf.Page) -> list[dict]:
    """Collect span rows, dropping the header/footer bands."""

    spans = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = span["text"].replace("\xa0", " ").strip()
                if not text:
                    continue
                y0, y1 = span["bbox"][1], span["bbox"][3]
                if y1 < HEADER_ZONE or y0 > FOOTER_ZONE:
                    continue
                spans.append({"text": text, "x0": span["bbox"][0], "y0": y0, "size": span["size"]})

    rows: list[dict] = []
    for span in spans:
        for row in rows:
            if abs(row["y0"] - span["y0"]) <= LINE_TOL:
                row["spans"].append(span)
                break
        else:
            rows.append({"y0": span["y0"], "spans": [span]})

    for row in rows:
        row["spans"].sort(key=lambda s: s["x0"])
        parts: list[str] = []
        prev_end = None
        for span in row["spans"]:
            if prev_end is not None and span["x0"] - prev_end > COL_GAP:
                parts.append(" | ")  # cell boundary in a rebuilt table row
            parts.append(span["text"])
            prev_end = span["x0"] + span["size"] * len(span["text"]) * 0.55
        row["text"] = "".join(parts).strip()
        row["max_size"] = max(s["size"] for s in row["spans"])

    rows.sort(key=lambda r: r["y0"])
    return rows


def load_pdf(path: Path, meta: dict | None = None, skip_cover: bool = True) -> list[Chunk]:
    """Extract chunks from a manual PDF."""

    meta = dict(meta or {})
    doc = pymupdf.open(str(path))
    doc_id = meta.get("doc_id") or path.stem
    doc_title = meta.get("doc_title") or path.stem

    chunks: list[Chunk] = []
    section = ""
    section_seq = 0
    buf: list[str] = []
    buf_page = 0
    buf_len = 0

    def flush() -> None:
        nonlocal buf, buf_len
        text = "\n".join(buf).strip()
        if text:
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}#p{buf_page}#s{section_seq:02d}#c01",
                    doc_id=doc_id,
                    doc_title=doc_title,
                    page=buf_page,
                    section=section or None,
                    text=text,
                    meta={**meta, "doc_type": meta.get("doc_type", "manual")},
                )
            )
        buf, buf_len = [], 0

    for page_index, page in enumerate(doc, start=1):
        if skip_cover and page_index == 1:
            continue
        for row in _page_lines(page):
            text = row["text"]
            if not text or RE_DROP_LINE.match(text):
                continue
            is_heading = row["max_size"] >= HEADING_SIZE and bool(RE_SECTION_NO.match(text))
            if is_heading:
                flush()
                section = text
                section_seq += 1
                buf_page = page_index
                continue
            if page_index != buf_page:
                flush()
                buf_page = page_index
            if buf_len + len(text) > MAX_CHUNK_CHARS:
                flush()
                buf_page = page_index
            buf.append(text)
            buf_len += len(text)

    flush()
    doc.close()
    return chunks


def load_markdown(path: Path, meta: dict | None = None) -> list[Chunk]:
    """Extract chunks from a Markdown internal/standard document (## = section)."""

    meta = dict(meta or {})
    doc_id = meta.get("doc_id") or path.stem
    doc_title = meta.get("doc_title") or path.stem
    lines = path.read_text(encoding="utf-8").splitlines()

    chunks: list[Chunk] = []
    section = ""
    seq = 0
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf
        text = "\n".join(buf).strip()
        if text:
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}#s{seq:02d}#c01",
                    doc_id=doc_id,
                    doc_title=doc_title,
                    page=None,
                    section=section or None,
                    text=text,
                    meta={**meta, "doc_type": meta.get("doc_type", "internal")},
                )
            )
        buf = []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            flush()
            section = line[3:].strip()
            seq += 1
            continue
        buf.append(line.lstrip("> ").removeprefix("- ").strip())
    flush()
    return chunks


def load_dir(directory: Path, pattern: str, loader, meta_fn) -> list[Chunk]:
    out: list[Chunk] = []
    for path in sorted(directory.glob(pattern)):
        if path.name.startswith("_"):
            continue
        out.extend(loader(path, meta_fn(path)))
    return out
