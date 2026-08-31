#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 模型扫描器模块
- model_scan: 配置驱动的模型扫描（docker_dir + api）
- scan_register: 用户确认后一键登记新模型
- 自动扫描器：ollama 新模型自动登记，标记待验证
"""
import json
import os
import re
import shutil
import threading
import time
import urllib.request
from core.logger import log_event, log_error
from core.config import REGISTRY, BASE_DIR
from core.utils import run_args
from services.ollama import ollama_tags

# ComfyUI 登记模型 → 实际文件关键词映射
COMFY_FILE_MAP = {
    "SDXL": ["sd_xl_base", "sdxl"],
    "Flux-Q5": ["flux1-dev", "flux1"],
    "Music3": ["minimax_music3", "music3"],
    "Wan2.2-TI2V": ["wan2.2_ti2v", "wan2.2"],
}
# ComfyUI 主模型目录
_COMFY_SCAN_DIRS = ["checkpoints", "unet", "diffusion_models"]

# 自动扫描器状态
_last_ollama_tags = set()
_auto_scanner_running = False


def _load_registry():
    """加载 registry.json。"""
    reg_path = os.path.join(BASE_DIR, "resources", "registry.json")
    if os.path.exists(reg_path):
        try:
            with open(reg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _comfy_model_files():
    """扫描 ComfyUI 容器模型目录，返回 {类别: [模型文件名]}。"""
    out = {}
    for d in _COMFY_SCAN_DIRS:
        rc, ls = run_args(["docker", "exec", "comfyui", "sh", "-c", "ls /workspace/models/%s 2>/dev/null" % d], 10)
        if rc != 0:
            continue
        files = [x.strip() for x in ls.splitlines() if x.strip() and not x.startswith("total")]
        files = [f for f in files if f.lower().endswith((".safetensors", ".gguf", ".ckpt", ".bin"))]
        if files:
            out[d] = files
    return out


def _guess_family(fname):
    """按文件名粗判家族：video/music/image。"""
    fl = fname.lower()
    if any(k in fl for k in ("ltx", "hunyuan", "wan2", "wan_", "wav2lip", "videogen")):
        return "video"
    if any(k in fl for k in ("minimax_music", "ace_step", "music", "dav", "suno")):
        return "music"
    return "image"


def _scan_docker_dir(t):
    """扫描容器内模型目录（配置驱动）。"""
    container = t.get("container", t.get("source"))
    base = t.get("base", "/")
    files_by_dir = {}
    for d in t.get("dirs", []):
        rc, ls = run_args(["docker", "exec", container, "sh", "-c", "ls %s/%s 2>/dev/null" % (base, d)], 10)
        if rc != 0:
            continue
        files = [x.strip() for x in ls.splitlines() if x.strip() and not x.startswith("total")]
        files = [f for f in files if f.lower().endswith((".safetensors", ".gguf", ".ckpt", ".bin"))]
        if files:
            files_by_dir[d] = files
    return files_by_dir


def _scan_api(t):
    """HTTP API 拉模型列表（如 ollama /api/tags）。"""
    try:
        with urllib.request.urlopen(t.get("url", ""), timeout=8) as r:
            d = json.loads(r.read().decode("utf-8"))
        return [m.get("name", "") for m in d.get("models", []) if m.get("name")]
    except Exception:
        return []


def model_scan():
    """蓝图§10.3 模型扫描器（配置驱动）：从 registry.scanner.targets 读取扫描目标。
    支持 docker_dir（容器内目录扫描）+ api（HTTP 拉模型列表）。"""
    targets = REGISTRY.get("scanner", {}).get("targets", [])
    sources = {}
    for t in targets:
        if not t.get("enabled", True):
            continue
        source = t.get("source", "?")
        ttype = t.get("type", "docker_dir")
        registered = {m["id"] for m in REGISTRY.get(source, {}).get("models", [])}
        actual, files_by_dir = [], {}
        if ttype == "api":
            actual = _scan_api(t)
        else:
            files_by_dir = _scan_docker_dir(t)
            actual = [f for lst in files_by_dir.values() for f in lst]
        actual = sorted(set(actual))
        kws = t.get("model_keywords", {})
        known = set()
        missing = []
        for rid in sorted(registered):
            rkw = kws.get(rid) or COMFY_FILE_MAP.get(rid) or [rid.lower()]
            hit = [f for f in actual if any(k in f.lower() for k in rkw)]
            if hit:
                known.update(hit)
            else:
                missing.append(rid)
        new_files = [f for f in actual if f not in known]
        default_cat = t.get("default_category", "")
        new_meta = [{"file": f,
                     "category": (_guess_family(f) if _guess_family(f) != "image" else (default_cat or "image")),
                     "dir": next((d for d, lst in files_by_dir.items() if f in lst), "api")}
                    for f in new_files]
        sources[source] = {
            "type": ttype,
            "registered": sorted(registered),
            "actual": actual,
            "known": sorted(known),
            "new": new_meta,
            "missing": missing,
        }
    return {"ok": True, "ts": int(time.time()), "sources": sources}


def scan_register(source, name, vram_gb=None, category="image"):
    """用户确认后把扫描到的新模型写入 registry（蓝图10.3 一键登记）。"""
    global REGISTRY
    if source not in REGISTRY:
        return {"ok": False, "error": "unknown source: " + source + "（请先在 registry.json 中添加该 source 配置）"}
    src = source
    if "models" not in REGISTRY.get(src, {}):
        return {"ok": False, "error": "source has no models list: " + source}
    models = REGISTRY.get(src, {}).get("models", [])
    if any(m.get("id") == name for m in models):
        return {"ok": False, "error": "already registered: " + name}
    if vram_gb is None:
        if src == "ollama":
            vram_gb = _estimate_ollama_vram(name)
        else:
            vram_gb = {"video": 10.0, "music": 6.0, "image": 6.5, "llm": 8.0}.get(category, 6.5)
    entry = {
        "id": name, "name": name, "vram_gb": float(vram_gb),
        "ctx": 8192 if category == "llm" else 0,
        "exclusive": category in ("video", "music"),
        "category": category,
        "full_name": name,
        "vendor": "手动登记",
        "release": "2026",
        "desc": "一键登记，显存为" + ("估算值" if src == "ollama" else "默认值") + "，待实测验证",
        "detail": "由扫描器发现并手动登记",
        "auto_registered": False,
        "vram_verified": False,
        "context_vram": {},
    }
    reg_path = os.path.join(BASE_DIR, "resources", "registry.json")
    bak = reg_path + ".bak_scan"
    try:
        shutil.copyfile(reg_path, bak)
    except Exception:
        pass
    models.append(entry)
    with open(reg_path, "w", encoding="utf-8") as f:
        json.dump(REGISTRY, f, ensure_ascii=False, indent=2)
    REGISTRY = _load_registry()
    log_event("scan_register", source=src, model=name, vram_gb=vram_gb, backup=bak)
    return {"ok": True, "registered": name, "vram_gb": vram_gb, "backup": bak, "source": src}


def _estimate_ollama_vram(name):
    """估算 ollama 模型显存：优先实际文件大小，失败回退模型名参数×量化系数。"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
        for m in d.get("models", []):
            if m.get("name") == name:
                return round(m.get("size", 0) / 1e9 + 0.8, 1)
    except Exception:
        pass
    n = name.lower()
    m = re.search(r'(\d+\.?\d*)b', n)
    params_b = float(m.group(1)) if m else 7.0
    if 'q8' in n or 'f16' in n or 'fp16' in n:
        q = 1.0
    elif 'q4' in n or 'q5' in n or 'q6' in n:
        q = 0.55
    elif 'q3' in n or 'iq3' in n:
        q = 0.4
    else:
        q = 0.75
    return round(params_b * q + 1.0, 1)


