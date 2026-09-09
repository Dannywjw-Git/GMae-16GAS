#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
进程管理端点
- POST /api/process/kill — 结束指定 Windows 进程（安全范围：非系统关键进程）
"""
import os
import re
import subprocess
from api.router import router
from api.request import Request
from api.response import Response
from core.status_cache import status_cache
from core.event_bus import event_bus
from core.logger import log_error, log_event

# 系统关键进程黑名单（不允许结束）
SYSTEM_PROCESS_BLACKLIST = {
    'system', 'registry', 'smss', 'csrss', 'wininit', 'services', 'lsass',
    'svchost', 'dwm', 'winlogon', 'fontdrvhost', 'sihost', 'taskhostw',
    'textinputhost', 'searchhost', 'shellhost', 'shellexperiencehost',
    'startmenuexperiencehost', 'applicationframehost', 'msmpeng',
    'securityhealthservice', 'vmmem', 'vmmemwsl', 'vmwp', 'wudfhost',
    'spoolsv', 'audiodg', 'conhost', 'dllhost', 'taskeng', 'taskhostex',
    'runtimebroker', 'sihost', 'ctfmon', 'igfxem', 'igfxcuiservice',
    'nvcontainer', 'nvdisplay.container', 'dasHost', 'SearchIndexer',
    'SearchProtocolHost', 'SearchFilterHost', 'WmiPrvSE', 'wmiprvse',
    'wininit', 'winlogon', 'Memory Compression', 'Registry',
}


def _is_system_process(name: str) -> bool:
    """判断是否为系统关键进程（不允许结束）。"""
    if not name:
        return True
    name_lower = name.lower().replace('.exe', '')
    return any(s in name_lower for s in SYSTEM_PROCESS_BLACKLIST)


@router.post("/api/process/kill")
def post_process_kill(req: Request) -> Response:
    """结束指定 Windows 进程（安全范围：非系统关键进程）。

    Body 参数：
        pid: 进程 ID
    """
    pid = req.body_get("pid", 0)
    try:
        pid = int(pid)
    except (ValueError, TypeError):
        return Response.bad_request("invalid pid")

    if pid <= 0:
        return Response.bad_request("pid must be positive")

    # 获取进程名
    try:
        r = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command',
             f'(Get-Process -Id {pid} -ErrorAction SilentlyContinue).ProcessName'],
            capture_output=True, text=True, timeout=5
        )
        proc_name = r.stdout.strip()
    except Exception:
        proc_name = ""

    # 安全检查：不允许结束系统关键进程
    if _is_system_process(proc_name):
        return Response.bad_request(f"进程 {proc_name or 'System'} (PID {pid}) 是系统关键进程，不允许结束")

    # 安全检查：不允许结束 GMae 自身或看门狗
    try:
        current_pid = os.getpid()
        if pid == current_pid:
            return Response.bad_request("不允许结束 GMae 调度中心自身进程")
    except Exception:
        pass

    # 执行结束进程
    try:
        r = subprocess.run(
            ['taskkill', '/F', '/PID', str(pid)],
            capture_output=True, text=True, timeout=10
        )
        ok = r.returncode == 0
        msg = (r.stdout or r.stderr).strip()[:200]
    except Exception as e:
        ok = False
        msg = str(e)[:200]

    status_cache.invalidate()
    log_event("process_kill", pid=pid, name=proc_name, ok=ok, message=msg)
    try:
        event_bus.record(
            category="user_action", level="warning" if ok else "error",
            source="api_endpoint", event="process_killed",
            message="结束进程 {}（PID {}）{}".format(proc_name or 'unknown', pid, "成功" if ok else "失败"),
            metadata={"pid": pid, "name": proc_name, "success": ok, "message": msg}
        )
    except Exception as e:
        log_error("exception_suppressed", error=e, context="process.py:event")

    if ok:
        return Response.success({"ok": True, "pid": pid, "name": proc_name, "message": "进程已结束"})
    else:
        return Response.internal_error("结束进程失败", details={"pid": pid, "name": proc_name, "error": msg})
