#!/usr/bin/env python3
"""创作日志记录工具 - 零依赖，仅用 Python 标准库。

用法:
  python log_creation.py --env                    # 采集环境快照
  python log_creation.py --append '{"type":"image",...}'  # 追加记录
  python log_creation.py --recent 10              # 最近10条
  python log_creation.py --type video             # 按类型筛选
  python log_creation.py --stats                  # 统计
  python log_creation.py --compare sage           # SageAttention 对比
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime

LOG_FILE = r"D:\Users\Danny\Documents\GMae_Amanda\16gb-ai-studio\docs\creation-log.jsonl"
COMFY_URL = "http://127.0.0.1:8188/system_stats"


def fetch_comfy_stats():
    """从 ComfyUI API 获取版本信息。"""
    try:
        with urllib.request.urlopen(COMFY_URL, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        sys_info = data.get("system", {})
        return {
            "comfyui_version": sys_info.get("comfyui_version", "unknown"),
            "pytorch_version": sys_info.get("pytorch_version", "unknown"),
        }
    except Exception as e:
        return {"comfyui_version": "unreachable", "pytorch_version": "unreachable", "error": str(e)}


def fetch_gpu_info():
    """用 nvidia-smi 获取 GPU 信息。"""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            return {
                "gpu_model": parts[0] if len(parts) > 0 else "unknown",
                "vram_used_mb": int(parts[1]) if len(parts) > 1 else None,
                "vram_total_mb": int(parts[2]) if len(parts) > 2 else None,
                "driver_version": parts[3] if len(parts) > 3 else "unknown",
            }
    except Exception:
        pass
    return {"gpu_model": "unknown", "vram_used_mb": None, "vram_total_mb": None}


def check_sage_attention():
    """检查 SageAttention 是否启用（容器内 comfyui_args.conf）。"""
    try:
        result = subprocess.run(
            ["docker", "exec", "comfyui", "cat", "/etc/comfyui_args.conf"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            enabled = "--use-sage-attention" in result.stdout
            return {"sage_attention": enabled, "args": result.stdout.strip()}
    except Exception:
        pass
    return {"sage_attention": "unknown"}


def collect_env():
    """采集完整环境快照。"""
    env = {
        "timestamp": datetime.now().isoformat(),
        "comfyui": fetch_comfy_stats(),
        "gpu": fetch_gpu_info(),
    }
    env.update(check_sage_attention())
    return env


def append_record(record_str):
    """追加一条记录到日志文件，自动补全 environment（如果未提供）。"""
    try:
        record = json.loads(record_str)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    # 补全缺失字段
    record.setdefault("timestamp", datetime.now().isoformat())
    record.setdefault("id", datetime.now().strftime("%Y%m%d-%H%M%S"))
    # 自动采集环境信息（如果记录中没有 environment 字段）
    if "environment" not in record:
        record["environment"] = collect_env()

    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"OK: record appended (id={record.get('id')})")
    print(f"    file: {LOG_FILE}")


def read_all_records():
    """读取所有记录。"""
    if not os.path.exists(LOG_FILE):
        return []
    records = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def show_recent(n):
    """显示最近 N 条记录。"""
    records = read_all_records()
    for r in records[-n:]:
        duration = r.get("duration_seconds", "?")
        if isinstance(duration, (int, float)):
            duration = f"{duration}s"
        sage = r.get("environment", {}).get("sage_attention", "?")
        rating = r.get("user_rating", "-")
        print(f"[{r.get('id','?')}] {r.get('type','?'):6s} | {r.get('model','?'):12s} | "
              f"{duration:>6s} | sage={sage} | rating={rating} | {r.get('prompt','')[:40]}")


def show_by_type(rec_type):
    """按类型筛选。"""
    records = [r for r in read_all_records() if r.get("type") == rec_type]
    print(f"共 {len(records)} 条 {rec_type} 记录:")
    for r in records:
        duration = r.get("duration_seconds", "?")
        print(f"  [{r.get('id','?')}] {duration}s | {r.get('model','?')} | {r.get('output_file','')}")


def show_stats():
    """统计信息。"""
    records = read_all_records()
    if not records:
        print("暂无记录")
        return
    by_type = {}
    for r in records:
        t = r.get("type", "unknown")
        dur = r.get("duration_seconds")
        if t not in by_type:
            by_type[t] = {"count": 0, "durations": []}
        by_type[t]["count"] += 1
        if isinstance(dur, (int, float)):
            by_type[t]["durations"].append(dur)
    print(f"总记录数: {len(records)}")
    for t, info in by_type.items():
        durs = info["durations"]
        avg = sum(durs) / len(durs) if durs else 0
        print(f"  {t}: {info['count']} 次, 平均 {avg:.1f}s"
              + (f", 最快 {min(durs):.1f}s, 最慢 {max(durs):.1f}s" if durs else ""))


def compare_sage():
    """对比 SageAttention 开启前后的生成时长。"""
    records = read_all_records()
    on = [r.get("duration_seconds") for r in records
          if r.get("environment", {}).get("sage_attention") is True
          and isinstance(r.get("duration_seconds"), (int, float))]
    off = [r.get("duration_seconds") for r in records
           if r.get("environment", {}).get("sage_attention") is False
           and isinstance(r.get("duration_seconds"), (int, float))]
    print("SageAttention 性能对比:")
    if on:
        print(f"  开启: {len(on)} 次, 平均 {sum(on)/len(on):.1f}s")
    else:
        print("  开启: 无记录")
    if off:
        print(f"  关闭: {len(off)} 次, 平均 {sum(off)/len(off):.1f}s")
    else:
        print("  关闭: 无记录")
    if on and off:
        speedup = sum(off) / len(off) / (sum(on) / len(on))
        print(f"  提速: {speedup:.2f}x")


def main():
    parser = argparse.ArgumentParser(description="AI 创作日志工具")
    parser.add_argument("--env", action="store_true", help="采集环境快照并打印")
    parser.add_argument("--append", type=str, help="追加一条 JSON 记录")
    parser.add_argument("--recent", type=int, metavar="N", help="显示最近 N 条")
    parser.add_argument("--type", type=str, help="按类型筛选 (image/music/video)")
    parser.add_argument("--stats", action="store_true", help="统计信息")
    parser.add_argument("--compare", type=str, choices=["sage"], help="对比分析")
    args = parser.parse_args()

    if args.env:
        print(json.dumps(collect_env(), ensure_ascii=False, indent=2))
    elif args.append:
        append_record(args.append)
    elif args.recent:
        show_recent(args.recent)
    elif args.type:
        show_by_type(args.type)
    elif args.stats:
        show_stats()
    elif args.compare:
        compare_sage()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
