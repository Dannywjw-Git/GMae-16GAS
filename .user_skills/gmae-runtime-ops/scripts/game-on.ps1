# game-on.ps1 - 切换到游戏态：停止 AI 容器 + 释放显存
# 设计：为游戏腾出 GPU 显存和系统资源
#   1) 停止 ComfyUI / Fooocus 等文生图容器
#   2) 卸载全部 Ollama LLM 模型（docker exec）
#   3) 确认显存降至游戏可用水平
# 用法：
#   powershell -ExecutionPolicy Bypass -File game-on.ps1
#   可通过 -ThresholdMB 覆盖阈值：.\game-on.ps1 -ThresholdMB 2048
param(
    [int]$ThresholdMB = 2048
)
$ErrorActionPreference = 'SilentlyContinue'

$ollamaContainer = "ollama"

# 自动定位 GMae 工作区根目录（向上查找包含 AGENTS.md 的目录）
$workspaceRoot = $PSScriptRoot
while ($workspaceRoot -and -not (Test-Path (Join-Path $workspaceRoot "AGENTS.md"))) {
    $parent = Split-Path $workspaceRoot -Parent
    if (-not $parent -or $parent -eq $workspaceRoot) { break }
    $workspaceRoot = $parent
}

# 从 registry.json 读取 LLM 模型列表
$registryPath = Join-Path $workspaceRoot "16gb-ai-studio\vram-console\resources\registry.json"
$bigModels = @()
if (Test-Path $registryPath) {
    try {
        $registry = Get-Content $registryPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $bigModels = $registry.ollama.models | Where-Object { $_.category -eq "llm" } | ForEach-Object { $_.id }
    } catch {
        Write-Host "WARNING: Failed to read registry.json"
    }
}
if ($bigModels.Count -eq 0) {
    $bigModels = @('qwen3.5:9b', 'qwen3:0.6b', 'qwen3.8:27b-rvn-q3km', 'qwen3.8:27b-iq3xxs')
}

Write-Host '=== [1/3] 停止 AI 生成容器 ==='
foreach ($c in @('comfyui', 'fooocus')) {
    $running = docker ps --filter "name=$c" --format '{{.Names}}' 2>$null
    if ($running -eq $c) {
        Write-Host ("  docker stop " + $c)
        docker stop $c 2>&1 | ForEach-Object { Write-Host $_ }
    } else {
        Write-Host ("  " + $c + " not running, skip")
    }
}

Write-Host '=== [2/3] 卸载 Ollama 全部 LLM 模型（docker exec）==='
foreach ($m in $bigModels) {
    Write-Host ('  docker exec ollama ollama stop ' + $m)
    docker exec $ollamaContainer ollama stop $m 2>&1 | ForEach-Object { Write-Host "    $_" }
}
Start-Sleep -Seconds 3

Write-Host '=== [3/3] 显存确认 ==='
$usedMB = 0
$smi = & nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>$null
if ($smi -match '(\d+)') { $usedMB = [int]$Matches[1] }
$totalMB = 16380
$freeMB = $totalMB - $usedMB
Write-Host ("  VRAM used: {0} MiB / free: {1} MiB (threshold: free >= {2} MiB)" -f $usedMB, $freeMB, $ThresholdMB)
if ($freeMB -ge $ThresholdMB) {
    Write-Host '=> GPU ready for gaming. Have fun!'
    exit 0
} else {
    Write-Host '=> VRAM still high. Close other GPU apps (browser/WeChat/etc).'
    exit 1
}
