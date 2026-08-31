"""
GMae v0.3.1 — 动态阈值模块（DynamicThresholds）

根据硬件探测结果动态计算显存阈值，替换 v0.3 中硬编码的 16GB / 14GB / 4GB 等数值。

阈值体系（基于总显存百分比，而非固定值）：
- critical: 97% — 超过则强制释放+防死机
- danger:   92% — 超过则自动释放
- warning:  85% — 超过则告警
- safe:     85% — 安全线
- free_target: max(2GB, 15%) — 生成前应释放到的剩余显存

使用方式：
    from thresholds import get_thresholds
    t = get_thresholds()  # 从 hardware_profile.json 加载
    if used_mb > t.danger_mb:
        ...
"""

import json
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class DynamicThresholds:
    vram_total_mb: int
    base_noise_mb: int

    # 百分比阈值
    critical_pct: float = 0.97
    danger_pct: float = 0.92
    warning_pct: float = 0.85
    free_target_pct: float = 0.15
    free_target_min_mb: int = 2048  # 至少保留 2GB

    @property
    def usable_mb(self) -> int:
        """实际可给 AI 负载的显存 = 总显存 - 底噪"""
        return max(0, self.vram_total_mb - self.base_noise_mb)

    @property
    def critical_mb(self) -> int:
        """临界线（MB）：超过则强制释放+防死机"""
        return int(self.vram_total_mb * self.critical_pct)

    @property
    def danger_mb(self) -> int:
        """危险线（MB）：超过则自动释放"""
        return int(self.vram_total_mb * self.danger_pct)

    @property
    def warning_mb(self) -> int:
        """警告线（MB）：超过则告警"""
        return int(self.vram_total_mb * self.warning_pct)

    @property
    def safe_mb(self) -> int:
        """安全线（MB）：低于此值为安全"""
        return int(self.vram_total_mb * self.warning_pct)

    @property
    def free_target_mb(self) -> int:
        """生成前应释放到的剩余显存（MB）"""
        return max(self.free_target_min_mb, int(self.vram_total_mb * self.free_target_pct))

    @property
    def emergency_free_mb(self) -> int:
        """紧急阈值：空闲显存低于此值触发紧急释放（MB）
        对应 v0.3 的 2048MB，动态化为总显存的 12.5%（至少 1GB）"""
        return max(1024, int(self.vram_total_mb * 0.125))

    @property
    def warning_free_mb(self) -> int:
        """警告阈值：空闲显存低于此值触发警告（MB）
        对应 v0.3 的 4096MB，动态化为总显存的 25%（至少 2GB）"""
        return max(2048, int(self.vram_total_mb * 0.25))

    def danger_level(self, free_mb: int) -> str:
        """根据空闲显存返回危险等级：critical / danger / warning / safe"""
        if free_mb < self.emergency_free_mb // 2:  # <6.25% 总显存
            return "critical"
        elif free_mb < self.emergency_free_mb:  # <12.5%
            return "danger"
        elif free_mb < self.warning_free_mb:  # <25%
            return "warning"
        else:
            return "safe"

    def to_dict(self) -> dict:
        return {
            "vram_total_mb": self.vram_total_mb,
            "vram_total_gb": round(self.vram_total_mb / 1024, 1),
            "base_noise_mb": self.base_noise_mb,
            "base_noise_gb": round(self.base_noise_mb / 1024, 2),
            "usable_mb": self.usable_mb,
            "usable_gb": round(self.usable_mb / 1024, 1),
            "critical_mb": self.critical_mb,
            "danger_mb": self.danger_mb,
            "warning_mb": self.warning_mb,
            "free_target_mb": self.free_target_mb,
            "emergency_free_mb": self.emergency_free_mb,
            "warning_free_mb": self.warning_free_mb,
        }


# 全局缓存
_thresholds_cache: Optional[DynamicThresholds] = None
_profile_path: str = ""


def _default_profile_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "resources", "hardware_profile.json"
    )


def get_thresholds(profile_path: Optional[str] = None, force_refresh: bool = False) -> DynamicThresholds:
    """
    获取动态阈值实例（带缓存）。

    优先从 hardware_profile.json 读取；不存在时用默认值（16GB + 1.2GB底噪）。
    server.py 启动时调用一次，后续直接用缓存。

    Args:
        profile_path: hardware_profile.json 路径，默认 resources/hardware_profile.json
        force_refresh: 强制重新读取文件
    """
    global _thresholds_cache, _profile_path
    path = profile_path or _default_profile_path()

    if not force_refresh and _thresholds_cache is not None and _profile_path == path:
        return _thresholds_cache

    vram_total = 16384  # 默认 16GB
    base_noise = 1200   # 默认 1.2GB（v0.3 观察值）

    try:
        with open(path, "r", encoding="utf-8") as f:
            profile = json.load(f)
        gpus = profile.get("gpus", [])
        if gpus:
            primary_idx = profile.get("primary_gpu_index", 0)
            primary = next((g for g in gpus if g.get("index") == primary_idx), gpus[0])
            vram_total = int(primary.get("vram_total_mb", vram_total))
        noise = profile.get("base_noise_mb")
        if noise and isinstance(noise, (int, float)) and noise > 0:
            base_noise = int(noise)
    except Exception:
        pass  # 文件不存在或格式错误，用默认值

    _thresholds_cache = DynamicThresholds(vram_total_mb=vram_total, base_noise_mb=base_noise)
    _profile_path = path
    return _thresholds_cache


def invalidate_cache() -> None:
    """使缓存失效（硬件配置变更后调用）。"""
    global _thresholds_cache
    _thresholds_cache = None


# === 独立运行：python thresholds.py ===
if __name__ == "__main__":
    t = get_thresholds()
    d = t.to_dict()
    print("GMae 动态阈值配置")
    print("=" * 40)
    for k, v in d.items():
        if isinstance(v, float):
            print(f"  {k}: {v}")
        else:
            print(f"  {k}: {v} ({round(v/1024, 1)} GB)")
    print()
    print("16GB 卡示例阈值:")
    print(f"  critical: {int(16384*0.97)} MB ({16384*0.97/1024:.1f} GB)")
    print(f"  danger:   {int(16384*0.92)} MB ({16384*0.92/1024:.1f} GB)")
    print(f"  warning:  {int(16384*0.85)} MB ({16384*0.85/1024:.1f} GB)")
    print(f"  free_target: {max(2048, int(16384*0.15))} MB")
