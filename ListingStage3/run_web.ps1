<#
.SYNOPSIS
启动真实特征库的本机测试前端。浏览不需要模型，匹配需要 Ollama 在线。
.PARAMETER Port
仅监听本机的端口，默认 8765。
.PARAMETER Config
复用第三阶段运行配置，默认 config/runtime.json。
#>
param([int]$Port=8765,[string]$Config)
$env:PYTHONPATH=Join-Path $PSScriptRoot 'src'
$env:PYTHONIOENCODING='utf-8'
if (-not $Config) { $Config=Join-Path $PSScriptRoot 'config/runtime.json' }
$taskPython=Join-Path (Split-Path $PSScriptRoot -Parent) 'ListingStage2\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython='python' }
& $taskPython -B -m listing_stage3.web --config $Config --port $Port
exit $LASTEXITCODE
