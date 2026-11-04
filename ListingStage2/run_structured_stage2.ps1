<#
.SYNOPSIS
整体结构化特征与独立组件写入两个本地向量集合。
.DESCRIPTION
ReviewDirectory必须已有绑定完整来源的JSON语义审阅。本脚本不调用远程LLM。
输出目录使用新的目录；StorePath为本地Qdrant持久化目录。
#>
param(
  [Parameter(Mandatory=$true)][string]$SourceBatch,
  [Parameter(Mandatory=$true)][string]$ReviewDirectory,
  [Parameter(Mandatory=$true)][string]$Output,
  [Parameter(Mandatory=$true)][string]$StorePath
)
$taskPython=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw '请先按docs/整体组件双集合与API.md准备项目独立环境' }
$env:PYTHONPATH=Join-Path $PSScriptRoot 'src'
$env:PYTHONIOENCODING='utf-8'
& $taskPython -B -m listing_stage2.structured_batch --source $SourceBatch --reviews $ReviewDirectory --output $Output --store-path $StorePath
exit $LASTEXITCODE
