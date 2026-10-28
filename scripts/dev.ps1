# 一键启动：自检 → 起服务 → 开浏览器。
#   powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 [-Port 8321] [-NoBrowser] [-Python <path>]
#
# 和 check.ps1 一样，需要挑一个装了依赖的解释器：PATH 里的 python 未必是项目用的那套。
param(
    [int]$Port = 8321,
    [switch]$NoBrowser,
    [string]$Python = ""
)

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
            & $c -c "import fastapi, uvicorn, pymupdf" 2>$null
            if ($LASTEXITCODE -eq 0) { return $c }
        } catch { }
    }
    throw "找不到装了 fastapi/uvicorn/pymupdf 的解释器。用 -Python <path> 指定。"
}

$py = Resolve-Python -Explicit $Python
Write-Host "解释器：$py" -ForegroundColor DarkGray

Write-Host "== 初始化（缺数据才生成 + 自检 + 建 key） ==" -ForegroundColor Cyan
& $py scripts/bootstrap.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "初始化未通过，先按上面的提示补齐语料再启动。" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "== 启动服务 http://127.0.0.1:$Port ==" -ForegroundColor Cyan
if (-not $NoBrowser) {
    Start-Job -ScriptBlock { Start-Sleep 4; Start-Process "http://127.0.0.1:$using:Port" } | Out-Null
}
& $py -m uvicorn app.main:app --host 127.0.0.1 --port $Port
