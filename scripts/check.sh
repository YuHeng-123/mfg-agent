#!/usr/bin/env bash
# 一条命令跑完 lint + 测试：bash scripts/check.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"

echo "== ruff =="
"$PY" -m ruff check .

echo "== pytest =="
"$PY" -m pytest -q

echo "== 全部通过 =="
