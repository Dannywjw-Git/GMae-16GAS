#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae SSE 实时推送端点
- GET /api/stream — 每3秒推送状态快照（显存/告警/auto_protect）
- 前端用 EventSource 连接，替代轮询
"""
import json
import time
from api.router import router
from api.request import Request
from api.response import Response


def _sse_snapshot():
    """采集一次状态快照。"""
    from gpu.monitor import gpu_status
    from engine.alert_manager import alert_manager
    from engine.qos import auto_protect_status
    gpu = gpu_status(force_refresh=True)
    alerts = alert_manager.get_active()
    ap = auto_protect_status()
    return {
        "ts": int(time.time()),
        "gpu": {
            "used_mb": gpu.get("used_mb", 0),
            "free_mb": gpu.get("free_mb", 0),
            "total_mb": gpu.get("total_mb", 0),
            "utilization": gpu.get("utilization", 0),
        },
        "alerts": {
            "active_count": len(alerts),
            "critical": [a for a in alerts if a.get("level") == "critical"],
            "danger": [a for a in alerts if a.get("level") == "danger"],
        },
        "auto_protect": {
            "enabled": ap.get("enabled"),
            "mode": ap.get("mode"),
            "last_trigger": ap.get("last_trigger"),
        },
    }


@router.get("/api/stream")
def get_stream(req: Request) -> Response:
    """SSE 实时推送：每3秒推送状态快照。"""
    def event_generator():
        # 发送连接确认
        yield ": connected\n\n"
        while True:
            try:
                snapshot = _sse_snapshot()
                yield "data: " + json.dumps(snapshot, ensure_ascii=False) + "\n\n"
            except Exception as e:
                yield "event: error\ndata: " + json.dumps({"error": str(e)}) + "\n\n"
            time.sleep(3)
    return Response.stream(event_generator())
