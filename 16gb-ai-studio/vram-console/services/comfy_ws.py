#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae ComfyUI WebSocket 模块
- 极简 WebSocket 客户端（纯标准库）
- 实时事件监听（任务开始/完成/进度）
- 事件队列供前端拉取
"""
import json
import time
import base64
import struct
import socket
import threading
import uuid
import os
from collections import deque
from core.logger import log_event, log_error

# 事件队列
_COMFY_EVENTS = deque(maxlen=300)
_COMFY_EVENTS_LOCK = threading.Lock()


class ComfyWS:
    """极简 WebSocket 客户端（纯标准库，无第三方依赖）：连接 ComfyUI /ws 实时事件流。"""

    def __init__(self, host="127.0.0.1", port=8188):
        self.host, self.port = host, port
        self.client_id = uuid.uuid4().hex
        self.sock = None
        self._buf = b""

    def connect(self):
        key = base64.b64encode(os.urandom(16)).decode()
        path = "/ws?clientId=" + self.client_id
        req = ("GET %s HTTP/1.1\r\n"
               "Host: %s:%d\r\n"
               "Upgrade: websocket\r\n"
               "Connection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n") % (path, self.host, self.port, key)
        s = socket.create_connection((self.host, self.port), timeout=5)
        s.sendall(req.encode("ascii"))
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
        if b"101" not in resp.split(b"\r\n", 1)[0]:
            s.close()
            raise ConnectionError("ws 握手失败: " + resp[:80].decode(errors="replace"))
        self.sock = s
        self._buf = b""

    def _read_frame(self):
        """读一帧（服务端→客户端不 mask）。返回 (opcode, payload)。"""
        while len(self._buf) < 2:
            self._buf += self.sock.recv(4096)
        opcode = self._buf[0] & 0x0F
        ln = self._buf[1] & 0x7F
        off = 2
        if ln == 126:
            while len(self._buf) < 4:
                self._buf += self.sock.recv(4096)
            ln = struct.unpack(">H", self._buf[2:4])[0]
            off = 4
        elif ln == 127:
            while len(self._buf) < 10:
                self._buf += self.sock.recv(4096)
            ln = struct.unpack(">Q", self._buf[2:10])[0]
            off = 10
        while len(self._buf) < off + ln:
            self._buf += self.sock.recv(4096)
        payload = self._buf[off:off + ln]
        self._buf = self._buf[off + ln:]
        return opcode, payload

    def send_ctrl(self, opcode, payload=b""):
        """发送控制帧（客户端→服务器需 mask）。opcode 9=ping, 10=pong。"""
        mask = os.urandom(4)
        ln = len(payload)
        header = bytearray([0x80 | opcode])
        if ln < 126:
            header += bytearray([0x80 | ln])
        elif ln < 65536:
            header += bytearray([0x80 | 126]) + struct.pack(">H", ln)
        else:
            header += bytearray([0x80 | 127]) + struct.pack(">Q", ln)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def recv_message(self, timeout=30):
        """收一条文本消息；收到 ping 自动回 pong；close 抛异常（上层重连）。"""
        self.sock.settimeout(timeout)
        while True:
            op, payload = self._read_frame()
            if op == 9:      # ping → pong
                self.send_ctrl(10, payload)
                continue
            if op == 8:      # close
                raise ConnectionError("ws closed")
            if op in (1, 2):  # text / binary
                return payload.decode("utf-8", errors="replace")


def _on_comfy_ws(raw):
    """解析 ComfyUI ws 消息：status / executing / executed / progress → 刷新活跃度 + 记录事件。"""
    from engine.reaper import _mark_busy
    try:
        m = json.loads(raw)
    except Exception:
        return
    t = m.get("type")
    d = m.get("data") or {}
    rec = {"ts": time.time(), "type": t}
    if t == "status":
        qr = (d.get("exec_info") or {}).get("queue_remaining", 0)
        if qr > 0:
            _mark_busy("comfyui")
        rec["queue_remaining"] = qr
    elif t in ("executing", "executed", "progress"):
        _mark_busy("comfyui")
        rec["prompt_id"] = (d.get("prompt_id") or "")[:8]
        node = d.get("node")
        if t == "executing":
            rec["state"] = "done" if node is None else "executing"
        if t == "progress":
            rec["progress"] = "{}/{}".format(d.get("value"), d.get("max"))
        if node is not None:
            rec["node"] = str(node)[:40]
    else:
        return
    with _COMFY_EVENTS_LOCK:
        _COMFY_EVENTS.append(rec)


def _comfy_ws_loop():
    """ComfyUI WebSocket 监听线程，断线指数退避重连（5s→10s→20s→30s封顶）。"""
    backoff = 5
    while True:
        ws = ComfyWS()
        try:
            ws.connect()
            log_event("comfy_ws_connected", client_id=ws.client_id)
            backoff = 5
            while True:
                msg = ws.recv_message(timeout=45)
                if msg:
                    _on_comfy_ws(msg)
        except Exception as e:
            log_error("comfy_ws_error", error=e, backoff_s=backoff)
            try:
                if ws.sock:
                    ws.sock.close()
            except Exception:
                pass
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)


def comfy_events():
    """GET /api/comfy_events：最近 ComfyUI 实时事件。"""
    with _COMFY_EVENTS_LOCK:
        events = list(_COMFY_EVENTS)
    return {"ok": True, "count": len(events), "events": events[-100:]}


def start_comfy_ws():
    t = threading.Thread(target=_comfy_ws_loop, daemon=True, name="comfy-ws")
    t.start()
    return t
