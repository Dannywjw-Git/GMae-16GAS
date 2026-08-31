"""
GMae v0.3.1 — 准入闸门模块（AdmissionGate）

所有写操作（场景切换、任务提交、模型加载、显存释放、进程驱逐）统一过闸门。
C-Eng 的 LLM 决策和用户手动操作共用同一闸门，确保铁律不可绕过。

三道防线：
1. 格式校验：action 白名单 + args 完整性
2. 铁律校验：R1-R8 逐条检查（适用的）
3. 预算校验：实时显存 + registry 实测值，不信任调用方数字

返回格式：
{
    "allowed": bool,
    "reason": str,           # 不通过时的原因
    "required_free_gb": float,  # 需要释放的显存（GB）
    "violated_rules": [str], # 违反的铁律编号
    "checks": {              # 每项检查的详细结果
        "format": {"passed": bool, "detail": str},
        "rules": {"passed": bool, "violations": [str]},
        "budget": {"passed": bool, "detail": str}
    }
}
"""

from dataclasses import dataclass, field
from typing import Optional
from core.logger import logger


# 允许的 action 白名单
ALLOWED_ACTIONS = {
    "switch_scene": {"required": ["target"], "optional": []},
    "submit_task": {"required": ["model", "params"], "optional": ["workflow"]},
    "load_model": {"required": ["model"], "optional": ["ctx", "keep_alive"]},
    "stop_model": {"required": ["model"], "optional": []},
    "free_vram": {"required": [], "optional": ["target"]},
    "evict_process": {"required": ["pid"], "optional": []},
    "stop_service": {"required": ["service"], "optional": []},
    "start_service": {"required": ["service"], "optional": []},
}

# 大模型阈值（≥5GB 视为大模型，R1 用）
LARGE_MODEL_THRESHOLD_GB = 5.0

# 独占模型列表（R2 用）
EXCLUSIVE_MODELS = {"Flux-Q5", "flux", "27b", "qwen3.8:27b", "Wan2.2-TI2V", "wan2.2"}


@dataclass
class GateContext:
    """闸门检查所需的当前状态（由调用方从 server.py 传入）。"""
    vram_total_mb: int = 16384
    vram_used_mb: int = 0
    vram_free_mb: int = 16384
    base_noise_mb: int = 1200
    current_scene: str = "dialogue"
    loaded_ollama_models: list = field(default_factory=list)  # [{name, size_gb}]
    loaded_comfy_models: list = field(default_factory=list)   # [{id, name, vram_gb, exclusive}]
    comfyui_running: bool = False
    fooocus_running: bool = False
    ollama_serve_count: int = 1
    registry_models: dict = field(default_factory=dict)  # {source: [{id, name, vram_gb, exclusive, ctx}]}
    danger_thresholds: dict = field(default_factory=dict)  # 动态阈值


def _check_format(action: str, args: dict) -> dict:
    """防线1：格式校验。"""
    if action not in ALLOWED_ACTIONS:
        return {"passed": False, "detail": f"未知 action: {action}（允许: {', '.join(ALLOWED_ACTIONS.keys())}）"}
    spec = ALLOWED_ACTIONS[action]
    missing = [k for k in spec["required"] if k not in args or args[k] is None]
    if missing:
        return {"passed": False, "detail": f"缺少必填参数: {', '.join(missing)}"}
    return {"passed": True, "detail": "格式校验通过"}


