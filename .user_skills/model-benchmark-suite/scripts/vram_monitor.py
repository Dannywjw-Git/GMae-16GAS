#!/usr/bin/env python3
"""
VRAM Monitor — 显存峰值监控脚本
用法:
  # 监控指定PID的进程，进程结束自动停止
  python vram_monitor.py --pid 12345 --interval 0.5

  # 监控指定时长（秒）
  python vram_monitor.py --duration 120 --interval 0.5

  # 作为上下文管理器（在其他脚本中调用）
  from vram_monitor import VRAMMonitor
  with VRAMMonitor(interval=0.5) as mon:
      run_generation()
  print(mon.peak_gb, mon.avg_gb)
"""

import argparse
import subprocess
import time
import json
from datetime import datetime


class VRAMMonitor:
    """显存监控器：采样 nvidia-smi，记录峰值/均值/最小值。"""

    def __init__(self, interval=0.5, pid=None, duration=None, output_file=None):
        self.interval = interval
        self.pid = pid
        self.duration = duration
        self.output_file = output_file
        self.samples = []
        self._running = False
        self._start_time = None

    def _query_vram(self):
        """查询当前显存使用量（MiB）。"""
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
        except Exception:
            pass
        return None

    def _is_pid_alive(self):
        """检查目标进程是否还在运行（Windows tasklist）。"""
        if self.pid is None:
            return True
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {self.pid}", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            return str(self.pid) in result.stdout
        except Exception:
            return False

    def start(self):
        """开始监控（阻塞模式，直到停止条件满足）。"""
        self._running = True
        self._start_time = time.time()
        print(f"[VRAM Monitor] 开始监控，间隔={self.interval}s，PID={self.pid or 'N/A'}，时长={self.duration or 'N/A'}s")

        while self._running:
            vram = self._query_vram()
            if vram is not None:
                self.samples.append((time.time() - self._start_time, vram))

            if self.duration and (time.time() - self._start_time) >= self.duration:
                break
            if self.pid and not self._is_pid_alive():
                break

            time.sleep(self.interval)

        self._running = False
        return self.summary()

    def stop(self):
        self._running = False

    def summary(self):
        """返回统计摘要。"""
        if not self.samples:
            return {"peak_mib": 0, "avg_mib": 0, "min_mib": 0, "peak_gb": 0, "avg_gb": 0, "samples": 0, "duration_s": 0}

        values = [v for _, v in self.samples]
        peak = max(values)
        avg = sum(values) / len(values)
        minimum = min(values)
        duration = self.samples[-1][0] if self.samples else 0

        result = {
            "peak_mib": round(peak, 1),
            "avg_mib": round(avg, 1),
            "min_mib": round(minimum, 1),
            "peak_gb": round(peak / 1024, 2),
            "avg_gb": round(avg / 1024, 2),
            "samples": len(self.samples),
            "duration_s": round(duration, 1),
            "timestamp": datetime.now().isoformat(),
        }

        if self.output_file:
            with open(self.output_file, "w") as f:
                json.dump(result, f, indent=2)

        return result

    def __enter__(self):
        import threading
        self._thread = threading.Thread(target=self.start, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *args):
        self.stop()
        self._thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description="VRAM 峰值监控")
    parser.add_argument("--pid", type=int, help="监控目标进程PID，进程结束自动停止")
    parser.add_argument("--duration", type=float, help="监控时长（秒）")
    parser.add_argument("--interval", type=float, default=0.5, help="采样间隔（秒），默认0.5")
    parser.add_argument("--output", "-o", help="输出JSON文件路径")
    parser.add_argument("--json", action="store_true", help="以JSON格式输出结果")
    args = parser.parse_args()

    if not args.pid and not args.duration:
        parser.error("必须指定 --pid 或 --duration 之一")

    monitor = VRAMMonitor(
        interval=args.interval,
        pid=args.pid,
        duration=args.duration,
        output_file=args.output
    )
    result = monitor.start()

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"\n{'='*40}")
        print(f"VRAM 监控结果")
        print(f"{'='*40}")
        print(f"  峰值显存: {result['peak_gb']} GB ({result['peak_mib']} MiB)")
        print(f"  平均显存: {result['avg_gb']} GB ({result['avg_mib']} MiB)")
        print(f"  最低显存: {result['min_mib']} MiB")
        print(f"  采样次数: {result['samples']}")
        print(f"  监控时长: {result['duration_s']} 秒")
        print(f"{'='*40}")


if __name__ == "__main__":
    main()
