"""账号体系：两个角色，四件事必须成立。

1. 没 key / 错 key → 401（不是"匿名也能问"）
2. 普通用户提问 → 200
3. 普通用户写（工单草稿/差距清单/确认） → 403
4. 管理员写 → 200
外加两条：key 在库里存哈希不是明文；bootstrap 不会覆盖已有 key。
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app
from core.auth import keys
from core.config import settings
from core.store import records

ADMIN = {"X-API-Key": "test-admin-key"}
USER = {"X-API-Key": "test-user-key"}
ASK = {"domain": "equipment", "query": "AX300 报 E05 怎么处理"}


@pytest.fixture
def auth_on(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(records, "DB_PATH", tmp_path / "state.sqlite3")
    keys.clear()
    keys.bootstrap("test-admin-key", "test-user-key")
    yield
    keys.clear()


def test_missing_key_is_401(auth_on):
    client = TestClient(app)
    res = client.post("/api/ask", json=ASK)
    assert res.status_code == 401
    assert "API key" in res.json()["detail"]


def test_wrong_key_is_401(auth_on):
    client = TestClient(app)
    res = client.post("/api/ask", json=ASK, headers={"X-API-Key": "not-a-real-key"})
    assert res.status_code == 401


def test_bearer_header_also_works(auth_on):
    client = TestClient(app)
    res = client.post("/api/ask", json=ASK, headers={"Authorization": "Bearer test-user-key"})
    assert res.status_code == 200


def test_user_can_ask_but_cannot_write(auth_on):
    client = TestClient(app)
    assert client.post("/api/ask", json=ASK, headers=USER).status_code == 200

    draft = client.post(
        "/api/tickets/draft",
        json={"device_id": "AC-300-03", "fault_code": "E05", "symptom": "排气温度高"},
        headers=USER,
    )
    assert draft.status_code == 403
    assert "管理员" in draft.json()["detail"]


def test_admin_can_write(auth_on):
    client = TestClient(app)
    draft = client.post(
        "/api/tickets/draft",
        json={"device_id": "AC-300-03", "fault_code": "E05", "symptom": "排气温度高"},
        headers=ADMIN,
    )
    assert draft.status_code == 200
    assert draft.json()["draft"]["status"] == "draft"


def test_user_cannot_reload_corpus(auth_on):
    client = TestClient(app)
    assert client.post("/api/admin/reload", headers=USER).status_code == 403
    assert client.post("/api/admin/reload", headers=ADMIN).status_code == 200


def test_whoami_reports_the_role(auth_on):
    client = TestClient(app)
    assert client.get("/api/auth/whoami", headers=ADMIN).json()["role"] == "admin"
    assert client.get("/api/auth/whoami", headers=USER).json()["role"] == "user"
    assert client.get("/api/auth/whoami").status_code == 401


def test_keys_are_stored_as_hashes(auth_on, tmp_path):
    with sqlite3.connect(tmp_path / "state.sqlite3") as conn:
        rows = conn.execute("SELECT name, key_hash FROM api_keys").fetchall()
    stored = " ".join(h for _, h in rows)
    assert "test-admin-key" not in stored and "test-user-key" not in stored
    assert all(len(h) == 64 for _, h in rows), "应存 sha256 十六进制"


def test_bootstrap_does_not_overwrite_existing_keys(auth_on):
    assert keys.bootstrap("another-admin", "another-user") == []
    # 原 key 仍然可用
    assert keys.resolve("test-admin-key")["role"] == "admin"


def test_issued_key_works_and_is_listed(auth_on):
    client = TestClient(app)
    created = client.post("/api/admin/keys", json={"name": "班组A", "role": "user"}, headers=ADMIN).json()
    assert created["key"].startswith("mfg_user_")

    fresh = client.post("/api/ask", json=ASK, headers={"X-API-Key": created["key"]})
    assert fresh.status_code == 200

    listed = client.get("/api/admin/keys", headers=ADMIN).json()["items"]
    assert any(k["name"] == "班组A" and k["role"] == "user" for k in listed)
    # 列表里不能出现 key 本身
    assert all("key" not in k or k["key"] is None for k in listed)
