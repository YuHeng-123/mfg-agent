"""FastAPI entry point.

Run:  uvicorn app.main:app --reload --port 8000
Then: http://127.0.0.1:8000/healthz  and  http://127.0.0.1:8000/
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from core.config import ROOT, settings

WEB_DIR = ROOT / "web"

app = FastAPI(
    title="企业知识 Agent · 取用与体检",
    version="0.1.0",
    description="设备运维（取用）与文件体检（体检）共用一套检索 / 编排 / 引用 / 拒答能力层。",
)

app.include_router(router)

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
