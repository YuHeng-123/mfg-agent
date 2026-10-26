# 一键启动：清掉上一次的写入记录 → 起服务 → 开浏览器。
# 用法：powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 [-Port 8010] [-NoBrowser]
param(
    [int]$Port = 8010,
    [switch]$NoBrowser
)

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = "python"
if (-not (Get-Command $py -ErrorAction SilentlyContinue)) { $py = "py" }

Write-Host "== 生成数据（缺失时才跑） ==" -ForegroundColor Cyan
if (-not (Test-Path "data/equipment/manuals/AX300_manual.pdf")) {
    & $py scripts/gen_manuals.py
}
if (-not (Test-Path "data/equipment/tickets/tickets.csv")) {
    & $py scripts/gen_data.py
}

Write-Host "== 清空写入记录 ==" -ForegroundColor Cyan
& $py -c "import sys; sys.path.insert(0,'.'); from core.store import records; print('已清除', records.clear(), '条')"

Write-Host "== 启动服务 http://127.0.0.1:$Port ==" -ForegroundColor Cyan
if (-not $NoBrowser) {
    Start-Job -ScriptBlock { Start-Sleep 3; Start-Process "http://127.0.0.1:$using:Port" } | Out-Null
}
& $py -m uvicorn app.main:app --host 127.0.0.1 --port $Port
