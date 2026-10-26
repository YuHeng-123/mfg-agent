"""Write-side state: what the agent produced, and whether a human signed it.

Reads are free; writes are not. Anything the agent writes starts as a draft and
needs a human to move it along, so the state machine lives in the core rather
than in a domain: "an unconfirmed draft must not appear in the official list" is
one rule, and it must hold for every domain that ever grows a write tool.

Domain-agnostic on purpose — the core never learns what a "ticket" is, it only
knows a record has a kind, a reference and a payload.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from core.config import DATA_DIR

DB_PATH: Path = DATA_DIR / "state.sqlite3"

DRAFT = "draft"
CONFIRMED = "confirmed"
CLOSED = "closed"
TRANSITIONS: dict[str, set[str]] = {
    DRAFT: {CONFIRMED, CLOSED},
    CONFIRMED: {CLOSED},
    CLOSED: set(),
}

_LOCK = threading.Lock()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                ref TEXT NOT NULL DEFAULT '',
                payload TEXT NOT NULL,
                status TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT 'agent',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_records_kind ON records(kind, status)")


def _row_to_dict(row: sqlite3.Row) -> dict:
    payload = json.loads(row["payload"])
    return {
        "id": row["id"],
        "kind": row["kind"],
        "ref": row["ref"],
        "status": row["status"],
        "actor": row["actor"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        **payload,
    }


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create(kind: str, ref: str = "", payload: dict | None = None, actor: str = "agent") -> dict:
    """Every write starts here, and every write starts as a draft."""

    init()
    now = _now()
    body = json.dumps(payload or {}, ensure_ascii=False)
    with _LOCK, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO records (kind, ref, payload, status, actor, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (kind, ref, body, DRAFT, actor, now, now),
        )
        record_id = int(cur.lastrowid)
    return get(record_id) or {"id": record_id, "kind": kind, "status": DRAFT}


def get(record_id: int) -> dict | None:
    init()
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_records(
    kind: str | None = None,
    status: str | None = None,
    limit: int = 20,
    include_drafts: bool = True,
) -> list[dict]:
    """`include_drafts=False` is the official list: only what a human signed.

    The distinction matters more than the filter looks. A draft is what the agent
    *would* do; showing it next to confirmed records in the same table is how a
    suggestion quietly becomes an instruction.
    """

    init()
    sql = "SELECT * FROM records WHERE 1=1"
    args: list = []
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    if status:
        sql += " AND status = ?"
        args.append(status)
    elif not include_drafts:
        sql += " AND status != ?"
        args.append(DRAFT)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with _LOCK, _connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row_to_dict(r) for r in rows]


def transition(record_id: int, to: str, actor: str = "user") -> dict:
    """Move a record, or raise. There is no silent upgrade to confirmed."""

    init()
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(f"no record {record_id}")
        current = row["status"]
        if to not in TRANSITIONS.get(current, set()):
            raise ValueError(f"{current} -> {to} 不允许，允许的是 {sorted(TRANSITIONS.get(current, set()))}")
        conn.execute(
            "UPDATE records SET status = ?, actor = ?, updated_at = ? WHERE id = ?",
            (to, actor, _now(), record_id),
        )
        updated = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
    return _row_to_dict(updated)


def clear() -> int:
    """Test and demo helper: wipe the write side without touching the corpus."""

    init()
    with _LOCK, _connect() as conn:
        cur = conn.execute("DELETE FROM records")
    return int(cur.rowcount or 0)
