# gpu_release.ps1 - 生成任务前释放显存
# 设计：不杀进程，只卸载 Ollama 模型，确认显存降至阈值后放行
#   1) 卸载全部 Ollama LLM 模型（容器化后用 docker exec）
#   2) 确认显存降至阈值（默认 4GB）
#   3) 不杀 CPU 服务（rerank/embedding 等）
# 用法：
#   powershell -ExecutionPolicy Bypass -File gpu_release.ps1
#   可通过 -ThresholdMB 覆盖阈值：.\gpu_release.ps1 -ThresholdMB 6000
param(
    [int]$ThresholdMB = 4096
)
$ErrorActionPreference = 'SilentlyContinue'

# Ollama 容器名（容器化后用 docker exec 调用 CLI）
$ollamaContainer = "ollama"

# 从 registry.json 读取 LLM 模型列表（配置驱动，消除硬编码）
$registryPath = Join-Path $PSScriptRoot "..\vram-console\resources\registry.json"
$bigModels = @()
if (Test-Path $registryPath) {
    try {
        $registry = Get-Content $registryPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $bigModels = $registry.ollama.models | Where-Object { $_.category -eq "llm" } | ForEach-Object { $_.id }
        Write-Host "Loaded $($bigModels.Count) LLM models from registry.json"
    } catch {
        Write-Host "WARNING: Failed to read registry.json, using fallback list"
    }
}

# 兜底：如果 registry 读取失败，用硬编码列表
if ($bigModels.Count -eq 0) {
    $bigModels = @('qwen3.5:9b', 'qwen3:0.6b', 'qwen3.8:27b-rvn-q3km', 'qwen3.8:27b-iq3xxs')
}

Write-Host '=== [1/2] 卸载 Ollama 全部 LLM 模型（docker exec）==='
foreach ($m in $bigModels) {
    Write-Host ("  docker exec $ollamaContainer ollama stop " + $m)
    docker exec $ollamaContainer ollama stop $m 2>&1 | ForEach-Object { Write-Host "    $_" }
}
Start-Sleep -Seconds 3

Write-Host '=== [2/2] 显存确认 ==='
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
    Write-Host '=> VRAM still high. Check for orphan processes or ComfyUI models.'
    exit 1
}
