<#
.SYNOPSIS
第二阶段API入口。默认只预检；显式-Execute才调用远程模型。
.PARAMETER Report
第一阶段report.json路径。
.PARAMETER Rank
报告内的历史排名，默认1，不是实时排名。
.PARAMETER Config
API配置JSON；省略时使用disabled示例。密钥从配置指定的环境变量读取。
.PARAMETER Policy
可选组件规则；单项覆盖必须绑定当前任务版本和组件ID。
.PARAMETER Output
每次使用新的空输出目录，保留结果和失败记录。
.PARAMETER Execute
真实调用开关，还需配置enabled=true和有效密钥环境变量。
.PARAMETER Encode
分析后使用本地Ollama编码；需与-Execute同时使用。
.NOTES
使用D:/python/python.exe；返回Python退出码，不自动重试。
#>
param(
    [Parameter(Mandatory=$true)][string]$Report,
    [int]$Rank=1,
    [string]$Config,
    [string]$Policy,
    [Parameter(Mandatory=$true)][string]$Output,
    [switch]$Execute,
    [switch]$Encode
)
$env:PYTHONPATH = Join-Path $PSScriptRoot "src"
$env:PYTHONIOENCODING = "utf-8"
if (-not $Config) { $Config = Join-Path $PSScriptRoot "config\model-api.example.json" }
$apiArgs = @("-m", "listing_stage2.api_analysis", "--report", $Report, "--rank", $Rank, "--config", $Config, "--output", $Output)
if ($Policy) { $apiArgs += @("--policy", $Policy) }
if ($Execute) { $apiArgs += "--execute" } else { $apiArgs += "--dry-run" }
if ($Encode) { $apiArgs += "--encode" }
& "D:\python\python.exe" @apiArgs
exit $LASTEXITCODE
