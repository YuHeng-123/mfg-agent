"""Tokenisation: three layers, because Chinese has no spaces.

Layer 1  structured tokens  E05 / AX-300 / 0.15MPa / 118℃
Layer 2  CJK character bigrams  排气温度高 -> 排气 气温 温度 度高
Layer 3  latin words

Why bigrams instead of jieba:
  - zero dependency, so the repo runs on a clean machine offline;
  - every hit maps back to a character offset, which the UI needs to highlight;
  - fault codes and model numbers stay intact (jieba would split AX-300).
The cost: more index entries and slightly diluted IDF on long CJK runs. For a
corpus of ~800 short manual paragraphs that cost is irrelevant.
"""

from __future__ import annotations

import re

RE_STRUCT = re.compile(
    r"""
    [A-Za-z]{1,10}\s?[-_]?\s?\d+[A-Za-z0-9._-]*   # E05, AX-300, GB30871-2022, T-0912-014
    |\d+(?:\.\d+)?\s?(?:℃|°C|MPa|kPa|mm/s|mm|m3/h|A|Hz|rpm|kW|h|min|s|%|ppm)  # 0.15MPa, 118℃
    """,
    re.VERBOSE,
)
RE_CJK = re.compile(r"[\u4e00-\u9fa5]+")
RE_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,}")


def _norm_structured(raw: str) -> str:
    return re.sub(r"\s+", "", raw).lower()


def tokenize(text: str) -> list[str]:
    """Return the search tokens for `text` (order preserved, duplicates kept)."""

    if not text:
        return []

    tokens: list[str] = []

    for m in RE_STRUCT.finditer(text):
        tokens.append(_norm_structured(m.group(0)))

    # Remove structured spans before bigramming so that "E05" does not also
    # produce the useless bigram "e0"/"05" noise from its neighbours.
    stripped = RE_STRUCT.sub(" ", text)

    for m in RE_CJK.finditer(stripped):
        run = m.group(0)
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))

    for m in RE_LATIN.finditer(stripped):
        tokens.append(m.group(0).lower())

    return tokens


def bigrams_only(text: str) -> list[str]:
    """CJK bigrams without the structured layer (used for highlight offsets)."""

    out: list[str] = []
    for m in RE_CJK.finditer(text):
        run = m.group(0)
        out.extend(run[i : i + 2] for i in range(max(len(run) - 1, 1)))
    return out