def _auto_register_ollama_model(name):
    """自动登记新 ollama 模型（显存估算，标记 auto_registered + vram_verified=false）。"""
    global REGISTRY
    models = REGISTRY.setdefault("ollama", {}).setdefault("models", [])
    if any(m.get("id") == name for m in models):
        return False
    vram = _estimate_ollama_vram(name)
    entry = {
        "id": name, "name": name, "vram_gb": vram,
        "ctx": 8192, "exclusive": False, "category": "llm",
        "full_name": name, "vendor": "自动登记", "release": "2026",
        "desc": "自动扫描登记，显存为估算值，待实测验证",
        "detail": "由自动扫描器发现并登记",
        "auto_registered": True, "vram_verified": False,
        "context_vram": {},
    }
    models.append(entry)
    reg_path = os.path.join(BASE_DIR, "resources", "registry.json")
    try:
        with open(reg_path, "w", encoding="utf-8") as f:
            json.dump(REGISTRY, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_error("auto_register_write_failed", model=name, error=e)
    log_event("auto_register", source="ollama", model=name, vram_gb=vram, note="自动登记，待验证")
    return True


def _auto_scanner_loop():
    """自动扫描器后台线程：每60s轮询ollama list，新模型自动登记；每5min完整扫描。"""
    global _last_ollama_tags, _auto_scanner_running
    _auto_scanner_running = True
    full_scan_counter = 0
    while _auto_scanner_running:
        try:
            current = ollama_tags()
            if current:
                if _last_ollama_tags:
                    new_models = current - _last_ollama_tags
                    for name in sorted(new_models):
                        try:
                            _auto_register_ollama_model(name)
                        except Exception as e:
                            log_error("auto_register_error", model=name, error=e)
                registered = {m.get("id") for m in REGISTRY.get("ollama", {}).get("models", [])}
                unregistered = current - registered
                if unregistered:
                    log_event("auto_scanner_unregistered", count=len(unregistered),
                              models=",".join(sorted(unregistered))[:200])
                    for name in sorted(unregistered):
                        try:
                            _auto_register_ollama_model(name)
                        except Exception as e:
                            log_error("auto_register_error", model=name, error=e)
                _last_ollama_tags = current
            full_scan_counter += 1
            if full_scan_counter >= 5:
                full_scan_counter = 0
                try:
                    result = model_scan()
                    new_count = sum(len(s.get("new", [])) for s in result.get("sources", {}).values())
                    if new_count > 0:
                        log_event("auto_scan_full", new_found=new_count, note="完整扫描发现新文件，待用户确认")
                except Exception as e:
                    log_error("auto_scan_full_error", error=e)
        except Exception as e:
            log_error("auto_scanner_loop_error", error=e)
        time.sleep(60)


def start_auto_scanner():
    """启动自动扫描器后台线程（daemon）。"""
    global _last_ollama_tags
    _last_ollama_tags = ollama_tags()
    t = threading.Thread(target=_auto_scanner_loop, daemon=True, name="auto-scanner")
    t.start()
    log_event("auto_scanner_start", interval_s=60, baseline_models=len(_last_ollama_tags))
