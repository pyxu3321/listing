<#
.SYNOPSIS
新版细粒度提取：Prepare只生成任务；发布前必须有逐图及全文审阅JSON。
.PARAMETER AllowPartial
仅用于已明确选择的样本试验；默认缺任何审阅都拒绝发布。
#>
param([Parameter(Mandatory=$true)][string]$Source,
      [Parameter(Mandatory=$true)][string]$Output,
      [string]$Reviews,[string]$StorePath,[string]$Catalog,
      [switch]$Prepare,[switch]$AllowPartial)
$env:PYTHONPATH=Join-Path $PSScriptRoot 'src'
$env:PYTHONIOENCODING='utf-8'
$taskPython=Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython='python' }
$taskArgs=@('-B','-m','listing_stage2.detailed_batch','--source',$Source,'--output',$Output)
if ($Prepare) { $taskArgs+='--prepare' }
if ($AllowPartial) { $taskArgs+='--allow-partial' }
if ($Reviews) { $taskArgs+=@('--reviews',$Reviews) }
if ($StorePath) { $taskArgs+=@('--store-path',$StorePath) }
if ($Catalog) { $taskArgs+=@('--catalog',$Catalog) }
& $taskPython @taskArgs
exit $LASTEXITCODE
