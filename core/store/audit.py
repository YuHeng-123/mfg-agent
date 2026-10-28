"""审计：谁在什么时候问了什么，命中了哪些段落。

为什么这件事必须在服务端做、而且和 records 共用同一个库：
  - 记录在浏览器里 = 用户想关就关；
  - 记录在日志文件里 = 过了 logrotate 就没了、还查不了；
  - 落表 + 可查询 = 出了事能对着时间和人回溯。

写入是 fail-closed 的：这条插不进去，就说明这次提问没有留痕，
那就别应答（返回 503）。宁可服务报错，也不要出现"答了但查无此事"。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime

from core.store import records

_LOCK = threading.Lock()


def _connect() -> sqlite3.Connection:
    records.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(records.DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                actor TEXT NOT NULL,
                role TEXT NOT NULL,
                domain TEXT NOT NULL,
                question TEXT NOT NULL,
                outcome TEXT NOT NULL,
                refusal_kind TEXT,
                citation_ids TEXT NOT NULL,
                chunk_count INTEGER NOT NULL,
                elapsed_ms INTEGER NOT NULL,
                provider TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit(actor, ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts)")


def write(
    actor: str,
    role: str,
    domain: str,
    question: str,
    outcome: str,
    citation_ids: list[str],
    elapsed_ms: int,
    provider: str,
    refusal_kind: str | None = None,
) -> int:
    init()
    with _LOCK, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO audit (ts, actor, role, domain, question, outcome, refusal_kind,"
            " citation_ids, chunk_count, elapsed_ms, provider) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                datetime.now().isoformat(timespec="seconds"),
                actor,
                role,
                domain,
                question,
                outcome,
                refusal_kind,
                json.dumps(citation_ids, ensure_ascii=False),
                len(citation_ids),
                elapsed_ms,
                provider,
            ),
        )
        return int(cur.lastrowid)


def query(limit: int = 50, actor: str | None = None, domain: str | None = None) -> list[dict]:
    init()
    sql = "SELECT * FROM audit WHERE 1=1"
    args: list = []
    if actor:
        sql += " AND actor = ?"
        args.append(actor)
    if domain:
        sql += " AND domain = ?"
        args.append(domain)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(limit, 500)))
    with _LOCK, _connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [
        {
            # sqlite3.Row 迭代出来是「值」不是「列名」，所以这里必须用 .keys()。
            **{k: row[k] for k in row.keys() if k != "citation_ids"},  # noqa: SIM118
            "citation_ids": json.loads(row["citation_ids"]),
        }
        for row in rows
    ]


def clear() -> int:
    init()
    with _LOCK, _connect() as conn:
        cur = conn.execute("DELETE FROM audit")
    return int(cur.rowcount or 0)
