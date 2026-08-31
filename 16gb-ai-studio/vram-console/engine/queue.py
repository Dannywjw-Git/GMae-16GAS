#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 任务队列模块
- 16G 单卡串行化：提交→排队→预检→释放→加载→生成→完成
- 生成时间统计（预演模式"预计时间"用）
"""
import json
import os
import threading
import time
import uuid
import urllib.request
from collections import deque
from core.logger import log_event, log_error
from core.config import REGISTRY, BASE_DIR
from core.registry import registry
from engine.budget import budget_engine
from core.exceptions import ConfigError
from engine.gen_stats import load_gen_stats, save_gen_stats, update_gen_stats
from engine.eviction_guard import gpu_guard_evict

# 队列状态 — 已迁移到 registry（状态包装）
_QUEUE_CLIENT_ID = str(uuid.uuid4())
_queue_state = registry.get("queue_state")
if _queue_state is None:
    _queue_state = {
        "tasks": {},
        "task_queue": deque(),
        "worker_alive": False,
    }
    registry.set("queue_state", _queue_state)

# 可变对象直接引用（修改字段不需要 global）
_tasks = _queue_state["tasks"]
_task_queue = _queue_state["task_queue"]
_task_lock = threading.Lock()

# 生成时间统计


def _load_workflow(workflow_name):
    """读取工作流模板（vram-console/workflows/ 下），返回 dict；失败返回 None。"""
    p = os.path.join(BASE_DIR, "workflows", workflow_name)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception as e:
        raise ConfigError("工作流模板解析失败: %s" % workflow_name, detail={"file": p}) from e


def _apply_params(wf, params):
    """按 input 名匹配替换模板参数（不硬编码节点号）。"""
    wf = json.loads(json.dumps(wf))
    prompt_done = False
    for node in wf.values():
        ins = node.get("inputs")
        if not isinstance(ins, dict):
            continue
        if "prompt" in params and not prompt_done:
            if "text" in ins:
                ins["text"] = params["prompt"]
                prompt_done = True
            elif "caption" in ins:
                ins["caption"] = params["prompt"]
                prompt_done = True
        if "seed" in params and "seed" in ins:
            ins["seed"] = int(params["seed"])
        if "width" in params and "width" in ins:
            ins["width"] = int(params["width"])
        if "height" in params and "height" in ins:
            ins["height"] = int(params["height"])
        if "filename_prefix" in params and "filename_prefix" in ins:
            ins["filename_prefix"] = params["filename_prefix"]
    return wf


def queue_enqueue(model: str, params: dict) -> dict:
    """提交任务入队。model=registry comfyui 模型 id；params={prompt,seed,width,height,...}"""
    m = next((x for x in REGISTRY.get("comfyui", {}).get("models", []) if x["id"] == model), None)
    if not m:
        return {"ok": False, "error": "unknown model: " + model}
    wf_name = m.get("workflow")
    if not wf_name or not _load_workflow(wf_name):
        return {"ok": False, "error": "工作流模板缺失: %s（需先在 ComfyUI 前端导出到 vram-console/workflows/）" % wf_name}
    tid = uuid.uuid4().hex[:10]
    task = {
        "id": tid, "model": model, "workflow": wf_name,
        "params": {k: v for k, v in (params or {}).items()},
        "status": "queued", "progress": "", "prompt_id": None,
        "created": int(time.time()), "started": None, "ended": None, "error": "",
        "result": None,
    }
    with _task_lock:
        _tasks[tid] = task
        _task_queue.append(tid)
    if not _queue_state["worker_alive"]:
        _queue_state["worker_alive"] = True
        threading.Thread(target=_queue_worker, daemon=True).start()
    log_event("queue_enqueue", task=tid, model=model, workflow=wf_name)
    return {"ok": True, "task": task}


def _queue_submit_comfy(wf):
    """POST ComfyUI /prompt 提交工作流，返回 prompt_id / 错误。"""
    payload = {"prompt": wf, "client_id": _QUEUE_CLIENT_ID}
    try:
        req = urllib.request.Request("http://127.0.0.1:8188/prompt",
                                     data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode("utf-8"))
        return d.get("prompt_id"), None
    except Exception as e:
        return None, str(e)


def _queue_wait(prompt_id, task, timeout=3600):
    """轮询 /history/{prompt_id} 直到 success/error，回填进度。"""
    url = "http://127.0.0.1:8188/history/%s" % prompt_id
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                h = json.loads(r.read().decode("utf-8"))
            if prompt_id in h:
                st = h[prompt_id].get("status", {})
                s = st.get("status_str")
                if s == "success":
                    raw_outputs = h[prompt_id].get("outputs") or {}
                    images = []
                    for node_id, node_out in raw_outputs.items():
                        for img in (node_out.get("images") or []):
                            fname = img.get("filename", "")
                            sub = img.get("subfolder", "")
                            ftype = img.get("type", "output")
                            url = "http://127.0.0.1:8188/view?filename={}&subfolder={}&type={}".format(
                                fname, sub, ftype)
                            images.append({"filename": fname, "subfolder": sub, "type": ftype, "url": url, "node": node_id})
                    task["result"] = {"outputs": list(raw_outputs.keys()), "images": images}
                    return "done"
                if s == "error":
                    task["error"] = "comfy_error: " + json.dumps(st.get("messages", [])[-1:] if st.get("messages") else {})
                    return "failed"
        except Exception:
            pass
        time.sleep(3)
    return "failed"


def _run_task(task):
    """执行单个任务：预检 → 释放 → 提交 → 等待完成。"""
    try:
        task["status"] = "precheck"
        m = next((x for x in REGISTRY.get("comfyui", {}).get("models", []) if x["id"] == task["model"]), None)
        if m:
            dec = None
            for bm in budget_engine().get("models", []):
                if bm["id"] == task["model"]:
                    dec = bm
                    break
            if dec and dec["decision"] == "reject":
                task["status"] = "failed"
                task["error"] = "预检拒绝：%s" % dec["note"]
                return
            if dec and dec["decision"].startswith("free"):
                task["status"] = "freeing"
                task["progress"] = "释放 L1/L2 显存…"
                gpu_guard_evict()
                time.sleep(2)
        try:
            wf = _load_workflow(task["workflow"])
        except ConfigError as e:
            task["status"] = "failed"
            task["error"] = str(e)
            return
        if not wf:
            task["status"] = "failed"
            task["error"] = "模板读取失败"
            return
        wf = _apply_params(wf, task["params"])
        task["status"] = "running"
        task["started"] = int(time.time())
        pid, err = _queue_submit_comfy(wf)
        if not pid:
            task["status"] = "failed"
            task["error"] = "ComfyUI 提交失败: " + (err or "")
            task["ended"] = int(time.time())
            return
        task["prompt_id"] = pid
        task["progress"] = "已提交，等待执行…"
        rc = _queue_wait(pid, task)
        if task.get("cancel_requested"):
            task["status"] = "canceled"
        else:
            task["status"] = "done" if rc == "done" else "failed"
    except Exception as e:
        task["status"] = "failed"
        task["error"] = str(e)
    finally:
        task["ended"] = int(time.time())
        if task["status"] == "done" and task.get("started"):
            elapsed = task["ended"] - task["started"]
            update_gen_stats(task["model"], elapsed)
        log_event("queue_finish", task=task["id"], model=task["model"], status=task["status"],
                  err=task["error"][-200:] if task["error"] else "")


def _queue_worker():
    """串行 worker：取队首 → 执行 → 下一个；队列空时休眠 2s。"""
    while True:
        with _task_lock:
            if not _task_queue:
                _queue_state["worker_alive"] = False
                return
            tid = _task_queue.popleft()
        task = _tasks.get(tid)
        if task:
            _run_task(task)


def queue_snapshot() -> dict:
    """队列观察：全部任务（含历史）+ 当前 worker 状态。"""
    with _task_lock:
        tasks = [dict(t) for t in _tasks.values()]
        queue = list(_task_queue)
    tasks.sort(key=lambda t: t.get("created", 0), reverse=True)
    return {"ok": True, "queue": queue, "tasks": tasks,
            "worker_alive": _queue_state["worker_alive"], "client_id": _QUEUE_CLIENT_ID}


def queue_cancel(tid: str) -> dict:
    """取消排队中任务（运行中无法中断 ComfyUI，标记请求取消，完成后置 canceled）。"""
    with _task_lock:
        task = _tasks.get(tid)
        if not task:
            return {"ok": False, "error": "task not found"}
        if task["status"] == "queued":
            try:
                _task_queue.remove(tid)
            except ValueError:
                pass
            task["status"] = "canceled"
            task["ended"] = int(time.time())
            log_event("queue_cancel", task=tid)
            return {"ok": True, "task": task}
        if task["status"] in ("precheck", "freeing", "running"):
            task["cancel_requested"] = True
            return {"ok": True, "note": "运行中，完成/失败后置 canceled", "task": task}
        return {"ok": False, "error": "已结束的任务无法取消"}
