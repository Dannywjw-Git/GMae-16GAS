#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae GPU 门卫模块
- L2 强制驱逐单个进程
- 保护边界（系统进程拒绝驱逐）
"""
import time
from core.logger import log_event, toast_notify
from core.utils import run_args
from gpu.monitor import _find_pid_container, _container_pids, _proc_events

PROTECT_COMMS = {"dwm.exe", "explorer.exe", "init", "supervisord", "caddy"}


def gpu_guard_kick(pid):
    """L2 强制驱逐单个进程：验明正身（容器归属 + 进程名）→ docker exec kill -9。"""
    pid = str(pid).strip()
    if not pid.isdigit():
        return {"ok": False, "error": "invalid pid"}
    cont = _find_pid_container(pid)
    if not cont:
        return {"ok": False,
                "error": "PID %s 未在任何容器中找到，无法自动驱逐（可能 WSL2 VM 直跑，需人工处理）" % pid}
    cmap = _container_pids(cont)
    comm = cmap.get(pid, "")
    if comm.lower() in PROTECT_COMMS:
        return {"ok": False, "error": "拒绝驱逐 protect 进程 %s (PID %s)" % (comm, pid)}
    rc, out = run_args(["docker", "exec", cont, "kill", "-9", pid], 10)
    if rc == 0:
        _proc_events.appendleft({"ts": int(time.time()), "event": "kick", "pid": pid,
                                 "name": comm, "app": cont, "used_mb": 0})
        log_event("guard_kick", pid=pid, container=cont, comm=comm)
        toast_notify("GMae 门卫驱逐", "已强制驱逐进程 %s (PID %s) 于容器 %s" % (comm, pid, cont),
                     event_type="guard_kick", cooldown_s=60)
        return {"ok": True, "message": "已强制驱逐 PID %s (%s) 于容器 %s" % (pid, comm, cont),
                "pid": pid, "container": cont, "comm": comm}
    return {"ok": False, "error": "驱逐失败 rc=%s %s" % (rc, out[-200:])}
