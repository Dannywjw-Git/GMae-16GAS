#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拓扑图数据构建器（S5）— GPU→容器→模型→任务四层关系

核心概念：
- TopologyNode: 拓扑节点（GPU/容器/模型/任务），含位置、状态、指标
- TopologyLink: 拓扑连接（节点间关系），含类型、强度
- TopologyGraph: 拓扑图，含节点列表 + 连接列表 + 统计信息

四层结构：
  Layer 0: GPU（物理硬件）
  Layer 1: 容器（Docker 容器，运行 AI 服务）
  Layer 2: 模型（加载在容器中的 AI 模型）
  Layer 3: 任务（正在执行的生成/推理任务）
"""
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TopologyNode:
    """拓扑节点。"""
    id: str  # 节点唯一 ID
    layer: int  # 层级 0-3
    layer_name: str  # 层级名称
    name: str  # 节点名称
    type: str  # 节点类型（gpu/container/model/task）
    status: str  # 状态（running/idle/stopped/error/loading）
    metrics: Dict[str, Any] = field(default_factory=dict)  # 指标
    position: Dict[str, float] = field(default_factory=dict)  # 位置（x, y）
    description: str = ""  # 描述


@dataclass
class TopologyLink:
    """拓扑连接。"""
    source: str  # 源节点 ID
    target: str  # 目标节点 ID
    type: str  # 连接类型（runs/loads/executes）
    strength: float = 1.0  # 连接强度 0-1
    description: str = ""  # 描述


@dataclass
class TopologyGraph:
    """拓扑图。"""
    nodes: List[TopologyNode] = field(default_factory=list)
    links: List[TopologyLink] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    generated_at: str = ""


class TopologyBuilder:
    """拓扑图构建器。"""

    def build(self, status: Dict) -> TopologyGraph:
        """构建拓扑图。

        Args:
            status: /api/status 的完整数据

        Returns:
            TopologyGraph 拓扑图
        """
        nodes = []
        links = []

        gpu = status.get("gpu", {}) or {}
        containers_data = status.get("containers", {}) or {}
        all_containers = containers_data.get("all", []) or []
        ollama = status.get("ollama", {}) or {}
        ollama_models = ollama.get("models", []) or []
        comfy_models = status.get("comfyui_models", {}) or {}
        comfy_queue = status.get("comfy_queue", {}) or {}
        activity = status.get("activity", {}) or {}
        services_activity = activity.get("services", {}) or {}

        # === Layer 0: GPU ===
        total_mb = gpu.get("total_mb", 16384)
        used_mb = gpu.get("used_mb", 0)
        free_mb = gpu.get("free_mb", total_mb - used_mb)
        usage_pct = (used_mb / total_mb * 100) if total_mb > 0 else 0

        gpu_status = "running"
        if usage_pct > 90:
            gpu_status = "error"
        elif usage_pct > 70:
            gpu_status = "busy"

        gpu_node = TopologyNode(
            id="gpu-0",
            layer=0,
            layer_name="GPU",
            name="NVIDIA GPU",
            type="gpu",
            status=gpu_status,
            metrics={
                "total_mb": total_mb,
                "used_mb": used_mb,
                "free_mb": free_mb,
                "usage_pct": round(usage_pct, 1),
                "temperature": gpu.get("temperature", 0),
                "utilization": gpu.get("utilization", 0),
            },
            description=f"显存 {used_mb/1024:.1f}GB / {total_mb/1024:.1f}GB ({usage_pct:.0f}%)",
        )
        nodes.append(gpu_node)

        # === Layer 1: 容器 ===
        container_nodes = {}
        # 获取容器状态映射（comfyui/fooocus 等关键容器的状态）
        container_status_map = {}
        for key in ["comfyui", "fooocus", "ollama"]:
            if key in containers_data:
                val = containers_data[key]
                if isinstance(val, dict):
                    container_status_map[key] = val.get("status", "running" if val.get("ok") else "stopped")
                elif isinstance(val, bool):
                    container_status_map[key] = "running" if val else "stopped"

        for container in all_containers:
            # 处理字符串类型（容器名称）或字典类型
            if isinstance(container, str):
                c_name = container
                c_status = container_status_map.get(c_name, "running")  # 默认假设运行中
            else:
                c_name = container.get("name", "unknown")
                c_status = container.get("status", "stopped")

            c_id = f"container-{c_name}"

            # 容器状态
            if c_status == "running":
                svc_activity = services_activity.get(c_name, {})
                if svc_activity.get("busy"):
                    node_status = "busy"
                else:
                    node_status = "running"
            else:
                node_status = "stopped"

            c_node = TopologyNode(
                id=c_id,
                layer=1,
                layer_name="容器",
                name=c_name,
                type="container",
                status=node_status,
                metrics={
                    "status": c_status,
                    "busy": services_activity.get(c_name, {}).get("busy", False),
                },
                description=f"{c_name} ({c_status})",
            )
            nodes.append(c_node)
            container_nodes[c_name] = c_node

            # GPU → 容器 连接
            links.append(TopologyLink(
                source="gpu-0",
                target=c_id,
                type="runs",
                strength=0.8 if c_status == "running" else 0.2,
                description=f"GPU 运行 {c_name} 容器",
            ))

        # === Layer 2: 模型 ===
        # Ollama 模型
        for model in ollama_models:
            m_name = model.get("name", "unknown")
            m_size_gb = model.get("size_gb", 0)
            m_id = f"model-ollama-{m_name}"

            m_node = TopologyNode(
                id=m_id,
                layer=2,
                layer_name="模型",
                name=m_name,
                type="model",
                status="running",
                metrics={
                    "size_gb": m_size_gb,
                    "size_mb": int(m_size_gb * 1024),
                    "backend": "ollama",
                    "container": "ollama",
                },
                description=f"Ollama 模型 {m_name} ({m_size_gb:.1f}GB)",
            )
            nodes.append(m_node)

            # 容器 → 模型 连接
            if "ollama" in container_nodes:
                links.append(TopologyLink(
                    source=container_nodes["ollama"].id,
                    target=m_id,
                    type="loads",
                    strength=0.9,
                    description=f"Ollama 加载 {m_name}",
                ))

        # ComfyUI 模型
        comfy_loaded = comfy_models.get("models", []) or []
        for model in comfy_loaded:
            if isinstance(model, dict):
                m_name = model.get("name", model.get("model_name", "unknown"))
                m_type = model.get("type", "checkpoint")
                m_size = model.get("size_mb", model.get("size", 0))
            else:
                m_name = str(model)
                m_type = "unknown"
                m_size = 0

            m_id = f"model-comfy-{m_name}"

            m_node = TopologyNode(
                id=m_id,
                layer=2,
                layer_name="模型",
                name=m_name,
                type="model",
                status="running",
                metrics={
                    "size_mb": m_size,
                    "model_type": m_type,
                    "backend": "comfyui",
                    "container": "comfyui",
                },
                description=f"ComfyUI 模型 {m_name} ({m_type})",
            )
            nodes.append(m_node)

            # 容器 → 模型 连接
            if "comfyui" in container_nodes:
                links.append(TopologyLink(
                    source=container_nodes["comfyui"].id,
                    target=m_id,
                    type="loads",
                    strength=0.9,
                    description=f"ComfyUI 加载 {m_name}",
                ))

        # === Layer 3: 任务 ===
        # ComfyUI 队列任务
        queue_running = comfy_queue.get("running", []) or []
        queue_pending = comfy_queue.get("pending", []) or []

        for i, task in enumerate(queue_running[:3]):  # 最多显示3个运行中任务
            if isinstance(task, dict):
                t_id = task.get("id", task.get("prompt_id", f"task-{i}"))
                t_type = task.get("type", "generation")
            else:
                t_id = str(task)
                t_type = "generation"

            task_node = TopologyNode(
                id=f"task-running-{i}",
                layer=3,
                layer_name="任务",
                name=f"生成任务 {t_id[:8]}",
                type="task",
                status="running",
                metrics={
                    "task_id": t_id,
                    "task_type": t_type,
                    "backend": "comfyui",
                    "status": "running",
                },
                description=f"ComfyUI 正在执行任务 {t_id}",
            )
            nodes.append(task_node)

            # 模型 → 任务 连接（连接到 comfyui 容器的第一个模型，或直接到容器）
            if "comfyui" in container_nodes:
                links.append(TopologyLink(
                    source=container_nodes["comfyui"].id,
                    target=f"task-running-{i}",
                    type="executes",
                    strength=1.0,
                    description=f"ComfyUI 执行任务 {t_id}",
                ))

        for i, task in enumerate(queue_pending[:5]):  # 最多显示5个等待任务
            if isinstance(task, dict):
                t_id = task.get("id", task.get("prompt_id", f"pending-{i}"))
            else:
                t_id = str(task)

            task_node = TopologyNode(
                id=f"task-pending-{i}",
                layer=3,
                layer_name="任务",
                name=f"等待任务 {t_id[:8]}",
                type="task",
                status="pending",
                metrics={
                    "task_id": t_id,
                    "backend": "comfyui",
                    "status": "pending",
                    "queue_position": i + 1,
                },
                description=f"队列等待中，位置 {i + 1}",
            )
            nodes.append(task_node)

        # === 统计信息 ===
        model_count = len([n for n in nodes if n.type == "model"])
        task_count = len([n for n in nodes if n.type == "task"])
        container_count = len([n for n in nodes if n.type == "container"])
        running_containers = len([n for n in nodes if n.type == "container" and n.status in ("running", "busy")])

        stats = {
            "gpu_count": 1,
            "container_count": container_count,
            "running_containers": running_containers,
            "model_count": model_count,
            "task_count": task_count,
            "running_tasks": len(queue_running),
            "pending_tasks": len(queue_pending),
            "total_vram_mb": total_mb,
            "used_vram_mb": used_mb,
            "free_vram_mb": free_mb,
            "vram_usage_pct": round(usage_pct, 1),
        }

        return TopologyGraph(
            nodes=nodes,
            links=links,
            stats=stats,
            generated_at=datetime.now().isoformat(),
        )


# 全局单例
topology_builder = TopologyBuilder()
