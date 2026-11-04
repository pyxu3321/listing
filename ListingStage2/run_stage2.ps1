<#
.SYNOPSIS
历史五商品v2入口；新API流程使用run_api_analysis.ps1。
.PARAMETER MySQL
写旧试验MySQL并验证读回，会产生数据库写入。
.PARAMETER RefreshVectors
从旧项目重建payload和向量，可能调用本地Ollama。
.PARAMETER Payload
指定符合旧契约的已审阅payload，不能与RefreshVectors同时使用。
.NOTES
依赖D:/ListingAnalysis和D:/Crawl4AI；不执行亚马逊发布。
#>
param([switch]$MySQL,[switch]$RefreshVectors,[string]$Payload)
$env:PYTHONPATH = Join-Path $PSScriptRoot "src"
$env:PYTHONIOENCODING = "utf-8"
$stageArgs = @("-m", "listing_stage2")
if ($MySQL) { $stageArgs += "--mysql" }
if ($RefreshVectors) { $stageArgs += "--refresh-vectors" }
if ($Payload) { $stageArgs += @("--payload", $Payload) }
& "D:\python\python.exe" @stageArgs
exit $LASTEXITCODE
