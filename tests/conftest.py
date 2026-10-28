"""Session fixtures: make sure generated data exists before the suite runs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAN = ROOT / "data" / "equipment" / "manuals" / "AX300_manual.pdf"
TICKS = ROOT / "data" / "equipment" / "tickets" / "tickets.csv"


@pytest.fixture(scope="session", autouse=True)
def generated_data() -> None:
    if not MAN.is_file():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_manuals.py")], check=True, cwd=ROOT)
    if not TICKS.is_file():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_data.py")], check=True, cwd=ROOT)


@pytest.fixture(autouse=True)
def isolated_process_state(monkeypatch):
    """每个用例都从干净的配额和指标开始。

    这不是放宽限流——限流规则本身在 test_limits.py 里被测死。
    这里只是不让 A 用例消耗的额度把 B 用例打成 429：
    整个套件共用一个进程，配额是进程级的。

    鉴权默认关掉，同理：除了 tests/test_auth.py，其余用例测的不是"谁能进来"，
    而是各自那份逻辑。鉴权本身有 6 条专门的用例守着（含 401/403 两条路径）。
    """

    from app.main import limiter
    from core.config import settings as cfg
    from core.observability import metrics

    limiter.reset()
    metrics.reset()
    monkeypatch.setattr(cfg, "auth_enabled", False)
    yield
    limiter.reset()
