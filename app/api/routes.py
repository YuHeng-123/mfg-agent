"""Routes. Deliberately thin: no business logic here."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.api.security import require_admin
from core.agent.loop import ask as run_ask
from core.auth import keys
from core.config import REPORTS_DIR, settings
from core.observability import metrics
from core.store import audit
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


def _caller(request: Request) -> tuple[str, str]:
    """调用方身份。鉴权中间件没装时退到匿名，装了就从 request.state 取。"""

    actor = getattr(request.state, "actor", None) or "anonymous"
    role = getattr(request.state, "role", None) or "anonymous"
    return actor, role


@router.post("/api/ask")
def ask_endpoint(req: AskRequest, request: Request) -> dict:
    if req.domain not in available():
        raise HTTPException(status_code=404, detail=f"unknown domain: {req.domain}")
    # An empty corpus produces refusals that look like a retrieval problem. Say
    # which files are missing instead of answering "I don't know" 52 times.
    from app.boot import issues_for

    problems = issues_for(req.domain)
    if problems:
        raise HTTPException(status_code=503, detail="；".join(problems))
    result = run_ask(
        req.domain,
        req.query,
        {"device_id": req.device_id, "model_id": req.model_id, "fault_code": req.fault_code},
    )
    metrics.record_ask(req.domain, "refused" if result.answer.refusal else "answered")

    body = result.to_dict()
    actor, role = _caller(request)
    try:
        audit.write(
            actor=actor,
            role=role,
            domain=req.domain,
            question=req.query,
            outcome="refused" if result.answer.refusal else "answered",
            refusal_kind=(result.answer.refusal.kind if result.answer.refusal else None),
            citation_ids=[c["chunk_id"] for c in body["citations"]],
            elapsed_ms=body["elapsed_ms"],
            provider=body["provider"],
        )
    except Exception as exc:
        # 没留痕就别应答：宁可这次报错，也不要出现"答了但查无此事"。
        raise HTTPException(status_code=503, detail=f"审计写入失败，已拒绝本次应答：{exc}") from exc
    return body


@router.get("/api/audit")
def audit_log(request: Request, limit: int = 50, actor: str | None = None, domain: str | None = None) -> dict:
    """谁问的、什么时候、问了什么、命中哪些 chunk。

    普通用户只能看自己的记录；管理员可以按 actor 查别人的。
    """

    caller, role = _caller(request)
    if role != "admin":
        actor = caller
    rows = audit.query(limit=limit, actor=actor, domain=domain)
    return {"items": rows, "count": len(rows), "scope": "all" if role == "admin" else "self"}


@router.post("/api/tickets/draft")
def ticket_draft(req: DraftRequest, _admin: None = Depends(require_admin)) -> dict:
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
def gap_record(req: GapRecordRequest, _admin: None = Depends(require_admin)) -> dict:
    from domains.compliance.tools import record_gap

    result = record_gap(
        gap_id=req.gap_id, clause_id=req.clause_id, target_doc=req.target_doc, note=req.note
    )
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error or "record failed")
    return result.data


@router.get("/api/records")
def list_records(kind: str | None = None, status: str | None = None, limit: int = 20) -> dict:
    """Read side of the write path.

    `status` empty and `official=true` returns only what a human signed. The page
    shows both, but never in one column: a draft next to a confirmed record reads
    like the same thing and it is not.
    """

    from core.store import records as store

    return {
        "items": store.list_records(kind=kind, status=status, limit=limit),
        "official": store.list_records(kind=kind, status=status, limit=limit, include_drafts=False),
        "database": str(store.DB_PATH),
    }


class TransitionRequest(BaseModel):
    actor: str = "user"


@router.post("/api/records/{record_id}/confirm")
def confirm_record(
    record_id: int, req: TransitionRequest | None = None, _admin: None = Depends(require_admin)
) -> dict:
    from core.store import records as store

    try:
        return {"record": store.transition(record_id, store.CONFIRMED, actor=(req.actor if req else "user"))}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/records/{record_id}/close")
def close_record(
    record_id: int, req: TransitionRequest | None = None, _admin: None = Depends(require_admin)
) -> dict:
    from core.store import records as store

    try:
        return {"record": store.transition(record_id, store.CLOSED, actor=(req.actor if req else "user"))}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/auth/whoami")
def whoami(request: Request) -> dict:
    """页面用这个判断"要不要弹输入框要 key"。

    没 key 或 key 无效时中间件已经返回 401 了，所以能走到这里就说明认出来了。
    """

    actor, role = _caller(request)
    return {"actor": actor, "role": role, "auth_enabled": settings.auth_enabled}


class IssueKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    role: str = "user"


@router.get("/api/admin/keys")
def list_api_keys(_admin: None = Depends(require_admin)) -> dict:
    return {"items": keys.list_keys()}


@router.post("/api/admin/keys")
def create_api_key(req: IssueKeyRequest, _admin: None = Depends(require_admin)) -> dict:
    """发一把新 key。明文只在这里返回一次，库里只有哈希。"""

    try:
        raw = keys.issue(req.name, req.role)
    except Exception as exc:  # 重名或角色非法
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"name": req.name, "role": req.role, "key": raw, "note": "此 key 只显示这一次，请立即保存"}


@router.post("/api/admin/reload")
def reload_corpus(_admin: None = Depends(require_admin)) -> dict:
    """灌完新手册后调它：清各域缓存 → 重建索引 → 返回自检结果。

    为什么不自动监听文件：自动重载会在"手册复制到一半"的时候把索引建坏，
    而且事后没人说得清是哪一刻变的。显式一次调用，谁改的谁负责。
    """

    from app.boot import warm
    from domains.base import available as names
    from domains.base import load_domain as load

    for name in names():
        load(name).invalidate()

    state = warm()
    return {
        "reloaded": True,
        "index_ready": state["ready"],
        "warm_ms": state["warm_ms"],
        "corpus": state["domains"],
        "issues": state["issues"],
    }


@router.get("/metrics", include_in_schema=False)
def prometheus() -> PlainTextResponse:
    """给 Prometheus 抓的。格式是文本 exposition，不是 JSON。"""

    return PlainTextResponse(metrics.render_prometheus(), media_type="text/plain; version=0.0.4")


@router.get("/api/metrics")
def metrics_json() -> dict:
    """同一批数字的 JSON 版，给页面和人工排查用。"""

    return metrics.snapshot()


@router.get("/api/eval/latest")
def latest_eval() -> dict:
    """The numbers shown in the page footer come from a real report file."""

    # The footer strip wants a *complete* run: both domains, both stages.
    # Ablation files, --stage retrieve runs and --domain equipment sweeps all
    # live in the same folder and have a different shape. Picking the newest
    # file that merely has an equipment half made the page quote a compliance
    # block that was never written, which failed with a KeyError the moment
    # someone ran a single-domain sweep.
    files = sorted(
        f for f in REPORTS_DIR.glob("*.json") if f.name[:8].isdigit() and not f.name.startswith("ablation")
    )
    path = None
    data: dict = {}
    for candidate in reversed(files):
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        eq = payload.get("equipment", {})
        cp = payload.get("compliance", {})
        complete = (
            "retrieval" in eq
            and "answer" in eq
            and "gaps" in cp
            and "answer" in cp
        )
        if complete:
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
            "answered": eq["answer"]["rates"]["answered"],
            "refused": eq["answer"]["rates"]["refused"],
            "multihop_coverage": eq["answer"].get("multihop_coverage", 0.0),
            "singlehop_coverage": eq["answer"].get("singlehop_coverage", 0.0),
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
    from app.boot import health

    h = health()
    from core.agent.providers import provider_status

    return {
        "status": "ok" if h["index_ready"] else "degraded",
        "provider": settings.provider,
        "provider_status": provider_status(),
        "real_provider_ready": settings.real_provider_ready,
        "domains": available(),
        "index_ready": h["index_ready"],
        "warm_ms": h["warm_ms"],
        "corpus": h["domains"],
        "issues": h["issues"],
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
