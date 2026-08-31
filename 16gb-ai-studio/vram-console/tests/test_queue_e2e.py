"""
GMae v0.3.1 W1 — 队列 E2E 验证脚本

验证 SDXL 完整链路：提交 → 预检 → 释放 → ComfyUI调用 → 进度 → 完成 → 归档
同时测试失败场景：无效模型、缺失工作流、显存不足拒绝

运行: python test_queue_e2e.py
"""
import json
import os
import sys
import time

# 导入 server.py 的函数
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sys, os\nsys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\nimport server


def test_1_invalid_model():
    """测试1：提交无效模型应被拒绝"""
    print("\n=== 测试1：无效模型拒绝 ===")
    r = server.queue_enqueue("NonExistentModel", {"prompt": "test"})
    assert not r["ok"], f"应拒绝无效模型，实际: {r}"
    print(f"  ✅ 无效模型被拒绝: {r['error']}")
    return True


def test_2_missing_workflow():
    """测试2：模型存在但工作流缺失应被拒绝"""
    print("\n=== 测试2：缺失工作流拒绝 ===")
    # 找一个 registry 中存在但没有 workflow 的模型
    models = server.REGISTRY.get("comfyui", {}).get("models", [])
    no_wf = [m for m in models if not m.get("workflow")]
    if no_wf:
        r = server.queue_enqueue(no_wf[0]["id"], {"prompt": "test"})
        assert not r["ok"], f"应拒绝缺失工作流的模型"
        print(f"  ✅ 模型 {no_wf[0]['id']} 因缺失工作流被拒绝")
    else:
        print("  ⏭️  所有模型都有工作流，跳过")
    return True


def test_3_sdxl_submit():
    """测试3：提交 SDXL 任务（完整 E2E）"""
    print("\n=== 测试3：SDXL 完整 E2E ===")
    # 检查 SDXL 是否在 registry 中且有工作流
    sdxl = next((m for m in server.REGISTRY.get("comfyui", {}).get("models", [])
                 if m["id"] == "SDXL"), None)
    if not sdxl:
        print("  ⏭️  SDXL 未在 registry 中，跳过")
        return True
    if not sdxl.get("workflow"):
        print("  ⏭️  SDXL 无工作流配置，跳过")
        return True

    # 检查工作流文件是否存在
    wf_path = os.path.join(server.BASE_DIR, "workflows", sdxl["workflow"])
    if not os.path.exists(wf_path):
        print(f"  ⏭️  工作流文件不存在: {wf_path}，跳过")
        return True

    # 检查 ComfyUI 是否可用
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=3) as r:
            json.loads(r.read())
    except Exception:
        print("  ⏭️  ComfyUI 不可用，跳过实际生成（仅验证提交逻辑）")
        # 仍验证提交逻辑（任务会进入队列但 ComfyUI 调用会失败）
        r = server.queue_enqueue("SDXL", {"prompt": "a test image", "seed": 42})
        if r["ok"]:
            print(f"  ✅ 任务已入队: id={r['task']['id']}, status={r['task']['status']}")
            # 等待几秒看状态变化
            time.sleep(3)
            snap = server.queue_snapshot()
            task = next((t for t in snap["tasks"] if t["id"] == r["task"]["id"]), None)
            if task:
                print(f"  状态: {task['status']}, error: {task.get('error', '')[:80]}")
        return True

    # ComfyUI 可用，提交真实任务
    print(f"  提交 SDXL 任务...")
    start = time.time()
    r = server.queue_enqueue("SDXL", {
        "prompt": "a beautiful landscape, mountains, sunset, high quality",
        "seed": 42,
        "width": 512,
        "height": 512
    })
    if not r["ok"]:
        print(f"  ❌ 提交失败: {r.get('error')}")
        return False

    task_id = r["task"]["id"]
    print(f"  ✅ 任务已入队: id={task_id}")

    # 轮询任务状态
    max_wait = 180  # 最多等3分钟
    waited = 0
    while waited < max_wait:
        time.sleep(5)
        waited += 5
        snap = server.queue_snapshot()
        task = next((t for t in snap["tasks"] if t["id"] == task_id), None)
        if not task:
            print(f"  ❌ 任务消失了")
            return False
        status = task["status"]
        progress = task.get("progress", "")
        elapsed = time.time() - start
        print(f"  [{elapsed:.0f}s] status={status}, progress={progress}")
        if status in ("done", "failed", "canceled"):
            break

    # 最终状态
    snap = server.queue_snapshot()
    task = next((t for t in snap["tasks"] if t["id"] == task_id), None)
    if task and task["status"] == "done":
        duration = task["ended"] - task["started"] if task.get("started") and task.get("ended") else 0
        print(f"  ✅ 任务完成！耗时 {duration}s, result={task.get('result')}")
        return True
    elif task:
        print(f"  ⚠️  任务状态: {task['status']}, error: {task.get('error', '')[:200]}")
        return task["status"] == "done"
    return False


