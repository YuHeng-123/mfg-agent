"""FastAPI entry point.

Run:  uvicorn app.main:app --reload --port 8000
Then: http://127.0.0.1:8000/healthz  and  http://127.0.0.1:8000/
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import security
from app.api.routes import router
from app.boot import warm
from core.auth import keys
from core.auth.limits import RateLimiter
from core.config import ROOT, settings
from core.observability import metrics

WEB_DIR = ROOT / "web"

limiter = RateLimiter(settings.rate_limit_per_minute, settings.rate_limit_per_day)

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
    created = keys.bootstrap(settings.bootstrap_admin_key, settings.bootstrap_user_key)
    if created:
        default = settings.bootstrap_admin_key == "dev-admin-key"
        print(
            f"[boot] 首次启动，已创建 {len(created)} 把 API key"
            + ("（默认 key，试点前必须改 MFG_ADMIN_KEY / MFG_USER_KEY）" if default else "")
        )
    yield


app.router.lifespan_context = lifespan


@app.middleware("http")
async def _guard(request, call_next):
    """认人 → 判配额 → 记账，一个中间件里按顺序做完。

    顺序是有意的：
      1. 先认出调用方（否则配额不知道记在谁头上）；
      2. 再判配额，被拦也照样记一条指标（429 要能在 /metrics 里看到），
         否则"为什么突然没流量了"这个问题在监控上永远查不出来；
      3. 最后按路由模板记账，`/api/records/{id}/confirm` 不会因为 id 不同
         被拆成几百条时间序列。

    认证放这里而不是每个端点上，是因为"你是谁"只有一个答案；
    "你能不能干这事"留给端点自己声明（见 app/api/security.py）。
    """

    started = time.perf_counter()
    path = request.url.path

    caller = None
    if settings.auth_enabled and not security.is_open(path):
        caller = security.identify(request)
        if caller is None:
            request.state.actor, request.state.role = "anonymous", "anonymous"
            response = JSONResponse(
                status_code=401,
                content={"detail": "缺少或无效的 API key（请求头 X-API-Key）"},
            )
            return _finish(request, response, started, path, None)
        request.state.actor, request.state.role = caller["name"], caller["role"]

    identity = caller["name"] if caller else (request.headers.get("X-API-Key") or "anon")
    decision = None
    if settings.rate_limit_enabled and not security.is_open(path):
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
    return _finish(request, response, started, path, decision)


def _finish(request, response, started: float, path: str, decision):
    elapsed_ms = (time.perf_counter() - started) * 1000
    route = request.scope.get("route")
    metrics.record_http(getattr(route, "path", path), response.status_code, elapsed_ms)
    response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.1f}"
    # 响应头只能放 latin-1。actor 可能是中文（"班组A"），直接塞会让整个响应炸掉，
    # 所以百分号编码；要读中文名请调 /api/auth/whoami，别从头里猜。
    response.headers["X-Actor"] = quote(getattr(request.state, "actor", "anonymous") or "anonymous")
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
