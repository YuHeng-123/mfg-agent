# 一条命令跑完 lint + 测试。Windows:  powershell -File scripts/check.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = "python"
if (-not (Get-Command $py -ErrorAction SilentlyContinue)) { $py = "py" }

Write-Host "== ruff ==" -ForegroundColor Cyan
& $py -m ruff check .
if ($LASTEXITCODE -ne 0) { Write-Host "ruff 未通过" -ForegroundColor Red; exit $LASTEXITCODE }

Write-Host "== pytest ==" -ForegroundColor Cyan
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { Write-Host "测试未通过" -ForegroundColor Red; exit $LASTEXITCODE }

Write-Host "== 全部通过 ==" -ForegroundColor Green
