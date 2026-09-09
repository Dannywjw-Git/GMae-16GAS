#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拓扑图数据构建器 — 5层资源拓扑

五层结构：
  Layer 0: 宿主机硬件（CPU / 内存 / GPU / 磁盘 / 网络）
  Layer 1: 平台软件（OS / WSL / Docker / Python）
  Layer 2: AI服务容器（Docker 容器，运行 AI 服务）
  Layer 3: AI模型（加载在容器中的 AI 模型）
  Layer 4: 运行任务（正在执行的生成/推理任务）

跨机器适配：
- 所有节点动态生成，不硬编码硬件/软件信息
- 探测失败的组件不生成节点（或显示"未知"）
- 容器分类用规则匹配，不硬编码容器列表
"""
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TopologyNode:
    """拓扑节点。"""
    id: str
    layer: int  # 0-4
    layer_name: str
    name: str
    type: str  # cpu/memory/gpu/disk/network/os/wsl/docker/python/container/model/task
    status: str  # running/idle/stopped/error/loading/unknown
    metrics: Dict[str, Any] = field(default_factory=dict)
    position: Dict[str, float] = field(default_factory=dict)
    description: str = ""
    category: str = ""  # 容器分类：core/gateway/storage/search/other
    expandable: bool = False  # 是否可折叠
    default_expand: bool = True  # 默认是否展开


@dataclass
class TopologyLink:
    """拓扑连接。"""
    source: str
    target: str
    type: str  # runs/loads/executes/contains
    strength: float = 1.0
    description: str = ""


@dataclass
class TopologyGraph:
    """拓扑图。"""
    nodes: List[TopologyNode] = field(default_factory=list)
    links: List[TopologyLink] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    generated_at: str = ""


# 容器分类规则（按名称关键词匹配，顺序即优先级：具体规则在前）
CONTAINER_CATEGORY_RULES = [
    # (category, weight, default_expand, keywords)
    # 存储类（优先匹配，避免 nextcloud-nginx 被误判为 gateway）
    ("storage", "low", False, ["immich", "nextcloud", "minio", "seaweedfs", "owncloud", "syncthing"]),
    # 核心推理
    ("core", "high", True, ["ollama", "comfyui", "comfy", "fooocus", "sd-webui", "stable-diffusion",
                            "invokeai", "vllm", "text-generation", "localai", "lm-studio", "koboldai",
                            "whisper", "stable-video", "wan"]),
    # 前端/网关
    ("gateway", "medium", True, ["open-webui", "openwebui", "dify", "anything-llm", "librechat",
                                  "fastgpt", "flowise", "langchain", "caddy", "traefik", "n8n"]),
    # 向量数据库
    ("vector_db", "low", False, ["chroma", "milvus", "qdrant", "weaviate", "pinecone"]),
    # 搜索
    ("search", "low", False, ["searxng", "whoogle", "meilisearch", "elasticsearch"]),
    # 监控
    ("monitor", "low", False, ["grafana", "prometheus", "cadvisor", "node-exporter", "portainer"]),
]


def classify_container(name: str) -> Dict[str, Any]:
    """根据容器名分类。

    Returns:
        {category, weight, default_expand}
    """
    n = name.lower()
    for category, weight, default_expand, keywords in CONTAINER_CATEGORY_RULES:
        for kw in keywords:
            if kw in n:
                return {"category": category, "weight": weight, "default_expand": default_expand}
    return {"category": "other", "weight": "low", "default_expand": False}


class TopologyBuilder:
    """拓扑图构建器。"""

    def build(self, status: Dict, system_info: Optional[Dict] = None) -> TopologyGraph:
        """构建5层拓扑图。

        Args:
            status: /api/status 的完整数据
            system_info: /api/system/info 的数据（可选，None时不生成硬件/平台层）

        Returns:
            TopologyGraph 拓扑图
        """
        nodes = []
        links = []
        sys_info = system_info or {}

        # === Layer 0: 宿主机硬件 ===
        hardware_node_ids = self._build_hardware_layer(nodes, links, status, sys_info)

        # === Layer 1: 平台软件 ===
        platform_node_ids = self._build_platform_layer(nodes, links, sys_info, hardware_node_ids)

        # === Layer 2: AI服务容器 ===
        container_nodes = self._build_container_layer(nodes, links, status, platform_node_ids)

        # === Layer 3: AI模型 ===
        self._build_model_layer(nodes, links, status, container_nodes)

        # === Layer 4: 运行任务 ===
        self._build_task_layer(nodes, links, status, container_nodes)

        # === 统计信息 ===
        stats = self._build_stats(nodes, status)

        return TopologyGraph(
            nodes=nodes,
            links=links,
            stats=stats,
            generated_at=datetime.now().isoformat(),
        )

    def _build_hardware_layer(self, nodes, links, status, sys_info) -> Dict[str, str]:
        """构建硬件层，返回 {type: node_id} 映射。"""
        ids = {}
        gpu = status.get("gpu", {}) or {}

        # CPU
        cpu = sys_info.get("cpu", {}) or {}
        if cpu.get("name") or cpu.get("cores"):
            cpu_id = "hw-cpu"
            nodes.append(TopologyNode(
                id=cpu_id, layer=0, layer_name="硬件",
                name=cpu.get("name") or "CPU",
                type="cpu", status="running",
                metrics={
                    "cores": cpu.get("cores"),
                    "threads": cpu.get("threads"),
                    "usage_pct": cpu.get("usage_pct"),
                    "freq_mhz": cpu.get("freq_mhz"),
                },
                description=f"{cpu.get('cores', '?')}核 · {cpu.get('usage_pct', '?')}%",
            ))
            ids["cpu"] = cpu_id

        # 内存
        mem = sys_info.get("memory", {}) or {}
        if mem.get("total_mb"):
            mem_id = "hw-memory"
            total_gb = round(mem["total_mb"] / 1024, 1)
            used_gb = round(mem.get("used_mb", 0) / 1024, 1) if mem.get("used_mb") else None
            nodes.append(TopologyNode(
                id=mem_id, layer=0, layer_name="硬件",
                name="内存", type="memory", status="running",
                metrics={
                    "total_mb": mem.get("total_mb"),
                    "used_mb": mem.get("used_mb"),
                    "usage_pct": mem.get("usage_pct"),
                },
                description=f"{used_gb or '?'}/{total_gb}GB · {mem.get('usage_pct', '?')}%",
            ))
            ids["memory"] = mem_id

        # GPU（从 status 获取，实时数据）
        total_mb = gpu.get("total_mb", 0)
        used_mb = gpu.get("used_mb", 0)
        if total_mb > 0:
            gpu_id = "hw-gpu"
            gpu_name = "GPU"
            # 从 hardware_profile 或 system_info 获取 GPU 型号
            gpu_info = sys_info.get("gpu") or {}
            if gpu_info:
                gpu_name = gpu_info.get("name", "GPU")
            usage_pct = round(used_mb / total_mb * 100, 1) if total_mb > 0 else 0
            gpu_status = "error" if usage_pct > 90 else "busy" if usage_pct > 70 else "running"
            nodes.append(TopologyNode(
                id=gpu_id, layer=0, layer_name="硬件",
                name=gpu_name, type="gpu", status=gpu_status,
                metrics={
                    "total_mb": total_mb,
                    "used_mb": used_mb,
                    "free_mb": gpu.get("free_mb", total_mb - used_mb),
                    "usage_pct": usage_pct,
                    "temperature": gpu.get("temperature"),
                    "utilization": gpu.get("utilization"),
                },
                description=f"显存 {used_mb//1024}/{total_mb//1024}GB ({usage_pct}%)",
            ))
            ids["gpu"] = gpu_id

        # 磁盘（取第一个非系统盘，或系统盘）
        disks = sys_info.get("disks", []) or []
        for i, disk in enumerate(disks[:2]):  # 最多显示2个磁盘
            disk_id = f"hw-disk-{i}"
            nodes.append(TopologyNode(
                id=disk_id, layer=0, layer_name="硬件",
                name=disk.get("model") or f"磁盘 {i+1}",
                type="disk", status="running",
                metrics={
                    "total_gb": disk.get("total_gb"),
                    "used_gb": disk.get("used_gb"),
                    "usage_pct": disk.get("usage_pct"),
                    "mountpoint": disk.get("mountpoint"),
                },
                description=f"{disk.get('used_gb', '?')}/{disk.get('total_gb', '?')}GB · {disk.get('usage_pct', '?')}%",
            ))
            ids[f"disk_{i}"] = disk_id

        # 网络
        net = sys_info.get("network", {}) or {}
        if net.get("ip"):
            net_id = "hw-network"
            nodes.append(TopologyNode(
                id=net_id, layer=0, layer_name="硬件",
                name="网络", type="network", status="running",
                metrics={
                    "ip": net.get("ip"),
                    "upload_mbps": net.get("upload_mbps"),
                    "download_mbps": net.get("download_mbps"),
                },
                description=f"IP {net.get('ip')} · ↑{net.get('upload_mbps', '?')} ↓{net.get('download_mbps', '?')}MB/s",
            ))
            ids["network"] = net_id

        return ids

    def _build_platform_layer(self, nodes, links, sys_info, hw_ids) -> Dict[str, str]:
        """构建平台软件层，返回 {type: node_id} 映射。"""
        ids = {}

        # OS
        os_info = sys_info.get("os", {}) or {}
        if os_info.get("name"):
            os_id = "pf-os"
            os_name = f"{os_info['name']} {os_info.get('version', '')}".strip()
            nodes.append(TopologyNode(
                id=os_id, layer=1, layer_name="平台",
                name=os_name, type="os", status="running",
                metrics={"build": os_info.get("build"), "type": os_info.get("type")},
                description=f"构建 {os_info.get('build', '未知')}",
            ))
            ids["os"] = os_id
            # OS 运行在硬件上（连接到 CPU 或第一个硬件节点）
            if hw_ids:
                target = hw_ids.get("cpu") or list(hw_ids.values())[0]
                links.append(TopologyLink(source=target, target=os_id, type="runs", strength=0.9))

        # WSL
        wsl = sys_info.get("wsl", {}) or {}
        if wsl.get("available"):
            wsl_id = "pf-wsl"
            nodes.append(TopologyNode(
                id=wsl_id, layer=1, layer_name="平台",
                name=f"WSL2 {wsl.get('version', '')}".strip(),
                type="wsl", status="running",
                metrics={"default_distro": wsl.get("default_distro")},
                description=f"默认发行版: {wsl.get('default_distro', '未知')}",
            ))
            ids["wsl"] = wsl_id
            if "os" in ids:
                links.append(TopologyLink(source=ids["os"], target=wsl_id, type="runs", strength=0.9))

        # Docker
        docker = sys_info.get("docker", {}) or {}
        if docker.get("available"):
            docker_id = "pf-docker"
            docker_status = "running" if docker.get("running") else "stopped"
            nodes.append(TopologyNode(
                id=docker_id, layer=1, layer_name="平台",
                name=f"Docker {docker.get('version', '')}".strip(),
                type="docker", status=docker_status,
                metrics={
                    "container_count": docker.get("container_count"),
                    "running": docker.get("running"),
                },
                description=f"{docker.get('container_count', '?')}个容器 · {'运行中' if docker.get('running') else '未运行'}",
            ))
            ids["docker"] = docker_id
            # Docker 运行在 WSL 或 OS 上
            target = ids.get("wsl") or ids.get("os")
            if target:
                links.append(TopologyLink(source=target, target=docker_id, type="runs", strength=0.9))

        # Python
        py = sys_info.get("python", {}) or {}
        if py.get("version"):
            py_id = "pf-python"
            nodes.append(TopologyNode(
                id=py_id, layer=1, layer_name="平台",
                name=f"Python {py['version']}", type="python", status="running",
                metrics={"implementation": py.get("implementation")},
                description=py.get("implementation", ""),
            ))
            ids["python"] = py_id
            if "os" in ids:
                links.append(TopologyLink(source=ids["os"], target=py_id, type="runs", strength=0.7))

        return ids

    def _build_container_layer(self, nodes, links, status, platform_ids) -> Dict[str, TopologyNode]:
        """构建容器层，返回 {container_name: node} 映射。"""
        container_nodes = {}
        containers_data = status.get("containers", {}) or {}
        all_containers = containers_data.get("all", []) or []
        activity = status.get("activity", {}) or {}
        services_activity = activity.get("services", {}) or {}

        # 容器状态映射
        container_status_map = {}
        for key in ["comfyui", "fooocus", "ollama"]:
            if key in containers_data:
                val = containers_data[key]
                if isinstance(val, dict):
                    container_status_map[key] = val.get("status", "running" if val.get("ok") else "stopped")
                elif isinstance(val, bool):
                    container_status_map[key] = "running" if val else "stopped"

        docker_id = platform_ids.get("docker")

        for container in all_containers:
            if isinstance(container, str):
                c_name = container
                c_status = container_status_map.get(c_name, "running")
            else:
                c_name = container.get("name", "unknown")
                c_status = container.get("status", "stopped")

            c_id = f"container-{c_name}"
            cat_info = classify_container(c_name)

            # 容器状态
            if c_status == "running":
                svc_activity = services_activity.get(c_name, {})
                node_status = "busy" if svc_activity.get("busy") else "running"
            else:
                node_status = "stopped"

            c_node = TopologyNode(
                id=c_id, layer=2, layer_name="容器",
                name=c_name, type="container", status=node_status,
                category=cat_info["category"],
                expandable=cat_info["weight"] == "low",
                default_expand=cat_info["default_expand"],
                metrics={
                    "status": c_status,
                    "busy": services_activity.get(c_name, {}).get("busy", False),
                    "category": cat_info["category"],
                    "weight": cat_info["weight"],
                },
                description=f"{c_name} ({c_status}) · {cat_info['category']}",
            )
            nodes.append(c_node)
            container_nodes[c_name] = c_node

            # Docker → 容器 连接
            if docker_id:
                links.append(TopologyLink(
                    source=docker_id, target=c_id, type="contains",
                    strength=0.8 if c_status == "running" else 0.2,
                    description=f"Docker 运行 {c_name}",
                ))

        return container_nodes

    def _build_model_layer(self, nodes, links, status, container_nodes):
        """构建模型层。运行中模型单独显示；未加载模型合并为一个汇总节点（避免拓扑页过密）。"""
        ollama = status.get("ollama", {}) or {}
        ollama_running = ollama.get("models", []) or []
        ollama_installed = ollama.get("installed", []) or []
        comfy_models = status.get("comfyui_models", {}) or {}
        comfy_running = comfy_models.get("models", []) or []

        running_names = {m.get("name") for m in ollama_running if isinstance(m, dict)}
        idle_count = sum(1 for m in ollama_installed if isinstance(m, str) and m not in running_names)

        # Ollama 运行中模型
        for model in ollama_running:
            if isinstance(model, dict):
                m_name = model.get("name", "unknown")
                m_size_gb = model.get("size_gb", 0)
            else:
                m_name = str(model)
                m_size_gb = 0
            m_id = f"model-ollama-{m_name}"
            nodes.append(TopologyNode(
                id=m_id, layer=3, layer_name="模型",
                name=m_name, type="model", status="running",
                metrics={"size_gb": m_size_gb, "backend": "ollama", "container": "ollama", "category": "text", "loaded": True},
                description=f"Ollama · {m_size_gb:.1f}GB",
            ))
            if "ollama" in container_nodes:
                links.append(TopologyLink(source=container_nodes["ollama"].id, target=m_id, type="loads", strength=0.9, description=f"Ollama 加载 {m_name}"))

        # Ollama 未加载模型（合并为汇总节点）
        if idle_count > 0:
            idle_names = [m for m in ollama_installed if isinstance(m, str) and m not in running_names]
            summary_id = "model-ollama-installed-summary"
            nodes.append(TopologyNode(
                id=summary_id, layer=3, layer_name="模型",
                name=f"已安装模型 ({idle_count})", type="model", status="idle",
                metrics={"backend": "ollama", "container": "ollama", "loaded": False, "count": idle_count, "models": ", ".join(idle_names[:5]) + ("..." if len(idle_names) > 5 else "")},
                description=f"Ollama · 未加载 · 点击查看清单",
            ))
            if "ollama" in container_nodes:
                links.append(TopologyLink(source=container_nodes["ollama"].id, target=summary_id, type="loads", strength=0.3, description=f"Ollama 可加载 {idle_count} 个模型"))

        # ComfyUI 运行中模型
        for model in comfy_running:
            if isinstance(model, dict):
                m_name = model.get("name", model.get("model_name", "unknown"))
                m_type = model.get("type", "checkpoint")
                m_size = model.get("size_mb", model.get("size", 0))
            else:
                m_name = str(model)
                m_type = "unknown"
                m_size = 0
            m_id = f"model-comfy-{m_name}"
            model_category = "video" if "wan" in m_name.lower() or "video" in m_name.lower() else "image"
            nodes.append(TopologyNode(
                id=m_id, layer=3, layer_name="模型",
                name=m_name, type="model", status="running",
                metrics={"size_mb": m_size, "model_type": m_type, "backend": "comfyui", "container": "comfyui", "category": model_category, "loaded": True},
                description=f"ComfyUI · {m_type}",
            ))
            if "comfyui" in container_nodes:
                links.append(TopologyLink(source=container_nodes["comfyui"].id, target=m_id, type="loads", strength=0.9, description=f"ComfyUI 加载 {m_name}"))

        # ComfyUI 无活跃模型但有显存占用：显示框架占用节点
        if not comfy_running and comfy_models.get("torch_vram_used_mb", 0) > 1024:
            fw_id = "model-comfy-framework"
            torch_mb = comfy_models.get("torch_vram_used_mb", 0)
            nodes.append(TopologyNode(
                id=fw_id, layer=3, layer_name="模型",
                name="ComfyUI 框架占用", type="model", status="idle",
                metrics={"size_mb": torch_mb, "backend": "comfyui", "container": "comfyui", "loaded": False},
                description=f"ComfyUI · 框架 {torch_mb//1024}GB · 无活跃模型",
            ))
            if "comfyui" in container_nodes:
                links.append(TopologyLink(source=container_nodes["comfyui"].id, target=fw_id, type="loads", strength=0.3, description="ComfyUI 框架占用"))

    def _build_task_layer(self, nodes, links, status, container_nodes):
        """构建任务层。"""
        comfy_queue = status.get("comfy_queue", {}) or {}
        queue_running = comfy_queue.get("running", []) or []
        queue_pending = comfy_queue.get("pending", []) or []

        for i, task in enumerate(queue_running[:3]):
            if isinstance(task, dict):
                t_id = task.get("id", task.get("prompt_id", f"task-{i}"))
                t_type = task.get("type", "generation")
            else:
                t_id = str(task)
                t_type = "generation"

            task_node = TopologyNode(
                id=f"task-running-{i}", layer=4, layer_name="任务",
                name=f"生成中 {t_id[:8]}", type="task", status="running",
                metrics={"task_id": t_id, "task_type": t_type, "backend": "comfyui"},
                description=f"ComfyUI 执行中",
            )
            nodes.append(task_node)

            if "comfyui" in container_nodes:
                links.append(TopologyLink(
                    source=container_nodes["comfyui"].id, target=f"task-running-{i}",
                    type="executes", strength=1.0,
                    description=f"ComfyUI 执行任务",
                ))

        for i, task in enumerate(queue_pending[:5]):
            if isinstance(task, dict):
                t_id = task.get("id", task.get("prompt_id", f"pending-{i}"))
            else:
                t_id = str(task)

            task_node = TopologyNode(
                id=f"task-pending-{i}", layer=4, layer_name="任务",
                name=f"等待中 {t_id[:8]}", type="task", status="pending",
                metrics={"task_id": t_id, "backend": "comfyui", "queue_position": i + 1},
                description=f"队列位置 {i + 1}",
            )
            nodes.append(task_node)

    def _build_stats(self, nodes, status) -> Dict[str, Any]:
        """构建统计信息。"""
        gpu = status.get("gpu", {}) or {}
        total_mb = gpu.get("total_mb", 16384)
        used_mb = gpu.get("used_mb", 0)

        return {
            "hardware_count": len([n for n in nodes if n.layer == 0]),
            "platform_count": len([n for n in nodes if n.layer == 1]),
            "container_count": len([n for n in nodes if n.layer == 2]),
            "running_containers": len([n for n in nodes if n.layer == 2 and n.status in ("running", "busy")]),
            "model_count": len([n for n in nodes if n.layer == 3]),
            "task_count": len([n for n in nodes if n.layer == 4]),
            "running_tasks": len([n for n in nodes if n.layer == 4 and n.status == "running"]),
            "pending_tasks": len([n for n in nodes if n.layer == 4 and n.status == "pending"]),
            "total_vram_mb": total_mb,
            "used_vram_mb": used_mb,
            "vram_usage_pct": round(used_mb / total_mb * 100, 1) if total_mb > 0 else 0,
        }


# 全局单例
topology_builder = TopologyBuilder()
