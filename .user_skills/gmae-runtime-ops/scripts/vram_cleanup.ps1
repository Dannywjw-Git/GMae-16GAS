# vram_cleanup.ps1 - 通用显存清理（大显存场景前调用）
# 设计：释放所有可释放的显存，为生成任务腾出空间
#   1) 停止所有 Ollama LLM 模型（docker exec）
#   2) 可选：重启 ComfyUI 容器释放模型缓存（-RestartComfyUI 参数）
#   3) 确认显存降至阈值以下
# 用法：
#   powershell -ExecutionPolicy Bypass -File vram_cleanup.ps1
#   powershell -ExecutionPolicy Bypass -File vram_cleanup.ps1 -ThresholdMB 6000 -RestartComfyUI
param(
    [int]$ThresholdMB = 4096,
    [switch]$RestartComfyUI
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

Write-Host '=== [1/3] 停止 Ollama 全部 LLM 模型 ==='
foreach ($m in $bigModels) {
    Write-Host ("  docker exec ollama ollama stop " + $m)
    docker exec $ollamaContainer ollama stop $m 2>&1 | ForEach-Object { Write-Host "    $_" }
}
Start-Sleep -Seconds 3

# 可选：重启 ComfyUI 释放模型缓存
if ($RestartComfyUI) {
    Write-Host '=== [2/3] 重启 ComfyUI 释放模型缓存 ==='
    $running = docker ps --filter "name=comfyui" --format '{{.Names}}' 2>$null
    if ($running -eq "comfyui") {
        docker restart comfyui 2>&1 | ForEach-Object { Write-Host "    $_" }
        Start-Sleep -Seconds 5
    } else {
        Write-Host "  comfyui not running, skip"
    }
} else {
    Write-Host '=== [2/3] 跳过 ComfyUI 重启（使用 -RestartComfyUI 可强制释放模型缓存）==='
}

Write-Host '=== [3/3] 显存确认 ==='
$usedMB = 0
$smi = & nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>$null
if ($smi -match '(\d+)') { $usedMB = [int]$Matches[1] }
$totalMB = 16380
$freeMB = $totalMB - $usedMB
Write-Host ("  VRAM used: {0} MiB / free: {1} MiB (threshold: free >= {2} MiB)" -f $usedMB, $freeMB, $ThresholdMB)
if ($freeMB -ge $ThresholdMB) {
    Write-Host '=> GPU ready. Proceed with generation.'
    exit 0
} else {
    Write-Host '=> VRAM still high. Close other GPU apps (browser/WeChat/etc) or use -RestartComfyUI.'
    exit 1
}
