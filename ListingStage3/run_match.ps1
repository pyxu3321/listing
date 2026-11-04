<#
.SYNOPSIS
第三阶段本地参考匹配。-Plan不调用模型；正常运行需本地Ollama。
.PARAMETER Request
用户产品资料、卖点、国家、品类、风格和参考用途JSON。
.PARAMETER Config
特征库位置、编码器和检索阈值配置。
.PARAMETER Output
新结果目录；不覆盖已生成的候选包。
#>
param([string]$Request,[string]$Config,[Parameter(Mandatory=$true)][string]$Output,[switch]$Plan)
$env:PYTHONPATH=Join-Path $PSScriptRoot 'src'
$env:PYTHONIOENCODING='utf-8'
if (-not $Request) { $Request=Join-Path $PSScriptRoot 'config/request.example.json' }
if (-not $Config) { $Config=Join-Path $PSScriptRoot 'config/runtime.json' }
$matchArgs=@('-B','-m','listing_stage3','--request',$Request,'--config',$Config,'--output',$Output)
if ($Plan) { $matchArgs+='--plan' }
$taskPython=Join-Path (Split-Path $PSScriptRoot -Parent) 'ListingStage2\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython='D:\python\python.exe' }
& $taskPython @matchArgs
exit $LASTEXITCODE
