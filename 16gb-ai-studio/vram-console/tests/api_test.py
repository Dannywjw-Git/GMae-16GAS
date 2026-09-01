#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae API 自动化测试脚本
用法：python tests/api_test.py [--base-url http://127.0.0.1:8787] [--token <token>]
覆盖：健康检查、状态查询、显存管理、场景切换、队列、QoS、认证等所有端点
"""
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# ============================================================
# 配置
# ============================================================
BASE_URL = "http://127.0.0.1:8787"
API_TOKEN = ""
TIMEOUT = 30

# 测试结果统计
results = {"pass": 0, "fail": 0, "skip": 0, "errors": []}


def load_token():
    """从 .api_token 文件加载 token"""
    global API_TOKEN
    token_file = Path(__file__).parent.parent / ".api_token"
    if token_file.exists():
        API_TOKEN = token_file.read_text(encoding="utf-8").strip()


# ============================================================
# 辅助函数
# ============================================================

def _normalize(body):
    """自动识别 v0/v1 格式，统一为扁平格式（兼容测试）。
    v1: {ok, data, error, meta} → 扁平: {ok, ...data字段, error}
    """
    if isinstance(body, dict) and 'data' in body and 'meta' in body:
        normalized = {'ok': body.get('ok', False)}
        data = body.get('data')
        if isinstance(data, dict):
            normalized.update(data)
        elif data is not None:
            normalized['data'] = data
        err = body.get('error')
        if err:
            if isinstance(err, dict):
                normalized['error'] = err.get('message', str(err))
                normalized['error_code'] = err.get('code', '')
            else:
                normalized['error'] = str(err)
        return normalized
    return body


def api_get(path, params=None, auth=True):
    """发送 GET 请求"""
    url = BASE_URL + path
    if params:
        query = "&".join("%s=%s" % (k, v) for k, v in params.items())
        url += "?" + query
    headers = {}
    if auth and API_TOKEN:
        headers["X-API-Key"] = API_TOKEN
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, _normalize(json.loads(resp.read().decode("utf-8")))
    except urllib.error.HTTPError as e:
        try:
            body = _normalize(json.loads(e.read().decode("utf-8")))
        except Exception:
            body = {"error": str(e)}
        return e.code, body
    except Exception as e:
        return -1, {"error": str(e)}


def api_post(path, data=None, auth=True):
    """发送 POST 请求"""
    url = BASE_URL + path
    headers = {"Content-Type": "application/json"}
    if auth and API_TOKEN:
        headers["X-API-Key"] = API_TOKEN
    body = json.dumps(data or {}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, _normalize(json.loads(resp.read().decode("utf-8")))
    except urllib.error.HTTPError as e:
        try:
            body = _normalize(json.loads(e.read().decode("utf-8")))
        except Exception:
            body = {"error": str(e)}
        return e.code, body
    except Exception as e:
        return -1, {"error": str(e)}


def test(name, condition, detail=""):
    """记录测试结果"""
    if condition:
        results["pass"] += 1
        print("  [PASS] %s" % name)
    else:
        results["fail"] += 1
        results["errors"].append({"name": name, "detail": detail})
        print("  [FAIL] %s — %s" % (name, detail))


def skip(name, reason=""):
    """记录跳过的测试"""
    results["skip"] += 1
    print("  [SKIP] %s — %s" % (name, reason))


def assert_ok(resp, name):
    """断言响应 ok=True"""
    status, body = resp
    test("%s (HTTP %d)" % (name, status), status == 200 and body.get("ok") is True,
         "status=%d, body=%s" % (status, str(body)[:200]))
    return body


def assert_has_fields(body, fields, name):
    """断言响应包含指定字段"""
    missing = [f for f in fields if f not in body]
    test("%s 字段完整" % name, len(missing) == 0,
         "缺失字段: %s" % missing if missing else "")


# ============================================================
# 测试用例
# ============================================================

def test_health():
    """模块1：健康检查（公开端点）"""
    print("\n=== 模块1：健康检查 ===")
    status, body = api_get("/api/health", auth=False)
    test("health HTTP 200", status == 200, "status=%d" % status)
    test("health ok=True", body.get("ok") is True, "body=%s" % str(body)[:200])
    assert_has_fields(body, ["ok", "ts", "services"], "health")


def test_auth_status():
    """模块2：认证状态"""
    print("\n=== 模块2：认证状态 ===")
    status, body = api_get("/api/auth/status", auth=False)
    test("auth/status HTTP 200", status == 200, "status=%d" % status)
    assert_has_fields(body, ["ok", "has_admin"], "auth/status")

def test_status():
    """模块3：状态查询"""
    print("\n=== 模块3：状态查询 ===")
    body = assert_ok(api_get("/api/status"), "status")
    if body.get("ok"):
        assert_has_fields(body, ["ok", "gpu", "containers"], "status")
        # GPU 状态字段
        gpu = body.get("gpu", {})
        test("status.gpu 包含显存信息", all(k in gpu for k in ["total_mb", "used_mb", "free_mb"]),
             "gpu keys=%s" % list(gpu.keys()))


def test_logs():
    """模块4：日志查询"""
    print("\n=== 模块4：日志查询 ===")
    body = assert_ok(api_get("/api/logs"), "logs")
    if body.get("ok"):
        test("logs 返回数组", isinstance(body.get("logs", []), list),
             "logs type=%s" % type(body.get("logs")))


def test_registry():
    """模块5：注册表"""
    print("\n=== 模块5：注册表 ===")
    body = assert_ok(api_get("/api/registry"), "registry")
    if body.get("ok"):
        assert_has_fields(body, ["ok", "scenes", "ollama_models", "comfyui_models"], "registry")
        scenes = body.get("scenes", {})
        test("registry.scenes 包含6个场景", len(scenes) >= 6,
             "scenes count=%d" % len(scenes))
        # 验证场景配置包含 steps
        for sid, sc in scenes.items():
            test("scene.%s 包含 steps" % sid, "steps" in sc,
                 "scene %s keys=%s" % (sid, list(sc.keys())))


def test_budget():
    """模块6：预算引擎"""
    print("\n=== 模块6：预算引擎 ===")
    body = assert_ok(api_get("/api/budget"), "budget")
    if body.get("ok"):
        assert_has_fields(body, ["ok", "total_gb", "models"], "budget")


def test_queue():
    """模块7：队列"""
    print("\n=== 模块7：队列 ===")
    body = assert_ok(api_get("/api/queue"), "queue")
    if body.get("ok"):
        assert_has_fields(body, ["ok", "queue", "tasks"], "queue")


def test_advice():
    """模块8：显存建议"""
    print("\n=== 模块8：显存建议 ===")
    body = assert_ok(api_get("/api/advice"), "advice")
    if body.get("ok"):
        assert_has_fields(body, ["ok", "suggestions"], "advice")


def test_hardware():
    """模块9：硬件信息"""
    print("\n=== 模块9：硬件信息 ===")
    status, body = api_get("/api/hardware")
    test("hardware HTTP 200", status == 200, "status=%d" % status)
    if status == 200:
        assert_has_fields(body, ["ok", "profile"], "hardware")


def test_scene_switch():
    """模块10：场景切换（测试 dialogue 场景，安全）"""
    print("\n=== 模块10：场景切换 ===")
    # 无效场景
    status, body = api_post("/api/scene", {"scene": "invalid_scene"})
    test("scene 无效场景返回 ok=False", body.get("ok") is False,
         "body=%s" % str(body)[:200])
    test("scene 无效场景包含 error", "error" in body, "body=%s" % str(body)[:200])

    # 有效场景：dialogue（只停止容器，安全）
    body = assert_ok(api_post("/api/scene", {"scene": "dialogue"}), "scene dialogue")
    if body.get("ok"):
        assert_has_fields(body, ["ok", "scene", "actions", "duration_ms"], "scene result")
        test("scene.actions 是数组", isinstance(body.get("actions", []), list),
             "actions type=%s" % type(body.get("actions")))
        test("scene 返回预算检查", "budget_check" in body, "budget_check missing")


def test_free():
    """模块11：一键释放"""
    print("\n=== 模块11：一键释放 ===")
    body = assert_ok(api_post("/api/free"), "free")
    if body.get("ok"):
        assert_has_fields(body, ["ok", "freed_mb", "free_mb_before", "free_mb_after",
                                  "stopped", "running", "success_count", "total_count"], "free")
        test("free.stopped 是数组", isinstance(body.get("stopped", []), list))
        test("free.running 是数组", isinstance(body.get("running", []), list))
        test("free.success_count <= total_count",
             body.get("success_count", 0) <= body.get("total_count", 0),
             "success=%d, total=%d" % (body.get("success_count"), body.get("total_count")))


def test_combo():
    """模块12：组合切换"""
    print("\n=== 模块12：组合切换 ===")
    # 无效组合
    status, body = api_post("/api/combo", {"combo": "invalid_combo"})
    test("combo 无效组合返回 ok=False", body.get("ok") is False,
         "body=%s" % str(body)[:200])


def test_model_action():
    """模块13：模型操作"""
    print("\n=== 模块13：模型操作 ===")
    # 无效模型名（格式校验）
    status, body = api_post("/api/model", {"name": "invalid;rm -rf /", "action": "stop"})
    test("model 非法名称被拒绝", body.get("ok") is False,
         "body=%s" % str(body)[:200])

    # 无效操作
    status, body = api_post("/api/model", {"name": "test", "action": "invalid"})
    test("model 无效操作被拒绝", body.get("ok") is False,
         "body=%s" % str(body)[:200])


def test_service_action():
    """模块14：服务操作"""
    print("\n=== 模块14：服务操作 ===")
    # 无效服务
    status, body = api_post("/api/service", {"name": "invalid", "action": "status"})
    test("service 无效服务被拒绝", body.get("ok") is False,
         "body=%s" % str(body)[:200])


def test_qos():
    """模块15：QoS"""
    print("\n=== 模块15：QoS ===")
    body = assert_ok(api_post("/api/qos/status"), "qos/status")
    if body.get("ok"):
        assert_has_fields(body, ["ok", "level", "config"], "qos/status")


def test_auto_protect():
    """模块16：自动保护"""
    print("\n=== 模块16：自动保护 ===")
    body = assert_ok(api_get("/api/auto-protect/status"), "auto-protect/status")
    if body.get("ok"):
        assert_has_fields(body, ["ok", "enabled"], "auto-protect/status")


def test_helper():
    """模块17：Helper 状态"""
    print("\n=== 模块17：Helper ===")
    status, body = api_get("/api/desktop/helper/status")
    test("helper/status HTTP 200", status == 200, "status=%d" % status)
    if status == 200:
        assert_has_fields(body, ["ok", "running"], "helper/status")


def test_desktop_vram():
    """模块18：桌面显存"""
    print("\n=== 模块18：桌面显存 ===")
    status, body = api_get("/api/desktop_vram")
    test("desktop_vram HTTP 200", status == 200, "status=%d" % status)


def test_scan():
    """模块19：模型扫描"""
    print("\n=== 模块19：模型扫描 ===")
    body = assert_ok(api_get("/api/scan"), "scan")
    if body.get("ok"):
        assert_has_fields(body, ["ok", "sources"], "scan")


def test_comfy_events():
    """模块20：ComfyUI 事件"""
    print("\n=== 模块20：ComfyUI 事件 ===")
    status, body = api_get("/api/comfy_events")
    test("comfy_events HTTP 200", status == 200, "status=%d" % status)


def test_404():
    """模块21：404 处理"""
    print("\n=== 模块21：404 处理 ===")
    status, body = api_get("/api/nonexistent_endpoint")
    test("不存在端点返回 404", status == 404, "status=%d" % status)
    test("404 响应包含 ok=False", body.get("ok") is False, "body=%s" % str(body)[:200])


def test_unauthorized():
    """模块22：未授权访问"""
    print("\n=== 模块22：未授权访问 ===")
    # 只有在已配置管理员时才测试
    status, auth_body = api_get("/api/auth/status", auth=False)
    if auth_body.get("has_admin"):
        status, body = api_get("/api/status", auth=False)
        test("未授权访问 status 返回 401", status == 401, "status=%d" % status)
    else:
        skip("未授权测试", "未配置管理员，所有端点公开")


# ============================================================
# 主流程
# ============================================================

def main():
    global BASE_URL
    # 解析命令行参数
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--base-url" and i + 1 < len(args):
            BASE_URL = args[i + 1]
            i += 2
        elif args[i] == "--token" and i + 1 < len(args):
            global API_TOKEN
            API_TOKEN = args[i + 1]
            i += 2
        else:
            i += 1

    load_token()
    print("GMae API 自动化测试")
    print("目标: %s" % BASE_URL)
    print("Token: %s" % ("已配置" if API_TOKEN else "未配置（将测试公开端点）"))
    print("=" * 60)

    start_time = time.time()

    # 执行所有测试
    test_health()
    test_auth_status()
    test_status()
    test_logs()
    test_registry()
    test_budget()
    test_queue()
    test_advice()
    test_hardware()
    test_scene_switch()
    test_free()
    test_combo()
    test_model_action()
    test_service_action()
    test_qos()
    test_auto_protect()
    test_helper()
    test_desktop_vram()
    test_scan()
    test_comfy_events()
    test_404()
    test_unauthorized()

    # 输出报告
    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print("测试报告")
    print("=" * 60)
    print("通过: %d" % results["pass"])
    print("失败: %d" % results["fail"])
    print("跳过: %d" % results["skip"])
    print("耗时: %.1f 秒" % elapsed)
    print("=" * 60)

    if results["errors"]:
        print("\n失败详情:")
        for err in results["errors"]:
            print("  - %s: %s" % (err["name"], err["detail"]))

    return 0 if results["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
