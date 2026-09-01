#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI 配置管理
- 配置文件：~/.gmae/config.json
- 环境变量覆盖：GMAE_SERVER / GMAE_TOKEN / GMAE_TIMEOUT
"""
import os
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".gmae"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "server": "http://127.0.0.1:8787",
    "token": "",
    "timeout": 30,
    "output": "table",   # table / json / quiet
    "color": True,
}


def load_config() -> dict:
    """加载配置，文件不存在则返回默认值。"""
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                file_cfg = json.load(f)
            cfg.update({k: v for k, v in file_cfg.items() if k in DEFAULT_CONFIG})
        except Exception:
            pass
    # 环境变量覆盖
    if os.environ.get("GMAE_SERVER"):
        cfg["server"] = os.environ["GMAE_SERVER"]
    if os.environ.get("GMAE_TOKEN"):
        cfg["token"] = os.environ["GMAE_TOKEN"]
    if os.environ.get("GMAE_TIMEOUT"):
        try:
            cfg["timeout"] = int(os.environ["GMAE_TIMEOUT"])
        except ValueError:
            pass
    return cfg


def save_config(cfg: dict) -> None:
    """保存配置到文件。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_server_url(cfg: dict, path: str) -> str:
    """拼接完整 URL。"""
    base = cfg["server"].rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return base + path
