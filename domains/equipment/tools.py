"""The four equipment tools.

Rule the whole repo follows: a tool may return data with an empty citation list,
but it must return a ToolResult. If it has evidence, the evidence travels in
`citations`, and the core checks every claim against exactly that set.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import re
import time
from datetime import datetime
from pathlib import Path

from core.store import records
from core.types import Citation, EvidenceStats, ToolResult
from domains.equipment import store

SENSOR_THRESHOLD_KEYS = {
    "temp_c": ("exhaust_temp_c", "bearing_temp_c"),
    "vibration_mm_s": ("vibration_mm_s",),
    "current_a": ("current_a",),
}


def _timed(fn):
    """Time the call and never raise.

    functools.wraps matters more than it looks: the loop binds arguments by
    inspecting the tool signature, so a wrapper that swallows the signature would
    silently send every tool an empty argument list.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> ToolResult:
        started = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:  # a tool must never take the loop down
            return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    return wrapper


@_timed
def search_manual(query: str, model_id: str | None = None, top_k: int = 5) -> ToolResult:
    ix = store.index()
    family = None
    if model_id is None:
        model_id = store.resolve_model(query, store.resolve_device(query))
        if model_id is None:
            family = store.resolve_models(query)
    hits = ix.search(query, top_k=top_k, model_id=model_id, model_ids=family)
    stats = ix.query_stats(query)

    # An explicit model code that does not exist in the library is the clearest
    # possible signal that we have nothing to say, so collect it here instead of
    # hoping the score happens to come out low.
    unknowns = [
        code
        for code in re.findall(r"\b(AX\d{3}|BP\d{4}|HE\d{3})\b", query.upper())
        if code not in {m["model_id"] for m in store.MANUAL_META.values()}
    ]

    citations = []
    payload = []
    for hit in hits:
        c = hit.chunk
        citations.append(dataclasses.replace(c.cite(), score=round(hit.score, 4)))
        payload.append(
            {
                "chunk_id": c.chunk_id,
                "doc_title": c.doc_title,
                "page": c.page,
                "section": c.section,
                "score": round(hit.score, 3),
                "text": c.text[:400],
            }
        )

    return ToolResult(
        ok=True,
        data={
            "model_id": model_id,
            "query_stats": {
                "matched_terms": stats.matched_terms,
                "matched_mass": stats.matched_mass,
                "terms": stats.terms[:8],
            },
            "hits": payload,
        },
        citations=citations,
        evidence=EvidenceStats(
            matched_terms=stats.matched_terms,
            matched_mass=stats.matched_mass,
            hit_count=len(hits),
            unknowns=tuple(unknowns),
        ),
        note=f"命中 {len(hits)} 段，型号过滤={model_id or ("、".join(family) if family else '未指定')}",
    )


@_timed
def get_ticket_history(
    fault_code: str, model_id: str | None = None, limit: int = 3, query: str = ""
) -> ToolResult:
    if model_id is None:
        model_id = store.resolve_model(query or fault_code, store.resolve_device(query))
    rows = store.lookup_tickets(fault_code, model_id=model_id, limit=limit)
    citations = [
        Citation(
            chunk_id=t["ticket_id"],
            doc_title="历史工单",
            section=f"{t['fault_code']} {t['symptom'][:14]}",
            snippet=f"{t['action']}｜{t['hours']} h｜{t['result']}",
            kind="ticket",
        )
        for t in rows
    ]
    same_model = [t for t in rows if model_id and t["model_id"] == model_id]
    hours = [float(t["hours"]) for t in same_model] or [float(t["hours"]) for t in rows]
    return ToolResult(
        ok=bool(rows),
        data={
            "fault_code": fault_code.upper(),
            "model_id": model_id,
            "tickets": rows,
            "same_model_count": len(same_model),
            "avg_hours": round(sum(hours) / len(hours), 1) if hours else None,
        },
        citations=citations,
        error=None if rows else "no ticket with this fault code",
        note=f"同故障码 {len(rows)} 条，同型号 {len(same_model)} 条"
        + (f"，平均 {round(sum(hours) / len(hours), 1)} h" if hours else ""),
    )


