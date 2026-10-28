#!/usr/bin/env bash
# 一条命令跑完 lint + 测试：bash scripts/check.sh
# 想指定解释器：PYTHON=/path/to/python bash scripts/check.sh
set -euo pipefail
cd "$(dirname "$0")/.."

pick_python() {
    for candidate in "${PYTHON:-}" ".venv/bin/python" "$HOME/.workbuddy/binaries/python/envs/default/bin/python" python3 python; do
        [ -z "$candidate" ] && continue
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c "import pytest, ruff" >/dev/null 2>&1; then
                echo "$candidate"
                return 0
            fi
        fi
    done
    echo "找不到装了 pytest 与 ruff 的解释器。用 PYTHON=<path> 指定，或先 pip install -r requirements-dev.txt" >&2
    return 1
}

PY="$(pick_python)"
echo "解释器：$PY"

echo "== ruff =="
"$PY" -m ruff check .

echo "== pytest =="
"$PY" -m pytest -q

echo "== 全部通过 =="