def _check_rules(action: str, args: dict, ctx: GateContext) -> dict:
    """防线2：铁律校验 R1-R8（适用的逐条检查）。"""
    violations = []

    # R1: 禁止两个大模型（≥5G）同时常驻
    if action in ("load_model", "submit_task", "switch_scene"):
        large_loaded = [m for m in ctx.loaded_ollama_models if m.get("size_gb", 0) >= LARGE_MODEL_THRESHOLD_GB]
        large_loaded += [m for m in ctx.loaded_comfy_models if m.get("vram_gb", 0) >= LARGE_MODEL_THRESHOLD_GB]
        # 检查即将加载的模型是否也是大模型
        target_model = args.get("model") or args.get("target", "")
        target_vram = _get_model_vram(target_model, ctx)
        if target_vram >= LARGE_MODEL_THRESHOLD_GB and len(large_loaded) >= 1:
            # 检查目标是否与已加载的是同一个（已加载的不算违规）
            already_loaded = any(
                m.get("name") == target_model or m.get("id") == target_model
                for m in large_loaded
            )
            if not already_loaded:
                violations.append(f"R1: 已加载大模型 {[m.get('name') or m.get('id') for m in large_loaded]}，"
                                  f"不能再加载 {target_model}（≥{LARGE_MODEL_THRESHOLD_GB}GB）")

    # R2: 独占模型（Flux/27B/Wan2.2）不与其他AI负载共存
    if action in ("load_model", "submit_task", "switch_scene"):
        target_model = args.get("model") or args.get("target", "")
        target_exclusive = _is_exclusive(target_model)
        # 即将加载独占模型
        if target_exclusive:
            other_loads = len(ctx.loaded_ollama_models) + len(ctx.loaded_comfy_models)
            if other_loads > 0:
                violations.append(f"R2: {target_model} 需独占全卡，当前已加载 {other_loads} 个模型，请先释放")
        # 当前已有独占模型加载
        exclusive_loaded = [m for m in ctx.loaded_comfy_models if m.get("exclusive")]
        exclusive_loaded += [m for m in ctx.loaded_ollama_models if _is_exclusive(m.get("name", ""))]
        if exclusive_loaded and action in ("load_model", "submit_task"):
            violations.append(f"R2: 当前已有独占模型 {[m.get('name') or m.get('id') for m in exclusive_loaded]}，"
                              f"不能加载其他模型")

    # R3: 禁止 num_ctx 超 8192（qwen3.5:9b 设32K→13.7G→死机）
    if action == "load_model":
        ctx_size = args.get("ctx")
        if ctx_size and int(ctx_size) > 8192:
            model = args.get("model", "")
            violations.append(f"R3: {model} 的 num_ctx={ctx_size} 超过安全上限 8192（>8K 可能导致死机）")

    # R4: 禁止双 ollama serve 进程
    if action in ("start_service",) and args.get("service") == "ollama":
        if ctx.ollama_serve_count >= 1:
            violations.append("R4: 已有 ollama serve 进程运行，禁止启动第二个（双进程竞态曾误删模型）")

    # R6: 禁止 Fooocus/ComfyUI 模型常驻于对话态
    if action == "switch_scene" and args.get("target") == "dialogue":
        if ctx.fooocus_running:
            violations.append("R6: 切换到对话态前必须停止 Fooocus 容器（白占 6.9GB）")
        # ComfyUI 在对话态可以运行但不能有模型常驻（budget 检查会覆盖）

    # R7: 禁止未过准入的新服务占用显存（由调用方确保已登记，这里检查registry）
    if action in ("load_model", "submit_task"):
        target = args.get("model", "")
        if target and not _model_in_registry(target, ctx):
            violations.append(f"R7: 模型 {target} 未在 registry.json 中登记，禁止占用显存（请先登记并评测）")

    passed = len(violations) == 0
    return {
        "passed": passed,
        "violations": violations,
        "detail": "铁律校验通过" if passed else f"违反 {len(violations)} 条铁律"
    }


def _check_budget(action: str, args: dict, ctx: GateContext) -> dict:
    """防线3：预算校验（实时显存 + registry 实测值）。"""
    if action not in ("load_model", "submit_task", "switch_scene", "start_service"):
        return {"passed": True, "detail": "只读/释放操作无需预算校验"}

    target_model = args.get("model") or args.get("target", "")
    target_vram = _get_model_vram(target_model, ctx)

    if target_vram <= 0:
        return {"passed": True, "detail": "目标模型显存未知，跳过预算校验（建议先评测）"}

    # 计算执行后预计显存
    # 场景切换到 comfy/fooocus/music/h3 时，会先释放 ollama 模型
    if action == "switch_scene":
        target = args.get("target", "")
        if target in ("comfy", "fooocus", "music", "h3"):
            # 这些场景会释放 ollama 模型，只保留底噪 + 目标模型
            estimated_after = ctx.base_noise_mb + target_vram * 1024
        else:
            estimated_after = ctx.vram_used_mb + target_vram * 1024
    else:
        estimated_after = ctx.vram_used_mb + target_vram * 1024

    # 危险线（动态阈值）
    danger_mb = ctx.danger_thresholds.get("danger_mb", int(ctx.vram_total_mb * 0.92))
    free_target_mb = ctx.danger_thresholds.get("free_target_mb", 2048)

    if estimated_after > danger_mb:
        need_free = estimated_after - (ctx.vram_total_mb - free_target_mb)
        return {
            "passed": False,
            "detail": f"预计峰值 {estimated_after/1024:.1f}GB 超过危险线 {danger_mb/1024:.1f}GB",
            "required_free_gb": round(need_free / 1024, 1)
        }

    # 当前空闲是否足够
    if ctx.vram_free_mb < target_vram * 1024:
        need_free = target_vram * 1024 - ctx.vram_free_mb + free_target_mb
        return {
            "passed": False,
            "detail": f"当前空闲 {ctx.vram_free_mb/1024:.1f}GB，目标模型需 {target_vram:.1f}GB + 保留 {free_target_mb/1024:.1f}GB",
            "required_free_gb": round(need_free / 1024, 1)
        }

    return {
        "passed": True,
        "detail": f"预算通过：预计峰值 {estimated_after/1024:.1f}GB，危险线 {danger_mb/1024:.1f}GB"
    }


