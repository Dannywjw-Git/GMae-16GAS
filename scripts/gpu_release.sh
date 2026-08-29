#!/bin/bash
# gpu_release.sh - 生成任务前释放显存（Linux/macOS）
# 设计：不杀进程，只卸载 Ollama 模型，确认显存降至阈值后放行
# 用法: ./gpu_release.sh [threshold_mb]

THRESHOLD=${1:-4096}

# === 按你的实际模型修改此列表 ===
BIG_MODELS=("qwen3.5:9b" "qwen3:0.6b")

echo "=== [1/2] 卸载 Ollama 全部模型 ==="
for m in "${BIG_MODELS[@]}"; do
  echo "  ollama stop $m"
  ollama stop "$m" 2>&1
done
sleep 3

echo "=== [2/2] 显存确认 ==="
USED_MB=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1)
echo "  VRAM used: ${USED_MB} MiB (threshold: ${THRESHOLD} MiB)"

if [ "${USED_MB}" -le "${THRESHOLD}" ] 2>/dev/null; then
  echo "=> GPU ready. Proceed with generation."
  exit 0
else
  echo "=> VRAM still high. Check for orphan processes."
  exit 1
fi
