#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI 输出格式化
- table：人类可读表格/摘要（默认）
- json：原始 JSON 输出（脚本集成）
- quiet：仅输出关键信息/ID
"""
import json
import sys
from typing import Optional

# ANSI 颜色
COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "gray": "\033[90m",
}


def _c(text: str, color: str, use_color: bool = True) -> str:
    if not use_color or not sys.stdout.isatty():
        return text
    return COLORS.get(color, "") + text + COLORS["reset"]


def print_json(obj: dict) -> None:
    """输出原始 JSON。"""
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def print_error(msg: str, use_color: bool = True) -> None:
    """输出错误信息到 stderr。"""
    print(_c(f"[错误] {msg}", "red", use_color), file=sys.stderr)


def print_ok(msg: str, use_color: bool = True) -> None:
    """输出成功信息。"""
    print(_c(f"[OK] {msg}", "green", use_color))


def print_warn(msg: str, use_color: bool = True) -> None:
    print(_c(f"[警告] {msg}", "yellow", use_color))


def print_table(headers: list, rows: list, use_color: bool = True) -> None:
    """
    打印对齐表格。
    headers: 列名列表
    rows: 二维列表，每行数据
    """
    if not rows:
        print(_c("（无数据）", "gray", use_color))
        return
    # 计算列宽
    col_widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))
    # 表头
    header_line = "  ".join(
        _c(str(h).ljust(col_widths[i]), "bold", use_color)
        for i, h in enumerate(headers)
    )
    print(header_line)
    print(_c("  ".join("-" * w for w in col_widths), "gray", use_color))
    # 数据行
    for row in rows:
        line = "  ".join(str(row[i]).ljust(col_widths[i]) if i < len(row) else "" for i in range(len(headers)))
        print(line)


def print_kv(data: dict, title: Optional[str] = None, use_color: bool = True) -> None:
    """打印键值对。"""
    if title:
        print(_c(f"\n=== {title} ===", "cyan", use_color))
    if not data:
        print(_c("（无数据）", "gray", use_color))
        return
    max_key = max(len(str(k)) for k in data.keys()) if data else 0
    for k, v in data.items():
        key_str = _c(str(k).ljust(max_key), "bold", use_color)
        print(f"  {key_str}  {v}")


def format_vram_bar(used_gb: float, total_gb: float, width: int = 30, use_color: bool = True) -> str:
    """格式化显存水位条。"""
    ratio = min(used_gb / total_gb, 1.0) if total_gb > 0 else 0
    filled = int(ratio * width)
    bar = "█" * filled + "░" * (width - filled)
    if ratio < 0.6:
        color = "green"
    elif ratio < 0.8:
        color = "yellow"
    else:
        color = "red"
    return _c(bar, color, use_color) + f"  {used_gb:.1f}/{total_gb:.1f} GB ({ratio*100:.0f}%)"


def check_ok(result: dict, quiet: bool = False, use_color: bool = True) -> bool:
    """检查 API 返回是否成功，失败时打印错误。返回是否成功。"""
    if result.get("ok"):
        return True
    err = result.get("error", "未知错误")
    if not quiet:
        print_error(err, use_color)
    return False
