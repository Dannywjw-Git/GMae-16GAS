#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模型登记台与扫描端点（中间层重构 M2 试点）
- GET /api/registry — 模型登记台（registry 元数据 × 实际环境自动同步）
- GET /api/scan — 扫描模型文件
- POST /api/scan/register — 登记扫描到的模型
"""
from typing import Optional
from api.router import router
from api.request import Request
from api.response import Response
from api.route_helpers import registry_view
from engine.scanner import model_scan, scan_register
from core.event_bus import event_bus


@router.get("/api/registry")
def get_registry(req: Request) -> Response:
    """模型登记台：registry 元数据 × 实际环境自动同步。"""
    return Response.success(registry_view())


@router.get("/api/scan")
def get_scan(req: Request) -> Response:
    """扫描模型文件，返回发现的模型列表。"""
    return Response.success(model_scan())


@router.post("/api/scan/register")
def post_scan_register(req: Request) -> Response:
    """登记扫描到的模型到 registry。

    Body 参数：
        source: 来源（comfyui / ollama / 自定义），默认 comfyui
        name: 模型名称
        vram_gb: 显存占用（GB），可选
        category: 类别（image / video / audio / text），默认 image
    """
    result = scan_register(
        source=req.body_get("source", "comfyui"),
        name=req.body_get("name", ""),
        vram_gb=req.body_get("vram_gb"),
        category=req.body_get("category", "image"),
    )
    try:
        ok = result.get("ok", False) if isinstance(result, dict) else False
        event_bus.record(
            category="user_action", level="info", source="api_endpoint",
            event="model_register",
            message="登记模型 {}（{}，{}）".format(
                req.body_get("name", ""),
                req.body_get("source", "comfyui"),
                "成功" if ok else "失败"
            ),
            metadata={"name": req.body_get("name", ""),
                      "source": req.body_get("source", "comfyui"),
                      "category": req.body_get("category", "image"),
                      "success": ok}
        )
    except Exception:
        pass
    return Response.success(result)
