<#
.SYNOPSIS
从已有采集报告补齐全部已观察媒体；默认只显示计划，-Execute才下载。
.PARAMETER Report
保留的原始报告，始终只读。
.PARAMETER State
library内的独立补采目录；再次指定相同目录可恢复，禁止同时启动两份。
.PARAMETER Background
隐藏后台运行，日志和PID保存在State内；退出当前终端也可继续。
#>
param([Parameter(Mandatory=$true)][string]$Report,[Parameter(Mandatory=$true)][string]$State,[switch]$Execute,[switch]$Background)
$backfillConfig=Join-Path $PSScriptRoot 'config/topper-us.json'
$backfillArgs=@('-u','-B','-m','listing_ingest.backfill_media','--report',$Report,'--config',$backfillConfig,'--state',$State)
if (-not $Execute) { $backfillArgs+='--plan' }
if ($Background -and $Execute) {
    New-Item -ItemType Directory -Path $State -Force | Out-Null
    # Start-Process的ArgumentList会拼接，逐个引用以兼容有空格的路径。
    $quotedArgs=$backfillArgs | ForEach-Object { '"'+($_ -replace '"','\"')+'"' }
    $backfillProcess=Start-Process -FilePath 'D:\python\python.exe' -ArgumentList $quotedArgs -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $State 'worker.stdout.log') -RedirectStandardError (Join-Path $State 'worker.stderr.log') -PassThru
    @{pid=$backfillProcess.Id;state_directory=$State;started_at=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $State 'worker-process.json') -Encoding utf8
    Write-Output "Background worker PID: $($backfillProcess.Id)"
} else {
    Push-Location -LiteralPath $PSScriptRoot
    try { & 'D:\python\python.exe' @backfillArgs; $backfillCode=$LASTEXITCODE } finally { Pop-Location }
    exit $backfillCode
}
