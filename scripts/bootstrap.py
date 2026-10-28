"""一键初始化：空目录也能跑起来。

做四件事，每一步都可重复执行（幂等）：
  1. 检查语料在不在，缺了就跑生成脚本（PDF / 工单 / 传感器）
  2. 构建索引并自检，缺文件就报清楚缺哪个
  3. 首次启动时建两把 API key（已存在就不动）
  4. 打印下一步该干什么

退出码：0 表示可以启动；1 表示有问题，别硬启（带着空语料启动，所有回答都会变成拒答，
看起来像"检索效果差"，其实是没数据——这两种故障必须能分开）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.boot import warm  # noqa: E402
from core.auth import keys  # noqa: E402
from core.config import settings  # noqa: E402
from domains.equipment import store as eq_store  # noqa: E402

MANUAL = ROOT / "data" / "equipment" / "manuals" / "AX300_manual.pdf"
TICKETS = ROOT / "data" / "equipment" / "tickets" / "tickets.csv"
STANDARD = ROOT / "data" / "compliance" / "standards" / "GB19001-2026_excerpt.md"


def _run(script: str) -> bool:
    print(f"[init] 生成数据：{script}")
    res = subprocess.run([sys.executable, str(ROOT / "scripts" / script)], cwd=ROOT)
    return res.returncode == 0


def ensure_corpus() -> list[str]:
    """缺什么补什么。返回补不上的东西。"""

    failed: list[str] = []
    if not MANUAL.is_file():
        try:
            import pymupdf  # noqa: F401
        except ImportError:
            failed.append("缺少 pymupdf，无法生成手册 PDF（pip install -r requirements-dev.txt）")
        else:
            if not _run("gen_manuals.py"):
                failed.append("gen_manuals.py 执行失败")
    if not TICKETS.is_file() and not _run("gen_data.py"):
        failed.append("gen_data.py 执行失败")
    if not STANDARD.is_file():
        failed.append("标准节选缺失：data/compliance/standards/GB19001-2026_excerpt.md")
    return failed


def main() -> int:
    print("=" * 60)
    print("mfg-agent 初始化")
    print("=" * 60)

    failed = ensure_corpus()

    state = warm()
    print(
        f"[init] 索引预热 {state['warm_ms']} ms  "
        + "  ".join(f"{k}:{v['chunks']}段" for k, v in state["domains"].items())
    )
    for issue in state["issues"]:
        print(f"[init] ⚠ {issue}")

    created = keys.bootstrap(settings.bootstrap_admin_key, settings.bootstrap_user_key)
    if created:
        print(f"[init] 已创建 API key：{[c['name'] for c in created]}")
        if settings.bootstrap_admin_key == "dev-admin-key":
            print("[init] ⚠ 用的是默认 key，试点前务必设置 MFG_ADMIN_KEY / MFG_USER_KEY")
    else:
        print(f"[init] API key 已存在 {len(keys.list_keys())} 把，不覆盖")

    manuals = eq_store.manual_meta()
    print(f"[init] 手册 {len(manuals)} 本：{', '.join(manuals)}")
    real = eq_store.real_meta()
    if real:
        print(f"[init] 其中真实手册 {len(real)} 本：{', '.join(real)}")

    problems = failed + state["issues"]
    if problems:
        print("\n[init] 初始化未通过：")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("\n[init] 通过。启动：")
    print("  python -m uvicorn app.main:app --host 127.0.0.1 --port 8321")
    print("  页面：http://127.0.0.1:8321  （首次打开会要求填 API key）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
