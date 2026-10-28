"""API key 与两种角色。

为什么是 key 而不是账号密码 + JWT：
  这是给「公司内部试点」用的，用户是维修班组和体系办的人，不是消费者。
  试点阶段要解决的是**谁能写、谁只能读**，不是找回密码。API key 用 30 行能讲清楚，
  JWT 要带上签发、刷新、吊销三件事，这个阶段是负担不是能力。
  要接公司 SSO 时，换掉 `resolve()` 一个函数就够——调用方只拿 actor 和 role。

存的是 SHA-256，不是明文：库被人拷走也拿不到能用的 key。
代价是无法再展示原 key，所以 bootstrap 只在首次启动时打印一次（默认值见 config）。
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
from datetime import datetime

from core.store import records

_LOCK = threading.Lock()
ROLES = ("admin", "user")


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _connect() -> sqlite3.Connection:
    records.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(records.DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL,
                key_hash TEXT NOT NULL UNIQUE,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            """
        )


def bootstrap(admin_key: str, user_key: str) -> list[dict]:
    """首次启动时建两把 key。已有 key 就不动，避免把线上 key 覆盖掉。"""

    init()
    with _LOCK, _connect() as conn:
        existing = conn.execute("SELECT COUNT(*) AS n FROM api_keys").fetchone()["n"]
        if existing:
            return []
        now = datetime.now().isoformat(timespec="seconds")
        created = []
        for name, role, raw in (("admin", "admin", admin_key), ("user", "user", user_key)):
            conn.execute(
                "INSERT INTO api_keys (name, role, key_hash, active, created_at) VALUES (?,?,?,1,?)",
                (name, role, hash_key(raw), now),
            )
            created.append({"name": name, "role": role})
        return created


def issue(name: str, role: str) -> str:
    """管理员新增一把 key，返回明文——只此一次，之后库里只有哈希。"""

    if role not in ROLES:
        raise ValueError(f"role 必须是 {ROLES}")
    raw = f"mfg_{role}_{secrets.token_urlsafe(24)}"
    init()
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO api_keys (name, role, key_hash, active, created_at) VALUES (?,?,?,1,?)",
            (name, role, hash_key(raw), datetime.now().isoformat(timespec="seconds")),
        )
    return raw


def resolve(raw: str | None) -> dict | None:
    """key → {name, role}。查不到或已停用都返回 None，调用方统一按 401 处理。"""

    if not raw:
        return None
    init()
    with _LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT name, role, active FROM api_keys WHERE key_hash = ?", (hash_key(raw),)
        ).fetchone()
    if row is None or not row["active"]:
        return None
    return {"name": row["name"], "role": row["role"]}


def list_keys() -> list[dict]:
    init()
    with _LOCK, _connect() as conn:
        rows = conn.execute("SELECT id, name, role, active, created_at FROM api_keys ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def revoke(name: str) -> bool:
    init()
    with _LOCK, _connect() as conn:
        cur = conn.execute("UPDATE api_keys SET active = 0 WHERE name = ?", (name,))
    return bool(cur.rowcount)


def clear() -> int:
    init()
    with _LOCK, _connect() as conn:
        cur = conn.execute("DELETE FROM api_keys")
    return int(cur.rowcount or 0)


# ---- 公开演示用的只读 key ------------------------------------------------
# 演示站要是先弹一个"请输入访问密钥"，访客就走了。所以演示模式下服务端自己发一把
# role=user 的 key（只能提问和看自己的审计，写操作仍然要 admin），页面启动时自动取。
# 每次重启换一把：旧的自然失效，不需要额外的清理任务。
_DEMO_KEY: str | None = None


def ensure_demo_key() -> str:
    """重建 demo key 并返回明文。只在 MFG_DEMO_MODE=1 时由启动流程调用。"""

    global _DEMO_KEY
    init()
    with _LOCK, _connect() as conn:
        conn.execute("DELETE FROM api_keys WHERE name = 'demo'")
    _DEMO_KEY = issue("demo", "user")
    return _DEMO_KEY


def demo_key() -> str | None:
    return _DEMO_KEY
