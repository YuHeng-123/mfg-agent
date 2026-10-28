"""部署产物的静态检查。

**本机没有 docker，所以 `docker compose up` 没有在这里跑过。** 这条要说在前面：
下面的测试只保证"镜像定义没写错路径、compose 文件结构合法、启动命令引用的脚本存在"，
不保证"容器一定能起来"。真正的验证要在有 docker 的机器上做一次，见 docs/ops.md。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "Dockerfile"
COMPOSE = ROOT / "docker-compose.yml"


def test_dockerfile_copies_only_paths_that_exist():
    text = DOCKERFILE.read_text(encoding="utf-8")
    copies = re.findall(r"^COPY\s+(.+)$", text, flags=re.M)
    assert copies, "Dockerfile 里没有 COPY"

    missing = []
    for line in copies:
        parts = [p for p in line.split() if not p.startswith("--")]
        for source in parts[:-1]:  # 最后一个是目标
            if not (ROOT / source).exists():
                missing.append(source)
    assert not missing, f"Dockerfile COPY 了不存在的路径：{missing}"


def test_dockerfile_runs_the_self_check_before_serving():
    text = DOCKERFILE.read_text(encoding="utf-8")
    cmd = next(line for line in text.splitlines() if line.startswith("CMD"))
    assert "scripts/bootstrap.py" in cmd, "启动前要自检，否则空语料会被当成检索效果差"
    assert "uvicorn app.main:app" in cmd
    assert "0.0.0.0" in cmd, "容器里必须绑 0.0.0.0，绑 127.0.0.1 外面进不来"
    assert "HEALTHCHECK" in text


def test_runtime_requirements_include_the_pdf_parser():
    """服务启动时要解析 PDF。pymupdf 只写在 dev 依赖里，镜像会起不来。"""

    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "pymupdf" in reqs


def test_compose_is_wired_to_a_volume_and_a_healthcheck():
    spec = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    app = spec["services"]["app"]

    assert app["ports"] == ["8080:8080"]
    assert app["environment"]["STATE_DB"] == "/state/state.sqlite3"
    assert "state:/state" in app["volumes"]
    assert "healthcheck" in app
    assert "state" in spec["volumes"]


def test_compose_keys_are_not_the_dev_defaults_in_the_example():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "MFG_ADMIN_KEY=" in env_example
    assert "dev-admin-key" not in env_example, "示例文件不该用开发默认 key"