def _get_model_vram(model_name: str, ctx: GateContext) -> float:
    """从 registry 获取模型显存（GB）。找不到返回 0。"""
    if not model_name:
        return 0
    for source, models in ctx.registry_models.items():
        for m in models:
            if m.get("id") == model_name or m.get("name") == model_name:
                return float(m.get("vram_gb", 0))
    # 从已加载模型中查找
    for m in ctx.loaded_ollama_models:
        if m.get("name") == model_name:
            return float(m.get("size_gb", 0))
    return 0


def _is_exclusive(model_name: str) -> bool:
    """判断模型是否需要独占全卡。"""
    if not model_name:
        return False
    name_lower = model_name.lower()
    return any(kw in name_lower for kw in ("flux", "27b", "wan2.2", "wan2", "ti2v"))


def _model_in_registry(model_name: str, ctx: GateContext) -> bool:
    """检查模型是否在 registry 中登记。"""
    for source, models in ctx.registry_models.items():
        for m in models:
            if m.get("id") == model_name or m.get("name") == model_name:
                return True
    return False


def check(action: str, args: dict, ctx: GateContext) -> dict:
    """
    准入闸门主入口：三道防线依次检查。

    Args:
        action: 操作类型（switch_scene / submit_task / load_model 等）
        args: 操作参数
        ctx: 当前状态上下文

    Returns:
        闸门结果 dict
    """
    # 防线1：格式
    fmt = _check_format(action, args)
    if not fmt["passed"]:
        return {
            "allowed": False,
            "reason": fmt["detail"],
            "required_free_gb": 0,
            "violated_rules": [],
            "checks": {"format": fmt, "rules": {"passed": True, "violations": [], "detail": "未执行"}, "budget": {"passed": True, "detail": "未执行"}}
        }

    # 防线2：铁律
    rules = _check_rules(action, args, ctx)

    # 防线3：预算（即使铁律失败也跑预算，给出完整信息）
    budget = _check_budget(action, args, ctx)

    allowed = rules["passed"] and budget["passed"]
    violated = rules["violations"]

    reason = ""
    if not allowed:
        reasons = []
        if violated:
            reasons.append("；".join(violated))
        if not budget["passed"]:
            reasons.append(budget["detail"])
        reason = "；".join(reasons)

    return {
        "allowed": allowed,
        "reason": reason,
        "required_free_gb": budget.get("required_free_gb", 0),
        "violated_rules": [v.split(":")[0] for v in violated],  # 提取 R1/R2...
        "checks": {"format": fmt, "rules": rules, "budget": budget}
    }


# === 独立运行测试：python admission_gate.py ===
if __name__ == "__main__":
    # 模拟上下文
    ctx = GateContext(
        vram_total_mb=16384,
        vram_used_mb=8000,
        vram_free_mb=8384,
        base_noise_mb=1200,
        current_scene="dialogue",
        loaded_ollama_models=[{"name": "qwen3.5:9b", "size_gb": 6.6}],
        loaded_comfy_models=[],
        comfyui_running=False,
        fooocus_running=False,
        registry_models={
            "comfyui": [
                {"id": "SDXL", "name": "SDXL 1.0", "vram_gb": 6.5, "exclusive": False},
                {"id": "Flux-Q5", "name": "Flux.1 dev Q5", "vram_gb": 13.0, "exclusive": True},
            ],
            "ollama": [
                {"id": "qwen3.5:9b", "name": "qwen3.5:9b", "vram_gb": 6.6, "exclusive": False, "ctx": 8192},
            ]
        },
        danger_thresholds={"danger_mb": 15073, "free_target_mb": 2457}
    )

    logger.info("=== 准入闸门测试 ===\n")

    # 测试1：加载 SDXL（应该通过，因为会先释放9b）
    r1 = check("submit_task", {"model": "SDXL", "params": {"prompt": "test"}}, ctx)
    logger.info(f"测试1 - 提交 SDXL 任务: allowed={r1['allowed']}, reason={r1['reason']}")

    # 测试2：加载 Flux（应该 R2 违规，因为已有9b）
    r2 = check("submit_task", {"model": "Flux-Q5", "params": {"prompt": "test"}}, ctx)
    logger.info(f"测试2 - 提交 Flux 任务: allowed={r2['allowed']}, violated={r2['violated_rules']}")

    # 测试3：加载模型 ctx 超 8K（应该 R3 违规）
    r3 = check("load_model", {"model": "qwen3.5:9b", "ctx": 32768}, ctx)
    logger.info(f"测试3 - 加载 9b@32K: allowed={r3['allowed']}, violated={r3['violated_rules']}")

    # 测试4：未知 action（应该格式失败）
    r4 = check("destroy_gpu", {}, ctx)
    logger.info(f"测试4 - 未知 action: allowed={r4['allowed']}, reason={r4['reason']}")

    # 测试5：未登记模型（应该 R7 违规）
    r5 = check("load_model", {"model": "unknown-model:7b"}, ctx)
    logger.info(f"测试5 - 未登记模型: allowed={r5['allowed']}, violated={r5['violated_rules']}")
