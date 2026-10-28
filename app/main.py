"""FastAPI entry point.

Run:  uvicorn app.main:app --reload --port 8000
Then: http://127.0.0.1:8000/healthz  and  http://127.0.0.1:8000/
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.boot import warm
from core.config import ROOT, settings
from core.observability import metrics

WEB_DIR = ROOT / "web"

app = FastAPI(
    title="企业知识 Agent · 取用与体检",
    version="0.1.0",
    description="设备运维（取用）与文件体检（体检）共用一套检索 / 编排 / 引用 / 拒答能力层。",
)

app.include_router(router)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    state = warm()
    print(
        f"[boot] 索引预热 {state['warm_ms']} ms  "
        + "  ".join(f"{k}:{v['chunks']}段" for k, v in state["domains"].items())
        + (f"  ⚠ {len(state['issues'])} 项问题" if state["issues"] else "  自检通过")
    )
    for issue in state["issues"]:
        print(f"[boot]   {issue}")
    yield


app.router.lifespan_context = lifespan


@app.middleware("http")
async def _observe(request, call_next):
    """每个请求记一条：路径、状态码、耗时。

    路径用路由模板而不是原始 URL（`/api/records/{record_id}/confirm` 而不是
    `/api/records/17/confirm`），否则每个 id 都会变成一个独立的时间序列。
    """

    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    metrics.record_http(path, response.status_code, elapsed_ms)
    response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.1f}"
    return response

if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index():
    page = WEB_DIR / "index.html"
    if page.is_file():
        return FileResponse(str(page))
    return {
        "service": "mfg-agent",
        "provider": settings.provider,
        "hint": "web/index.html not generated yet; try /healthz or /docs",
    }
