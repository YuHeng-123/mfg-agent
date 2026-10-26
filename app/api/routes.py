"""Routes. Deliberately thin: no business logic here."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.agent.loop import ask as run_ask
from core.config import REPORTS_DIR, settings
from domains.base import available, load_domain

router = APIRouter()


class AskRequest(BaseModel):
    domain: str = Field(default="equipment", description="equipment | compliance")
    query: str = Field(min_length=1)
    device_id: str | None = None
    model_id: str | None = None
    fault_code: str | None = None


class DraftRequest(BaseModel):
    device_id: str
    fault_code: str = ""
    symptom: str = ""
    level: str = "P2"


class GapRecordRequest(BaseModel):
    gap_id: str
    clause_id: str = ""
    target_doc: str = ""
    note: str = ""


@router.post("/api/ask")
def ask_endpoint(req: AskRequest) -> dict:
    if req.domain not in available():
        raise HTTPException(status_code=404, detail=f"unknown domain: {req.domain}")
    result = run_ask(
        req.domain,
        req.query,
        {"device_id": req.device_id, "model_id": req.model_id, "fault_code": req.fault_code},
    )
    return result.to_dict()


@router.post("/api/tickets/draft")
def ticket_draft(req: DraftRequest) -> dict:
    """Write path. Always lands as a draft; a human has to confirm it."""

    from domains.equipment.tools import create_ticket_draft

    result = create_ticket_draft(
        device_id=req.device_id,
        fault_code=req.fault_code,
        symptom=req.symptom or "现场报修，待补充现象描述",
        level=req.level,
    )
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error or "draft failed")
    return result.data


@router.post("/api/gaps/record")
def gap_record(req: GapRecordRequest) -> dict:
    from domains.compliance.tools import record_gap

    result = record_gap(
        gap_id=req.gap_id, clause_id=req.clause_id, target_doc=req.target_doc, note=req.note
    )
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error or "record failed")
    return result.data


@router.get("/api/eval/latest")
def latest_eval() -> dict:
    """The numbers shown in the page footer come from a real report file."""

    # The footer strip wants a *complete* run. Ablation files and partial runs
    # (--stage retrieve) live in the same folder and have a different shape, so
    # pick the newest file that actually carries both halves.
    files = sorted(
        f for f in REPORTS_DIR.glob("*.json") if f.name[:8].isdigit() and not f.name.startswith("ablation")
    )
    path = None
    data: dict = {}
    for candidate in reversed(files):
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        eq_ok = "retrieval" in payload.get("equipment", {}) and "answer" in payload.get("equipment", {})
        if eq_ok:
            path, data = candidate, payload
            break
    if path is None:
        return {"available": False}
    out: dict = {
        "available": True,
        "file": path.name,
        "generated_at": data["meta"]["generated_at"],
        "provider": data["meta"]["provider"],
        "code": data["meta"]["code"],
    }
    eq = data.get("equipment", {})
    if "retrieval" in eq and "answer" in eq:
        out["equipment"] = {
            "recall@1": eq["retrieval"]["recall@1"],
            "recall@5": eq["retrieval"]["recall@5"],
            "wrong_model_when_unfiltered": eq["retrieval"]["model_filter"]["without_filter_wrong_model"],
            "refusal_accuracy": eq["answer"]["refusal_accuracy"],
            "over_refusal": eq["answer"]["rates"]["over_refusal"],
        }
    cp = data.get("compliance", {})
    if "gaps" in cp and "answer" in cp:
        out["compliance"] = {
            "gap_recall": cp["gaps"]["gap_recall"],
            "gap_precision": cp["gaps"]["gap_precision"],
            "no_gap_clean": cp["gaps"]["no_gap_clean_rate"],
            "refusal_accuracy": cp["answer"]["refusal_accuracy"],
        }
    return out


@router.get("/healthz")
def healthz() -> dict:
    return {
        "status": "ok",
        "provider": settings.provider,
        "real_provider_ready": settings.real_provider_ready,
        "domains": available(),
        "version": "0.1.0",
    }


@router.get("/api/domains")
def list_domains() -> list[dict]:
    items = []
    for name in available():
        d = load_domain(name)
        items.append({"name": d.name, "label": d.label})
    return items


@router.get("/api/domain/{name}/stats")
def domain_stats(name: str) -> dict:
    try:
        d = load_domain(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    chunks = d.load_chunks()
    return {
        "name": d.name,
        "label": d.label,
        "chunks": len(chunks),
        "tools": sorted(d.tools().keys()),
        "safety_rules": len(d.safety_rules()),
        "eval_items": len(d.eval_items()),
    }