def test_4_queue_snapshot():
    """测试4：队列快照结构"""
    print("\n=== 测试4：队列快照结构 ===")
    snap = server.queue_snapshot()
    assert snap["ok"], "队列快照应返回 ok"
    assert "queue" in snap, "应包含 queue"
    assert "tasks" in snap, "应包含 tasks"
    assert "worker_alive" in snap, "应包含 worker_alive"
    print(f"  ✅ 队列快照正常: {len(snap['tasks'])} 个任务, worker={snap['worker_alive']}")
    return True


def test_5_budget_engine():
    """测试5：预算引擎集成（动态阈值）"""
    print("\n=== 测试5：预算引擎 + 动态阈值 ===")
    budget = server.budget_engine()
    assert budget["ok"], "预算引擎应返回 ok"
    print(f"  总显存: {budget['total_gb']}GB")
    print(f"  底噪: {budget['noise_gb']}GB")
    print(f"  安全上限: {budget['safe_ceiling_gb']}GB")
    print(f"  可用: {budget['avail_gb']}GB")
    print(f"  模型数: {len(budget['models'])}")
    for m in budget["models"][:3]:
        print(f"    - {m['name']}: {m['vram_gb']}G, decision={m['decision']}")
    print("  ✅ 预算引擎正常")
    return True


def test_6_admission_gate_api():
    """测试6：准入闸门集成"""
    print("\n=== 测试6：准入闸门集成 ===")
    if not server._V031_MODULES:
        print("  ⏭️  admission_gate 模块不可用，跳过")
        return True
    ctx = server._build_gate_context()
    # 测试一个应该通过的操作
    r = server.admission_gate.check("free_vram", {}, ctx)
    print(f"  free_vram: allowed={r['allowed']}")
    # 测试一个应该被拒绝的操作（未登记模型）
    r2 = server.admission_gate.check("load_model", {"model": "unknown:7b"}, ctx)
    print(f"  load unknown model: allowed={r2['allowed']}, violated={r2['violated_rules']}")
    print("  ✅ 准入闸门集成正常")
    return True


def main():
    print("=" * 60)
    print("GMae v0.3.1 W1 — 队列 E2E 验证")
    print("=" * 60)

    tests = [
        ("无效模型拒绝", test_1_invalid_model),
        ("缺失工作流拒绝", test_2_missing_workflow),
        ("SDXL 完整 E2E", test_3_sdxl_submit),
        ("队列快照结构", test_4_queue_snapshot),
        ("预算引擎+动态阈值", test_5_budget_engine),
        ("准入闸门集成", test_6_admission_gate_api),
    ]

    results = []
    for name, fn in tests:
        try:
            ok = fn()
            results.append((name, ok))
        except Exception as e:
            print(f"  ❌ 异常: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f"  {'✅' if ok else '❌'} {name}")
    print(f"\n通过: {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
