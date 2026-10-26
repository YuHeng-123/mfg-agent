"""Startup: build every index once, and report what is missing instead of 500ing.

Two things this file is for:

1. Warmup. The first question used to pay ~2 s to extract PDFs and build the
   index, which looks like a broken service to anyone clicking the demo first
   thing. The indexes are built at import time now and /healthz says so.
2. Self-check. If someone clones the repo without running the generators, the
   corpus is empty and every answer is a refusal. That is indistinguishable from
   "the retrieval is bad" unless the service says which files are absent.
"""

from __future__ import annotations

import time
from pathlib import Path

from domains.base import available, load_domain

STATE: dict = {
    "ready": False,
    "warm_ms": 0,
    "domains": {},
    "issues": [],
}


def _check_sources(name: str, paths: list[Path]) -> list[str]:
    missing = [str(p) for p in paths if not p.exists()]
    return [f"{name}: 缺少数据文件 {m}" for m in missing]


def warm() -> dict:
    started = time.perf_counter()
    STATE.update({"ready": False, "domains": {}, "issues": []})

    for name in available():
        try:
            domain = load_domain(name)
        except Exception as exc:  # a broken domain must not stop the others
            STATE["issues"].append(f"{name}: 加载失败 {type(exc).__name__}: {exc}")
            continue

        paths = list(domain.sources() or [])
        STATE["issues"].extend(_check_sources(name, paths))

        try:
            began = time.perf_counter()
            index = domain.index()
            chunks = len(getattr(index, "chunks", []) or domain.load_chunks())
            STATE["domains"][name] = {
                "chunks": chunks,
                "build_ms": int((time.perf_counter() - began) * 1000),
                "sources": len(paths),
            }
            if not chunks:
                STATE["issues"].append(f"{name}: 语料为空，检索必然全部拒答")
        except Exception as exc:
            STATE["domains"][name] = {"chunks": 0, "build_ms": 0, "sources": len(paths)}
            STATE["issues"].append(f"{name}: 索引构建失败 {type(exc).__name__}: {exc}")

    STATE["warm_ms"] = int((time.perf_counter() - started) * 1000)
    STATE["ready"] = not STATE["issues"]
    return STATE


def issues_for(name: str) -> list[str]:
    return [i for i in STATE["issues"] if i.startswith(f"{name}:")]


def health() -> dict:
    # Warm on first ask as well as on startup: a TestClient that never entered
    # its context manager runs no startup event, and /healthz must still tell
    # the truth rather than report an index that simply was never built.
    if not STATE["domains"]:
        warm()
    return {
        "index_ready": STATE["ready"] and not STATE["issues"],
        "warm_ms": STATE["warm_ms"],
        "domains": STATE["domains"],
        "issues": STATE["issues"],
    }