@_timed
def get_device_state(device_id: str | None = None, query: str = "") -> ToolResult:
    device_id = store.resolve_device(query, device_id)
    if not device_id:
        return ToolResult(ok=False, error="无法从问题中识别设备，未取到实时读数")
    device = store.devices().get(device_id)
    if not device:
        return ToolResult(ok=False, error=f"unknown device: {device_id}")
    reading = store.latest_reading(device_id)
    if not reading:
        return ToolResult(ok=False, error=f"no sensor data for {device_id}")

    thresholds = device.get("thresholds", {})
    readings = []
    exceeded = []
    for field, keys in SENSOR_THRESHOLD_KEYS.items():
        raw = reading.get(field)
        if raw is None:
            continue
        value = float(raw)
        limit = next((thresholds[k] for k in keys if k in thresholds), None)
        over = limit is not None and value > limit
        readings.append(
            {"field": field, "value": value, "limit": limit, "exceeded": over, "unit": _unit(field)}
        )
        if over:
            exceeded.append(f"{_label(field)} {value}{_unit(field)} 超过阈值 {limit}{_unit(field)}")

    citation = Citation(
        chunk_id=f"sensor:{device_id}:{reading['ts']}",
        doc_title=f"{device['name']} 传感器",
        section=reading["ts"],
        snippet="；".join(
            f"{_label(r['field'])} {r['value']}{r['unit']}"
            + (f"（阈值 {r['limit']}{r['unit']}，超标）" if r["exceeded"] else "")
            for r in readings
        ),
        kind="sensor",
    )
    return ToolResult(
        ok=True,
        data={
            "device": device,
            "ts": reading["ts"],
            "readings": readings,
            "exceeded": exceeded,
        },
        citations=[citation],
        note=f"{device['name']} @ {reading['ts']}，"
        + (f"{len(exceeded)} 项超标" if exceeded else "全部在阈值内"),
    )


@_timed
def create_ticket_draft(
    device_id: str,
    fault_code: str,
    symptom: str,
    level: str = "P2",
    confirmed: bool = False,
) -> ToolResult:
    """Draft a maintenance ticket. The agent never decides it is confirmed.

    `confirmed=True` is accepted from the caller because the API exposes it, but
    the record starts as a draft in the store either way: the state machine owns
    the status, not the argument.
    """

    device = store.devices().get(device_id, {})
    ticket_id = f"D{datetime.now():%Y%m%d%H%M%S}"
    payload = {
        "ticket_id": ticket_id,
        "device_id": device_id,
        "device_name": device.get("name"),
        "line": device.get("line"),
        "fault_code": fault_code.upper(),
        "symptom": symptom,
        "level": level,
        "created_by": "agent",
    }
    record = records.create("ticket", ref=ticket_id, payload=payload)
    if confirmed:
        record = records.transition(record["id"], records.CONFIRMED, actor="api")
    return ToolResult(
        ok=True,
        data={
            "draft": record,
            "stored": True,
            "needs_confirmation": record["status"] == records.DRAFT,
        },
        citations=[],
    )


def _unit(field: str) -> str:
    return {"temp_c": "℃", "vibration_mm_s": "mm/s", "current_a": "A"}.get(field, "")


def _label(field: str) -> str:
    return {"temp_c": "温度", "vibration_mm_s": "振动", "current_a": "电流"}.get(field, field)


TOOLS = {
    "search_manual": {
        "fn": search_manual,
        "description": "检索设备手册段落，返回带页码与章节的原文片段。model_id 会做硬过滤，禁止跨型号检索。",
        "read_only": True,
        "parallel_safe": True,
        "primary": True,
        "trigger": None,
    },
    "get_ticket_history": {
        "fn": get_ticket_history,
        "description": "查同故障码的历史工单，返回处置动作、用时与结果。",
        "read_only": True,
        "parallel_safe": True,
        "primary": False,
        "trigger": r"[A-Z]\d{2}\b",
    },
    "get_device_state": {
        "fn": get_device_state,
        "description": "查设备档案与最新传感器读数，并与档案阈值对比。",
        "read_only": True,
        "parallel_safe": True,
        "primary": False,
        "trigger": r"(报警|超标|温度|振动|电流|读数|[A-Z]{2}-\d{4}-\d{2})",
    },
    "create_ticket_draft": {
        "fn": create_ticket_draft,
        "description": "生成工单草稿，须人工确认后才算正式工单。",
        "read_only": False,
        "parallel_safe": False,
        "primary": False,
        "trigger": None,
    },
}
