"""鉴权与角色。认证在中间件里做一次，授权在需要它的端点上单独声明。

为什么分开：
  - **认证**（你是谁）只有一个答案，放中间件，任何 `/api/*` 都过一遍；
  - **授权**（你能不能干这事）是每个端点自己的事，写在端点签名上，
    读代码时不用去翻一张"路径 → 角色"的表，也不会因为加了个新路由忘了登记。

两条角色：
  admin  提问 + 读记录 + 写（工单草稿 / 差距清单 / 确认 / 重载语料 / 发 key）
  user   只能提问 + 读自己的记录

真实部署里"维修工能不能开工单草稿"应该单独一个角色；这里按试点的最小集合来，
在 docs/ops.md 里写明这个取舍。
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from core.auth import keys
from core.config import settings

# 探测类接口不鉴权：K8s 探针和 Prometheus 抓取不该带业务 key。
# 演示 key 的领取口也不鉴权——它发出去的就是一把只读 key，本身没有可保护的东西。
OPEN_PATHS = ("/api/metrics", "/api/auth/demo")
OPEN_PREFIXES = ("/healthz", "/metrics", "/static", "/docs", "/openapi.json", "/redoc")


def is_open(path: str) -> bool:
    return path in OPEN_PATHS or path.startswith(OPEN_PREFIXES) or not path.startswith("/api")


def identify(request: Request) -> dict | None:
    """从请求里认出调用方。没有 key 或 key 无效都返回 None。"""

    raw = request.headers.get("X-API-Key")
    if not raw:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            raw = auth[7:].strip()
    return keys.resolve(raw)


def require_admin(request: Request) -> None:
    if not settings.auth_enabled:
        return
    if getattr(request.state, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="该操作需要管理员权限")
