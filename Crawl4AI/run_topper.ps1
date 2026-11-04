<#
.SYNOPSIS
单来源采集启动器。正常启动会真实访问Amazon；-CheckEnvironment只检查依赖。
.PARAMETER MaxProducts
商品详情采集数量上限，默认50，范围0到50；0不代表完全离线，仍可能读取榜单。
.PARAMETER Python
可选Python解释器路径；省略时依次探测项目环境和系统解释器。
.PARAMETER CheckEnvironment
仅打印实际Python及依赖版本，不启动采集器。
.NOTES
当前入口读取config/topper-us.json；多来源使用python -m listing_ingest.sources。
Push-Location/Pop-Location保证相对路径基于项目目录且退出后恢复工作目录。
#>
param(
    [ValidateRange(0, 50)]
    [int]$MaxProducts = 50,
    [string]$Python,
    [switch]$CheckEnvironment
)

$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $taskCandidates = @()
    if ($Python) { $taskCandidates += $Python }
    $taskCandidates += (Join-Path $PSScriptRoot '.venv\Scripts\python.exe')
    $taskConfigPath = Join-Path $PSScriptRoot '.venv\pyvenv.cfg'
    if (Test-Path -LiteralPath $taskConfigPath) {
        $taskHomeLine = Get-Content -LiteralPath $taskConfigPath | Where-Object { $_ -match '^home\s*=\s*(.+)$' } | Select-Object -First 1
        if ($taskHomeLine -match '^home\s*=\s*(.+)$') { $taskCandidates += (Join-Path $Matches[1].Trim() 'python.exe') }
    }
    $taskSystemPython = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($taskSystemPython) { $taskCandidates += $taskSystemPython.Source }
    $taskPython = $null
    foreach ($taskCandidate in ($taskCandidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $taskCandidate)) { continue }
        & $taskCandidate -c "import importlib.util,sys; sys.exit(0 if all(importlib.util.find_spec(n) for n in ['crawl4ai','aiohttp','bs4','PIL']) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $taskPython = $taskCandidate; break }
    }
    if (-not $taskPython) { throw 'No Python with Crawl4AI dependencies was found. Install the project dependencies or pass -Python.' }
    Write-Host "Using Python: $taskPython"
    if ($CheckEnvironment) {
        & $taskPython -c "import sys,json,importlib.metadata as m; print(json.dumps({'python':sys.executable,'versions':{p:m.version(p) for p in ['crawl4ai','playwright','aiohttp','pillow']}},indent=2))"
    } else {
        & $taskPython -m listing_ingest --max-products $MaxProducts
    }
    $taskExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $taskExitCode
