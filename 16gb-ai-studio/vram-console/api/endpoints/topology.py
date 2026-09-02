#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拓扑图与健康度端点（S5）
- GET /api/topology — 获取 GPU→容器→模型→任务四层拓扑图数据
- GET /api/health — 获取系统健康度评分报告
"""
from api.router import router
from api.request import Request
from api.response import Response
from engine.topology import topology_builder
from engine.health_score import health_engine
from services.status import current_status


@router.get("/api/topology")
def get_topology(req: Request) -> Response:
    """获取拓扑图数据。

    返回 GPU→容器→模型→任务四层关系，含节点、连接、统计信息。
    前端可用于 SVG 拓扑图可视化。
    """
    status = current_status()
    graph = topology_builder.build(status)

    return Response.success({
        "nodes": [
            {
                "id": n.id,
                "layer": n.layer,
                "layer_name": n.layer_name,
                "name": n.name,
                "type": n.type,
                "status": n.status,
                "metrics": n.metrics,
                "position": n.position,
                "description": n.description,
            }
            for n in graph.nodes
        ],
        "links": [
            {
                "source": l.source,
                "target": l.target,
                "type": l.type,
                "strength": l.strength,
                "description": l.description,
            }
            for l in graph.links
        ],
        "stats": graph.stats,
        "generated_at": graph.generated_at,
    })


@router.get("/api/health/score")
def get_health_score(req: Request) -> Response:
    """获取系统健康度评分报告。

    返回多维度健康分（GPU显存/容器/服务/告警）+ 综合健康分 + 问题与建议。
    注意：与 /api/health（健康检查，免认证）不同，此端点返回详细健康度评分。
    """
    status = current_status()
    report = health_engine.evaluate(status)

    return Response.success({
        "overall_score": report.overall_score,
        "overall_status": report.overall_status,
        "summary": report.summary,
        "dimensions": [
            {
                "id": d.id,
                "name": d.name,
                "score": d.score,
                "status": d.status,
                "description": d.description,
                "metrics": d.metrics,
                "issues": d.issues,
                "suggestions": d.suggestions,
            }
            for d in report.dimensions
        ],
        "top_issues": report.top_issues,
        "top_suggestions": report.top_suggestions,
        "generated_at": report.generated_at,
    })
