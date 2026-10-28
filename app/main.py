"""FastAPI entry point.

Run:  uvicorn app.main:app --reload --port 8000
Then: http://127.0.0.1:8000/healthz  and  http://127.0.0.1:8000/
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.boot import warm
from core.auth.limits import RateLimiter
from core.config import ROOT, settings
from core.observability import metrics

WEB_DIR = ROOT / "web"

limiter = RateLimiter(settings.rate_limit_per_minute, settings.rate_limit_per_day)
# 探测类接口不限额：Prometheus 每 15 秒抓一次，额度不该被它吃掉。
UNLIMITED = ("/healthz", "/metrics", "/api/metrics")

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
    """限流 + 记账，一个中间件里做完。

    顺序是有意的：先判配额，被拦也照样记一条指标（429 要能在 /metrics 里看到），
    否则"为什么突然没流量了"这个问题在监控上永远查不出来。

    路径用路由模板而不是原始 URL（`/api/records/{record_id}/confirm` 而不是
    `/api/records/17/confirm`），否则每个 id 都会变成一个独立的时间序列。
    """

    started = time.perf_counter()
    path = request.url.path
    decision = None
    if settings.rate_limit_enabled and path not in UNLIMITED:
        identity = request.headers.get("X-API-Key") or (request.client.host if request.client else "anon")
        decision = limiter.check(f"{identity}|{path}")

    if decision is not None and not decision.allowed:
        response = JSONResponse(
            status_code=429,
            content={
                "detail": "请求过于频繁，请稍后再试",
                "limit": decision.limit,
                "window": decision.window,
                "retry_after": decision.retry_after,
            },
        )
    else:
        response = await call_next(request)

    elapsed_ms = (time.perf_counter() - started) * 1000
    route = request.scope.get("route")
    metrics.record_http(getattr(route, "path", path), response.status_code, elapsed_ms)
    response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.1f}"
    if decision is not None:
        for key, value in decision.headers().items():
            response.headers[key] = value
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
