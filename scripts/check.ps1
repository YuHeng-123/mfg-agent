# 一条命令跑完 lint + 测试。
#   powershell -File scripts/check.ps1
#   powershell -File scripts/check.ps1 -Python C:\path\to\python.exe
#
# 为什么要挑解释器：这台机器 PATH 里的 `python` 指向另一套环境，里面没装
# pytest/ruff，直接跑会得到 "No module named ruff" 这种假失败。
param([string]$Python = "")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Resolve-Python {
    param([string]$Explicit)
    $candidates = @()
    if ($Explicit) { $candidates += $Explicit }
    if ($env:PYTHON) { $candidates += $env:PYTHON }
    $candidates += (Join-Path $root ".venv\Scripts\python.exe")
    $candidates += (Join-Path $env:USERPROFILE ".workbuddy\binaries\python\envs\default\Scripts\python.exe")
    $candidates += "python"
    foreach ($c in $candidates) {
        if (-not $c) { continue }
        try {
            & $c -c "import pytest, ruff" 2>$null
            if ($LASTEXITCODE -eq 0) { return $c }
        } catch { }
    }
    throw "找不到装了 pytest 与 ruff 的解释器。用 -Python <path> 指定，或先 pip install -r requirements-dev.txt"
}

$py = Resolve-Python -Explicit $Python
Write-Host "解释器：$py" -ForegroundColor DarkGray

Write-Host "== ruff ==" -ForegroundColor Cyan
& $py -m ruff check .
if ($LASTEXITCODE -ne 0) { Write-Host "ruff 未通过" -ForegroundColor Red; exit $LASTEXITCODE }

Write-Host "== pytest ==" -ForegroundColor Cyan
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { Write-Host "测试未通过" -ForegroundColor Red; exit $LASTEXITCODE }

Write-Host "== 全部通过 ==" -ForegroundColor Green
