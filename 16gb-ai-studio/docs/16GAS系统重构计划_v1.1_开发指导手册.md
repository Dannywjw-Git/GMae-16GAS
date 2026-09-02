# 16GAS 系统重构计划 v1.1（开发指导手册）

> **文档性质**：可执行开发指导（每个子任务含具体文件/类/函数/API/测试/DoD）
> **创建日期**：2026-09-01
> **基于**：`16GAS系统重构计划_v1.0.md` + `可观测能力增强方案_借鉴ZSvirt命题.md`
> **适用对象**：执行重构的 AI Agent / 开发者
> **大赛节点**：截止 10-11

---

## 通用开发规范（所有阶段必须遵守）

### 代码规范
- **语言**：Python 3.10+（后端），原生 ES Module JavaScript（前端，零构建）
- **后端模块路径**：`vram-console/api/endpoints/`（API 端点）、`vram-console/engine/`（业务引擎）、`vram-console/core/`（基础设施）
- **命名**：Python 用 snake_case，类用 PascalCase；JS 用 camelCase，组件用 PascalCase
- **零新增第三方依赖**：后端只用 Python 标准库；前端只用浏览器原生 API + 现有组件
- **认证**：所有新增 API 必须走认证（Session Cookie 或 X-API-Key），公开路径仅限 `/api/health`、`/api/auth/*`
- **写操作后必须失效 S1 的状态缓存**（调用 `status_cache.invalidate()`）

### 测试规范
- 每个新建引擎模块必须配套单元测试，放在 `vram-console/tests/`
- 测试命名：`test_<模块名>.py`，用 Python 标准库 `unittest`
- 每个公开方法至少 1 个正例 + 1 个反例
- 运行方式：`python tests/run_tests.py <模块名>`（工作目录 vram-console）
- 重构完成后必须运行全量测试：`python tests/run_tests.py`

### 文档规范
- 每个新建模块顶部写 docstring：用途、核心类、依赖
- 每个公开函数写 docstring：参数、返回值、异常
- 重大变更后更新：`工作交接.md`（根目录）、`开发日志.md`、`项目进度跟踪.md`
- 蓝图偏差：代码与蓝图不一致时登记到 `项目进度跟踪.md` 第八章，不擅自改蓝图

### 显存安全
- 所有新增功能不得加载新模型、不得启动新 GPU 进程
- 故障注入脚本执行前必须检查当前显存，空闲 <4GB 时拒绝高显存压力注入
- 遵循 `docs/显存管理最高指南.md`

---

## S0：已完成（2026-09-01）

> 以下为已完成项的状态记录，供后续阶段参考。

| 项目 | 交付物 | 验证状态 |
|------|--------|---------|
| 中间层重构 | `api/endpoints/` 12 模块 45 端点 + `api/router.py` + `api/middleware.py` + `api/request.py` + `api/response.py` | ✅ 全量冒烟通过 |
| 前端存档 | `legacy/web_v2_archive/` + `legacy/v1-index.html`，根路径占位页 | ✅ 验证通过 |
| watchdog bug | `/api/health` 直接返回 `health_check()` 原始 dict（顶层含 services） | ✅ watchdog 稳定 |

**后续阶段的代码修改入口**：
- 新增 API 端点 → 在 `api/endpoints/` 新建模块，用 `@router.get/post` 装饰器注册，在 `api/endpoints/__init__.py` 中导入
- 新增业务引擎 → 在 `engine/` 新建模块
- 状态缓存 → S1 新建 `core/status_cache.py`
- 写操作后失效缓存 → 调用 `from core.status_cache import status_cache; status_cache.invalidate()`

---

## S1：轻量采集优化（P0，4 人天）

> **目标**：`/api/status` 热路径从 13-17 秒降至 <3 秒；缓存命中 <500ms
> **前置条件**：S0 完成，服务稳定运行
> **后置条件**：所有写操作端点已接入缓存失效；Docker events 后台线程运行中

### S1.1 指标缓存层（1.5 人天）

#### 新建文件：`vram-console/core/status_cache.py`

```python
"""
状态缓存模块 — 为 /api/status 提供 TTL 缓存，减少 docker exec 调用。

核心类：
- StatusCache: 单例缓存管理器，支持 get/set/invalidate/is_stale

设计要点：
- TTL 默认 10 秒，危险状态时缩短为 2 秒
- 缓存失效时后台异步刷新（不阻塞请求，返回旧数据 + stale 标记）
- 写操作后主动调用 invalidate()
- 线程安全（threading.Lock）
"""

import threading
import time
import json
from typing import Optional, Dict, Any


class StatusCache:
    def __init__(self, ttl_seconds: float = 10.0, danger_ttl_seconds: float = 2.0):
        self._ttl = ttl_seconds
        self._danger_ttl = danger_ttl_seconds
        self._cache: Optional[Dict[str, Any]] = None
        self._cached_at: float = 0.0
        self._lock = threading.Lock()
        self._refreshing = False
        self._refresh_thread: Optional[threading.Thread] = None

    def get(self) -> Optional[Dict[str, Any]]:
        """获取缓存。返回 None 表示缓存不存在或已过期。"""
        with self._lock:
            if self._cache is None:
                return None
            age = time.time() - self._cached_at
            # 危险状态时用更短的 TTL
            danger_level = self._cache.get("data", {}).get("vram_ledger", {}).get("danger_level", "safe")
            ttl = self._danger_ttl if danger_level in ("danger", "critical") else self._ttl
            if age > ttl:
                return None
            # 返回副本，避免外部修改缓存
            return json.loads(json.dumps(self._cache))

    def get_stale(self) -> Optional[Dict[str, Any]]:
        """获取缓存（即使已过期），用于后台刷新时返回旧数据。"""
        with self._lock:
            if self._cache is None:
                return None
            result = json.loads(json.dumps(self._cache))
            result["cached"] = True
            result["cached_at"] = self._cached_at
            result["stale"] = True
            return result

    def set(self, data: Dict[str, Any]) -> None:
        """设置缓存。"""
        with self._lock:
            self._cache = json.loads(json.dumps(data))
            self._cached_at = time.time()

    def invalidate(self) -> None:
        """失效缓存（写操作后调用）。"""
        with self._lock:
            self._cache = None
            self._cached_at = 0.0

    def is_expired(self) -> bool:
        """检查缓存是否已过期。"""
        with self._lock:
            if self._cache is None:
                return True
            age = time.time() - self._cached_at
            danger_level = self._cache.get("data", {}).get("vram_ledger", {}).get("danger_level", "safe")
            ttl = self._danger_ttl if danger_level in ("danger", "critical") else self._ttl
            return age > ttl

    def try_background_refresh(self, refresh_func) -> Optional[Dict[str, Any]]:
        """
        尝试后台刷新缓存。
        - 如果缓存未过期，直接返回缓存
        - 如果缓存已过期且有旧数据，启动后台刷新线程，返回旧数据（stale=True）
        - 如果缓存已过期且无旧数据，同步执行刷新，返回新数据
        """
        cached = self.get()
        if cached is not None:
            cached["cached"] = True
            cached["cached_at"] = self._cached_at
            cached["stale"] = False
            return cached

        stale = self.get_stale()
        if stale is not None and not self._refreshing:
            # 有旧数据，后台刷新
            self._refreshing = True
            self._refresh_thread = threading.Thread(
                target=self._do_refresh,
                args=(refresh_func,),
                daemon=True
            )
            self._refresh_thread.start()
            return stale

        # 无旧数据，同步刷新
        if not self._refreshing:
            self._refreshing = True
            try:
                new_data = refresh_func()
                self.set(new_data)
                return new_data
            finally:
                self._refreshing = False
        else:
            # 正在刷新，等待短暂时间后重试
            time.sleep(0.5)
            return self.get() or self.get_stale()

    def _do_refresh(self, refresh_func) -> None:
        """后台刷新执行体。"""
        try:
            new_data = refresh_func()
            self.set(new_data)
        except Exception:
            pass  # 后台刷新失败不影响服务，保留旧数据
        finally:
            self._refreshing = False


# 全局单例
status_cache = StatusCache()
```

#### 修改文件：`vram-console/api/endpoints/status.py`

在 `get_status` 函数中接入缓存：

```python
from core.status_cache import status_cache

def _build_status() -> dict:
    """构建完整 status 响应（原有的 status 构建逻辑，从旧代码中提取）。
    这个函数执行所有 docker exec 调用，是慢路径。
    """
    # TODO: 从原有的 status 构建逻辑中提取到这里
    # 包含：nvidia-smi、docker ps、ollama ps、comfyui 模型状态、helper 状态等
    pass

@router.get("/api/status")
def get_status(req: Request) -> Response:
    # 尝试从缓存获取，过期则后台刷新
    result = status_cache.try_background_refresh(_build_status)
    if result is None:
        return _error("status build failed", 500)
    return Response.json(result)
```

**关键**：需要把原有的 status 构建逻辑（当前在 `api/endpoints/status.py` 的 `get_status` 中，或在 `server.py` 的某个函数中）提取为独立的 `_build_status()` 函数，作为缓存的 refresh_func。

#### 修改文件：所有写操作端点

在以下端点的写操作成功后，调用 `status_cache.invalidate()`：

| 文件 | 端点 | 失效时机 |
|------|------|---------|
| `api/endpoints/vram.py` | `POST /api/free` | 释放显存成功后 |
| `api/endpoints/scene.py` | `POST /api/scene` | 场景切换成功后 |
| `api/endpoints/scene.py` | `POST /api/combo` | 组合切换成功后 |
| `api/endpoints/guard.py` | `POST /api/guard`（action=kick/evict） | 驱逐进程成功后 |
| `api/endpoints/service.py` | `POST /api/service` | 服务启停成功后 |
| `api/endpoints/service.py` | `POST /api/model` | 模型加载/卸载成功后 |
| `api/endpoints/service.py` | `POST /api/container/stop` | 容器停止成功后 |
| `api/endpoints/queue.py` | `POST /api/queue` | 任务提交成功后 |
| `api/endpoints/queue.py` | `POST /api/queue/cancel` | 任务取消成功后 |

每个端点添加：
```python
from core.status_cache import status_cache
# ... 写操作成功后 ...
status_cache.invalidate()
```

#### 新建测试：`vram-console/tests/test_status_cache.py`

```python
import unittest
import time
import sys
sys.path.insert(0, ".")
from core.status_cache import StatusCache


class TestStatusCache(unittest.TestCase):
    def setUp(self):
        self.cache = StatusCache(ttl_seconds=0.5, danger_ttl_seconds=0.2)

    def test_set_and_get(self):
        data = {"ok": True, "data": {"vram_ledger": {"danger_level": "safe"}}}
        self.cache.set(data)
        result = self.cache.get()
        self.assertIsNotNone(result)
        self.assertTrue(result["ok"])

    def test_expiry(self):
        data = {"ok": True, "data": {"vram_ledger": {"danger_level": "safe"}}}
        self.cache.set(data)
        time.sleep(0.6)
        self.assertIsNone(self.cache.get())

    def test_invalidate(self):
        data = {"ok": True, "data": {"vram_ledger": {"danger_level": "safe"}}}
        self.cache.set(data)
        self.cache.invalidate()
        self.assertIsNone(self.cache.get())

    def test_danger_shorter_ttl(self):
        data = {"ok": True, "data": {"vram_ledger": {"danger_level": "critical"}}}
        self.cache.set(data)
        time.sleep(0.3)
        self.assertIsNone(self.cache.get())  # danger TTL=0.2s，已过期

    def test_get_returns_copy(self):
        data = {"ok": True, "data": {"vram_ledger": {"danger_level": "safe"}}}
        self.cache.set(data)
        result = self.cache.get()
        result["ok"] = False
        # 原缓存不应被修改
        self.assertTrue(self.cache.get()["ok"])

    def test_background_refresh_with_stale(self):
        # 先设置缓存
        data = {"ok": True, "data": {"vram_ledger": {"danger_level": "safe"}}, "version": 1}
        self.cache.set(data)
        time.sleep(0.6)  # 过期

        refresh_called = []
        def refresh_func():
            refresh_called.append(True)
            return {"ok": True, "data": {"vram_ledger": {"danger_level": "safe"}}, "version": 2}

        # 第一次调用应返回 stale 数据（version=1），并启动后台刷新
        result = self.cache.try_background_refresh(refresh_func)
        self.assertEqual(result["version"], 1)
        self.assertTrue(result["stale"])

        # 等待后台刷新完成
        time.sleep(0.5)
        # 第二次调用应返回新数据（version=2）
        result2 = self.cache.try_background_refresh(refresh_func)
        self.assertEqual(result2["version"], 2)
        self.assertFalse(result2["stale"])


if __name__ == "__main__":
    unittest.main()
```

#### S1.1 完成定义（DoD）
- [ ] `core/status_cache.py` 存在，`StatusCache` 类实现上述所有方法
- [ ] `api/endpoints/status.py` 的 `get_status` 接入 `try_background_refresh`
- [ ] 9 个写操作端点全部调用 `status_cache.invalidate()`
- [ ] `test_status_cache.py` 7 个测试全部通过
- [ ] 连续调用 `/api/status` 5 次，第 2-5 次响应 <500ms
- [ ] 调用 `/api/free` 后立即调用 `/api/status`，返回最新数据（无 stale 标记）

---

### S1.2 Docker Events API（1 人天）

#### 新建文件：`vram-console/core/docker_events.py`

```python
"""
Docker 事件监听模块 — 用 `docker events` 命令流式监听容器状态变化，
维护内存中的容器状态表，替代 /api/status 中的 docker exec ps 轮询。

核心类：
- DockerEventsMonitor: 后台线程监听 docker events，维护 container_states 字典

设计要点：
- 用 subprocess.Popen 启动 `docker events --format '{{json .}}'`，逐行读取
- 解析 JSON 事件，更新 container_states（running/stopped/exited）
- 线程安全（threading.Lock）
- 服务停止时优雅退出（daemon=True + stop() 方法）
- Windows 兼容：用 docker events 命令，不依赖 Docker SDK 或 TCP API
- 降级方案：如果 docker events 启动失败，container_states 返回 None，
  /api/status 回退到 docker exec ps
"""

import subprocess
import json
import threading
import time
from typing import Dict, Optional, Set


class DockerEventsMonitor:
    def __init__(self):
        self._states: Dict[str, str] = {}  # container_name -> "running" | "stopped" | "exited"
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._available = False  # docker events 是否成功启动

    def start(self) -> bool:
        """启动事件监听线程。返回 True 表示成功启动，False 表示失败（降级）。"""
        try:
            self._process = subprocess.Popen(
                ["docker", "events", "--format", "{{json .}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            self._running = True
            self._available = True
            self._thread = threading.Thread(target=self._read_events, daemon=True)
            self._thread.start()
            # 初始同步：用 docker ps 填充当前状态
            self._initial_sync()
            return True
        except Exception:
            self._available = False
            return False

    def stop(self) -> None:
        """停止事件监听。"""
        self._running = False
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass

    def get_container_state(self, container_name: str) -> Optional[str]:
        """获取容器状态。返回 None 表示未知（监控不可用或容器未出现过）。"""
        with self._lock:
            return self._states.get(container_name)

    def get_all_states(self) -> Dict[str, str]:
        """获取所有容器状态的副本。"""
        with self._lock:
            return dict(self._states)

    def is_available(self) -> bool:
        """docker events 监控是否可用。"""
        return self._available

    def _initial_sync(self) -> None:
        """初始同步：用 docker ps 获取当前运行中的容器。"""
        try:
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}} {{.Status}}"],
                capture_output=True, text=True, timeout=10
            )
            with self._lock:
                for line in result.stdout.strip().split("\n"):
                    if line:
                        parts = line.split(" ", 1)
                        if len(parts) == 2:
                            name, status = parts
                            self._states[name] = "running" if "Up" in status else "exited"
        except Exception:
            pass

    def _read_events(self) -> None:
        """后台线程：逐行读取 docker events 输出。"""
        if not self._process or not self._process.stdout:
            return
        try:
            for line in self._process.stdout:
                if not self._running:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    self._handle_event(event)
                except json.JSONDecodeError:
                    continue
        except Exception:
            self._available = False

    def _handle_event(self, event: dict) -> None:
        """处理单个 docker 事件。"""
        event_type = event.get("Type", "")
        action = event.get("Action", "")
        actor = event.get("Actor", {})
        attributes = actor.get("Attributes", {})
        container_name = attributes.get("name", actor.get("ID", ""))

        if event_type != "container" or not container_name:
            return

        with self._lock:
            if action == "start":
                self._states[container_name] = "running"
            elif action in ("stop", "die", "kill"):
                self._states[container_name] = "exited"
            elif action == "restart":
                self._states[container_name] = "running"
            elif action == "destroy":
                self._states.pop(container_name, None)


# 全局单例
docker_events = DockerEventsMonitor()
```

#### 修改文件：`vram-console/server.py`（服务启动/停止钩子）

在 server 启动时调用 `docker_events.start()`，停止时调用 `docker_events.stop()`。

如果 server.py 没有明确的启动/停止钩子，可以在 `server.py` 的 `if __name__ == "__main__"` 块中添加：
```python
from core.docker_events import docker_events

if __name__ == "__main__":
    docker_events.start()  # 启动 docker events 监控
    try:
        # 原有启动逻辑
        httpd = ThreadingHTTPServer(...)
        httpd.serve_forever()
    finally:
        docker_events.stop()  # 停止监控
```

#### 修改文件：`vram-console/api/endpoints/status.py`

在 `_build_status()` 中，容器状态优先从 `docker_events` 获取，不可用时回退到 docker exec：

```python
from core.docker_events import docker_events

def _get_container_status(name: str) -> dict:
    """获取容器状态，优先用 docker events 内存表，失败回退 docker exec。"""
    if docker_events.is_available():
        state = docker_events.get_container_state(name)
        if state is not None:
            return {"ok": state == "running", "state": state, "source": "events"}
    # 回退：docker exec
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True, text=True, timeout=5
        )
        running = result.stdout.strip() == "true"
        return {"ok": running, "state": "running" if running else "exited", "source": "docker_inspect"}
    except Exception:
        return {"ok": False, "state": "unknown", "source": "error"}
```

#### S1.2 完成定义（DoD）
- [ ] `core/docker_events.py` 存在，`DockerEventsMonitor` 类实现上述所有方法
- [ ] server 启动时调用 `docker_events.start()`，停止时调用 `stop()`
- [ ] `_build_status()` 中容器状态优先用 docker events，不可用时回退
- [ ] 启动/停止一个 Docker 容器，`/api/status` 中容器状态 5 秒内更新
- [ ] docker events 不可用时（如 Docker 未运行），服务正常启动，status 回退到 docker exec
- [ ] 现有测试全部通过

---

### S1.3 并行化 docker exec（0.5 人天）

#### 修改文件：`vram-console/api/endpoints/status.py`

在 `_build_status()` 中，对以下独立调用用 `concurrent.futures.ThreadPoolExecutor` 并行执行：

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _build_status() -> dict:
    # ...  nvidia-smi（单独，最快） ...

    # 并行执行 3 个独立的 docker 调用
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            "ollama": executor.submit(_get_ollama_status),
            "comfyui": executor.submit(_get_comfyui_status),
            "containers": executor.submit(_get_all_container_statuses),
        }
        results = {}
        for name, future in as_completed(futures):
            try:
                results[name] = future.result(timeout=15)
            except Exception:
                results[name] = {"ok": False, "error": "timeout"}

    # ... 组装最终响应 ...
```

需要把原有的 ollama/comfyui/容器状态查询逻辑分别提取为独立函数：
- `_get_ollama_status()` → 返回 ollama 状态 dict
- `_get_comfyui_status()` → 返回 comfyui 状态 dict
- `_get_all_container_statuses()` → 返回所有容器状态 dict

#### S1.3 完成定义（DoD）
- [ ] `_build_status()` 中 ollama/comfyui/容器状态查询并行执行
- [ ] 并行后这部分从 3-5 秒降至 1-2 秒（实测对比）
- [ ] 某个调用超时（15s）不影响其他调用结果
- [ ] 现有测试全部通过

---

### S1.4 nvidia-smi 缓存（0.5 人天）

#### 修改文件：`vram-console/engine/` 中负责 nvidia-smi 查询的模块

> 注意：需要先定位当前 nvidia-smi 查询在哪个文件/函数中。用 Grep 搜索 `nvidia-smi` 或 `query-gpu` 找到位置。

在 nvidia-smi 查询函数外包裹一层 5 秒 TTL 缓存：

```python
import time
import threading

_nvidia_cache = {"data": None, "timestamp": 0}
_nvidia_lock = threading.Lock()
_NVIDIA_TTL = 5.0  # 秒
_NVIDIA_DANGER_TTL = 2.0  # 危险状态时更短

def get_gpu_status(force_refresh: bool = False) -> dict:
    """获取 GPU 状态，带 5 秒缓存。"""
    global _nvidia_cache
    with _nvidia_lock:
        now = time.time()
        if not force_refresh and _nvidia_cache["data"] is not None:
            danger = _nvidia_cache["data"].get("danger_level", "safe")
            ttl = _NVIDIA_DANGER_TTL if danger in ("danger", "critical") else _NVIDIA_TTL
            if now - _nvidia_cache["timestamp"] < ttl:
                return _nvidia_cache["data"]

        # 执行 nvidia-smi 查询（原有逻辑）
        data = _query_nvidia_smi()
        _nvidia_cache["data"] = data
        _nvidia_cache["timestamp"] = now
        return data
```

#### S1.4 完成定义（DoD）
- [ ] nvidia-smi 查询带 5 秒 TTL 缓存
- [ ] 危险状态时 TTL 缩短为 2 秒
- [ ] 连续调用 5 次，只有第 1 次执行 nvidia-smi，其余命中缓存
- [ ] 现有测试全部通过

---

### S1 总体验收

- [ ] `/api/status` 热路径响应 <3 秒（缓存命中 <500ms）
- [ ] 连续调用 5 次，第 2-5 次缓存命中
- [ ] 写操作后缓存失效，返回最新数据
- [ ] Docker 容器启停后 5 秒内 status 反映最新状态
- [ ] docker events 不可用时服务正常降级
- [ ] `test_status_cache.py` 全部通过
- [ ] 现有 98 个测试全部通过
- [ ] 服务稳定运行 30 分钟无崩溃（watchdog 无重启）

---

## S2：事件关联引擎（P0，6 人天）

> **目标**：告警触发时自动回溯最近 5 分钟事件流，输出根因候选 Top3
> **前置条件**：S1 完成（Docker events 可用）
> **后置条件**：`/api/events/timeline` 和 `/api/diagnose` API 可用，9 条规则测试通过

### S2.1 事件标准化 + EventBus（1.5 人天）

#### 新建文件：`vram-console/engine/event_bus.py`

```python
"""
事件总线模块 — 统一事件格式，提供事件记录、查询、时间线 API 的数据基础。

事件格式（统一）：
{
    "timestamp": "2026-09-01T12:00:00.123456",  # ISO 8601
    "category": "vram",  # 枚举：vram/container/model/task/user_action/system/guard
    "level": "info",  # 枚举：debug/info/warning/error/critical
    "source": "qos_engine",  # 产生事件的模块名
    "event": "vram_danger_critical",  # 事件类型名（蛇形命名）
    "message": "显存剩余 0.8GB，进入 critical 状态",  # 人类可读描述
    "metadata": {...}  # 附加数据（任意 dict）
}

核心类：
- EventBus: 事件记录与查询，内存环形缓冲区（最近 1000 条）+ 持久化到日志文件
"""

import json
import time
import threading
from collections import deque
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pathlib import Path


# 事件类别枚举
EVENT_CATEGORIES = {"vram", "container", "model", "task", "user_action", "system", "guard"}
# 事件级别枚举
EVENT_LEVELS = {"debug", "info", "warning", "error", "critical"}


class EventBus:
    def __init__(self, max_events: int = 1000, log_file: Optional[str] = None):
        self._events: deque = deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._log_file = Path(log_file) if log_file else None

    def record(self, category: str, level: str, source: str, event: str,
               message: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """记录一个事件。返回事件对象。"""
        if category not in EVENT_CATEGORIES:
            category = "system"  # 未知类别归为 system
        if level not in EVENT_LEVELS:
            level = "info"

        evt = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category": category,
            "level": level,
            "source": source,
            "event": event,
            "message": message,
            "metadata": metadata or {},
        }
        with self._lock:
            self._events.append(evt)
        # 持久化到日志文件（异步或同步，简单起见同步追加）
        if self._log_file:
            try:
                with open(self._log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(evt, ensure_ascii=False) + "\n")
            except Exception:
                pass
        return evt

    def query(self, start_time: Optional[str] = None, end_time: Optional[str] = None,
              category: Optional[str] = None, level: Optional[str] = None,
              source: Optional[str] = None, event: Optional[str] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        """查询事件，按时间倒序。"""
        with self._lock:
            events = list(self._events)

        # 过滤
        if start_time:
            events = [e for e in events if e["timestamp"] >= start_time]
        if end_time:
            events = [e for e in events if e["timestamp"] <= end_time]
        if category:
            events = [e for e in events if e["category"] == category]
        if level:
            events = [e for e in events if e["level"] == level]
        if source:
            events = [e for e in events if e["source"] == source]
        if event:
            events = [e for e in events if e["event"] == event]

        # 按时间倒序
        events.sort(key=lambda e: e["timestamp"], reverse=True)
        return events[:limit]

    def get_recent(self, seconds: int = 300, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取最近 N 秒的事件。"""
        cutoff = datetime.now(timezone.utc).timestamp() - seconds
        cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
        return self.query(start_time=cutoff_iso, category=category, limit=500)

    def count_by_category(self, seconds: int = 300) -> Dict[str, int]:
        """统计最近 N 秒各类别事件数量。"""
        recent = self.get_recent(seconds)
        counts = {cat: 0 for cat in EVENT_CATEGORIES}
        for e in recent:
            counts[e["category"]] = counts.get(e["category"], 0) + 1
        return counts


# 全局单例
event_bus = EventBus(
    max_events=1000,
    log_file="logs/events.jsonl"  # 事件持久化文件
)
```

#### 新建端点：`vram-console/api/endpoints/events.py`

```python
"""事件相关 API 端点。"""
from api.router import router
from api.request import Request
from api.response import Response
from engine.event_bus import event_bus


@router.get("/api/events/timeline")
def get_events_timeline(req: Request) -> Response:
    """获取事件时间线。

    Query 参数：
    - start_time: ISO 8601 起始时间（可选）
    - end_time: ISO 8601 结束时间（可选）
    - category: 事件类别过滤（可选）
    - level: 事件级别过滤（可选）
    - source: 事件来源过滤（可选）
    - event: 事件类型过滤（可选）
    - limit: 返回数量，默认 100，最大 500
    """
    start_time = req.query.get("start_time")
    end_time = req.query.get("end_time")
    category = req.query.get("category")
    level = req.query.get("level")
    source = req.query.get("source")
    event_name = req.query.get("event")
    try:
        limit = min(int(req.query.get("limit", 100)), 500)
    except ValueError:
        limit = 100

    events = event_bus.query(
        start_time=start_time, end_time=end_time,
        category=category, level=level, source=source,
        event=event_name, limit=limit
    )
    return Response.json({"ok": True, "data": {"events": events, "count": len(events)}})


@router.get("/api/events/stats")
def get_events_stats(req: Request) -> Response:
    """获取事件统计（最近 5 分钟各类别数量）。"""
    seconds = int(req.query.get("seconds", 300))
    stats = event_bus.count_by_category(seconds)
    return Response.json({"ok": True, "data": {"stats": stats, "window_seconds": seconds}})
```

在 `api/endpoints/__init__.py` 中添加 `from . import events`。

#### S2.1 完成定义（DoD）
- [ ] `engine/event_bus.py` 存在，`EventBus` 类实现上述所有方法
- [ ] `api/endpoints/events.py` 存在，`/api/events/timeline` 和 `/api/events/stats` 注册
- [ ] 事件持久化到 `logs/events.jsonl`
- [ ] `GET /api/events/timeline` 返回统一格式事件，支持所有过滤参数
- [ ] 内存环形缓冲区最多 1000 条，超出自动淘汰最旧的

---

### S2.2 显存状态变化事件（0.5 人天）

#### 修改文件：`vram-console/engine/qos.py`（或负责 QoS 状态机的模块）

> 先定位 QoS 状态机在哪个文件。用 Grep 搜索 `GREEN`、`YELLOW`、`RED` 或 `danger_level` 找到位置。

在状态跃迁时记录事件：

```python
from engine.event_bus import event_bus

def _transition_state(old_state: str, new_state: str, vram_free_mb: int, reason: str):
    """状态跃迁时记录事件。"""
    if old_state == new_state:
        return
    level = "warning" if new_state in ("warning", "danger") else "critical" if new_state == "critical" else "info"
    event_bus.record(
        category="vram",
        level=level,
        source="qos_engine",
        event=f"vram_state_{old_state}_to_{new_state}",
        message=f"显存状态从 {old_state} 变为 {new_state}（空闲 {vram_free_mb}MB），原因：{reason}",
        metadata={"old_state": old_state, "new_state": new_state, "vram_free_mb": vram_free_mb, "reason": reason}
    )
    # ... 原有状态跃迁逻辑 ...
```

需要记录的状态跃迁：
- safe → warning / danger / critical
- warning → safe / danger / critical
- danger → safe / warning / critical
- critical → safe / warning / danger

#### S2.2 完成定义（DoD）
- [ ] QoS 状态每次跃迁都记录事件到 event_bus
- [ ] 事件含 old_state/new_state/vram_free_mb/reason
- [ ] 手动触发状态变化（如加载大模型），`/api/events/timeline` 能查到对应事件

---

### S2.3 用户操作事件审计（1 人天）

#### 任务：检查所有写操作端点，确保都有 event_bus.record 调用

需要检查并补充事件记录的端点：

| 端点 | 事件 category | 事件名 | 关键字段 |
|------|-------------|--------|---------|
| `POST /api/free` | user_action | vram_free_executed | level(L1/L2/L3), freed_mb |
| `POST /api/scene` | user_action | scene_switched | from_scene, to_scene, success |
| `POST /api/combo` | user_action | combo_switched | combo_name, success |
| `POST /api/guard` (kick) | guard | process_kicked | pid, process_name, reason |
| `POST /api/guard` (evict) | guard | process_evicted | pid, process_name, level |
| `POST /api/model` (load) | model | model_loaded | model_name, container, vram_estimate |
| `POST /api/model` (unload) | model | model_unloaded | model_name, container |
| `POST /api/queue` | task | task_submitted | model, workflow, priority |
| `POST /api/queue/cancel` | task | task_canceled | task_id, reason |
| `POST /api/service` | user_action | service_action | service, action, success |
| `POST /api/container/stop` | container | container_stopped | container_name, reason |
| `POST /api/admission` | system | admission_checked | model, decision, reason |

每个端点在操作成功后添加：
```python
from engine.event_bus import event_bus

event_bus.record(
    category="user_action",
    level="info",
    source="api_endpoint",
    event="vram_free_executed",
    message=f"显存释放执行（L{level}），释放约 {freed_mb}MB",
    metadata={"level": level, "freed_mb": freed_mb, "user": req.user or "api_token"}
)
```

#### S2.3 完成定义（DoD）
- [ ] 上表 13 个写操作端点全部有 event_bus.record 调用
- [ ] 事件格式统一，含必要的 metadata
- [ ] 执行一个写操作（如 `/api/free`），`/api/events/timeline` 能查到对应事件

---

### S2.4 Docker events 接入 EventBus（0.5 人天）

#### 修改文件：`vram-console/core/docker_events.py`

在 `_handle_event` 方法中，把容器状态变化也记录到 event_bus：

```python
from engine.event_bus import event_bus

def _handle_event(self, event: dict) -> None:
    # ... 原有状态更新逻辑 ...

    # 记录到 event_bus
    if action in ("start", "stop", "die", "restart", "destroy"):
        level = "warning" if action in ("die", "destroy") else "info"
        event_bus.record(
            category="container",
            level=level,
            source="docker_events",
            event=f"container_{action}",
            message=f"容器 {container_name} {action}",
            metadata={"container": container_name, "action": action, "docker_event": event}
        )
```

#### S2.4 完成定义（DoD）
- [ ] Docker 容器 start/stop/die/restart/destroy 事件都记录到 event_bus
- [ ] 启停一个容器，`/api/events/timeline` 能查到 container 类别事件

---

### S2.5 根因推断规则引擎（2 人天）

#### 新建文件：`vram-console/engine/diagnose.py`

```python
"""
根因推断规则引擎 — 基于 if-then 规则的故障根因分析（非 ML，保证可解释性）。

核心概念：
- Rule: 一条诊断规则，含 condition（事件模式匹配）、root_cause、confidence、suggested_action
- DiagnosisResult: 诊断结果，含匹配的规则列表（按置信度排序）+ 关联事件

规则匹配算法：
1. 拉取时间窗内所有事件（默认最近 300 秒）
2. 逐条规则检查 condition（事件模式 + 当前状态）
3. 匹配的规则按 confidence 降序排序
4. 返回 Top3 + 每条规则的关联事件
"""

import re
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from engine.event_bus import event_bus


@dataclass
class Rule:
    """诊断规则。"""
    id: str  # 规则 ID，如 RC-001
    name: str  # 规则名称
    description: str  # 规则描述
    condition: Callable[[List[Dict], Dict], bool]  # 匹配函数：(事件列表, 当前状态) -> bool
    root_cause: str  # 根因描述
    confidence: int  # 置信度 0-100
    suggested_action: str  # 处置建议
    related_events_query: Dict[str, Any]  # 关联事件查询条件


@dataclass
class DiagnosisResult:
    """诊断结果。"""
    alert_type: str
    alert_time: str
    window_seconds: int
    matched_rules: List[Dict] = field(default_factory=list)  # 匹配的规则（含关联事件）
    total_events: int = 0
    default_diagnosis: Optional[str] = None


class RuleEngine:
    """规则引擎。"""

    def __init__(self):
        self._rules: List[Rule] = []

    def register(self, rule: Rule) -> None:
        """注册一条规则。"""
        self._rules.append(rule)

    def get_all_rules(self) -> List[Dict]:
        """获取所有规则的元信息。"""
        return [
            {"id": r.id, "name": r.name, "description": r.description,
             "root_cause": r.root_cause, "confidence": r.confidence,
             "suggested_action": r.suggested_action}
            for r in self._rules
        ]

    def diagnose(self, alert_type: str, alert_time: Optional[str] = None,
                 window_seconds: int = 300, current_status: Optional[Dict] = None) -> DiagnosisResult:
        """
        执行诊断。

        Args:
            alert_type: 告警类型，如 "vram_critical"
            alert_time: 告警时间（ISO 8601），默认当前时间
            window_seconds: 回溯时间窗，默认 300 秒
            current_status: 当前系统状态（/api/status 的数据），用于 condition 中的状态检查
        """
        # 拉取时间窗内事件
        events = event_bus.get_recent(seconds=window_seconds)
        current_status = current_status or {}

        result = DiagnosisResult(
            alert_type=alert_type,
            alert_time=alert_time or "",
            window_seconds=window_seconds,
            total_events=len(events)
        )

        # 逐条规则匹配
        matched = []
        for rule in self._rules:
            try:
                if rule.condition(events, current_status):
                    # 拉取关联事件
                    related = event_bus.query(
                        category=rule.related_events_query.get("category"),
                        event=rule.related_events_query.get("event"),
                        limit=20
                    )
                    matched.append({
                        "rule_id": rule.id,
                        "rule_name": rule.name,
                        "root_cause": rule.root_cause,
                        "confidence": rule.confidence,
                        "suggested_action": rule.suggested_action,
                        "related_events": related,
                        "related_events_count": len(related)
                    })
            except Exception:
                continue  # 规则执行失败不影响其他规则

        # 按置信度降序排序，取 Top3
        matched.sort(key=lambda x: x["confidence"], reverse=True)
        result.matched_rules = matched[:3]

        if not result.matched_rules:
            result.default_diagnosis = "未识别到明确根因，建议检查事件时间线。最近 10 条事件已附带。"
            result.matched_rules = [{
                "rule_id": "DEFAULT",
                "rule_name": "默认诊断",
                "root_cause": result.default_diagnosis,
                "confidence": 0,
                "suggested_action": "查看事件时间线，手动排查",
                "related_events": events[:10],
                "related_events_count": min(len(events), 10)
            }]

        return result


# ========== 规则定义 ==========

def _has_event(events: List[Dict], event_pattern: str, category: Optional[str] = None) -> bool:
    """检查事件列表中是否存在匹配的事件。event_pattern 支持正则。"""
    for e in events:
        if category and e["category"] != category:
            continue
        if re.search(event_pattern, e["event"]):
            return True
    return False


def _is_container_running(status: Dict, container_name: str) -> bool:
    """检查容器是否在运行。"""
    services = status.get("data", {}).get("services", {})
    return services.get(container_name, {}).get("ok", False)


def _get_vram_free_mb(status: Dict) -> int:
    """获取当前空闲显存。"""
    return status.get("data", {}).get("vram_ledger", {}).get("free_mb", 99999)


def _get_loaded_models(status: Dict, container: str) -> List[str]:
    """获取容器中加载的模型列表。"""
    if container == "ollama":
        return status.get("data", {}).get("ollama", {}).get("loaded_models", [])
    return []


# RC-001: ComfyUI 生成任务显存溢出
def rc001_condition(events: List[Dict], status: Dict) -> bool:
    return (
        _has_event(events, r"task_submit|comfyui_task", "task")
        and _is_container_running(status, "comfyui")
        and _get_vram_free_mb(status) < 1024
    )

# RC-002: 大模型加载导致显存不足
def rc002_condition(events: List[Dict], status: Dict) -> bool:
    loaded = _get_loaded_models(status, "ollama")
    has_large = any(any(s in m.lower() for s in ["7b", "9b", "14b", "27b", "32b"]) for m in loaded)
    return (
        _has_event(events, r"model_loaded", "model")
        and has_large
        and _get_vram_free_mb(status) < 2048
    )

# RC-003: Fooocus 场景切换后显存未释放
def rc003_condition(events: List[Dict], status: Dict) -> bool:
    return (
        _has_event(events, r"scene_switched|combo_switched", "user_action")
        and _is_container_running(status, "fooocus")
        and _get_vram_free_mb(status) < 2048
    )

# RC-004: 多服务并发占用累积
def rc004_condition(events: List[Dict], status: Dict) -> bool:
    services = status.get("data", {}).get("services", {})
    running_count = sum(1 for s in services.values() if s.get("ok"))
    return (
        running_count >= 3
        and not _has_event(events, r"task_submit|model_loaded", "task")
        and _get_vram_free_mb(status) < 4096
    )

# RC-005: 桌面应用占用显存
def rc005_condition(events: List[Dict], status: Dict) -> bool:
    desktop_vram = status.get("data", {}).get("desktop_vram", {}).get("total_mb", 0)
    return (
        desktop_vram > 2048
        and not _has_event(events, r"task_submit|model_loaded|scene_switched", "task")
        and _get_vram_free_mb(status) < 2048
    )


# 全局规则引擎实例
rule_engine = RuleEngine()

# 注册初始 5 条规则
rule_engine.register(Rule(
    id="RC-001",
    name="ComfyUI 生成任务显存溢出",
    description="ComfyUI 正在运行且最近有任务提交，显存进入危险状态",
    condition=rc001_condition,
    root_cause="ComfyUI 生成任务显存溢出，高分辨率或大批量生成导致显存占用超出预期",
    confidence=85,
    suggested_action="暂停 ComfyUI 队列任务；降低生成分辨率或批量大小；执行 /api/free 释放 ComfyUI 显存",
    related_events_query={"category": "task", "event": "task_submit"}
))

rule_engine.register(Rule(
    id="RC-002",
    name="大模型加载导致显存不足",
    description="Ollama 加载了 >7B 模型且最近有模型加载事件",
    condition=rc002_condition,
    root_cause="大参数模型（>7B）加载占用大量显存，与其他服务并发导致显存不足",
    confidence=80,
    suggested_action="卸载大模型（ollama rm 或 /api/model unload）；切换到小模型（如 qwen3:0.6b）；降低 context 长度",
    related_events_query={"category": "model", "event": "model_loaded"}
))

rule_engine.register(Rule(
    id="RC-003",
    name="Fooocus 场景切换后显存未释放",
    description="Fooocus 正在运行且最近有场景切换，显存未正常释放",
    condition=rc003_condition,
    root_cause="Fooocus 容器在场景切换后显存未正常释放，模型权重残留在显存中",
    confidence=70,
    suggested_action="重启 Fooocus 容器（docker restart fooocus）；切换到不含 Fooocus 的场景；执行 /api/free L2 释放",
    related_events_query={"category": "user_action", "event": "scene_switched"}
))

rule_engine.register(Rule(
    id="RC-004",
    name="多服务并发占用累积",
    description="多个容器同时运行且无新任务，显存被并发服务累积占用",
    condition=rc004_condition,
    root_cause="多个 AI 服务（Ollama/ComfyUI/Fooocus/OWUI）同时运行，显存被累积占用，无单一明显元凶",
    confidence=60,
    suggested_action="停止非必要服务（如 OWUI/Immich）；切换到独占场景（只运行一个 AI 服务）；执行 /api/free 释放空闲模型",
    related_events_query={"category": "container", "event": "container_start"}
))

rule_engine.register(Rule(
    id="RC-005",
    name="桌面应用占用显存",
    description="桌面进程显存 >2GB 且最近无容器操作，显存被桌面 GPU 应用占用",
    condition=rc005_condition,
    root_cause="桌面 GPU 应用（游戏、浏览器硬件加速、视频编辑等）占用大量显存，与 AI 服务竞争显存资源",
    confidence=75,
    suggested_action="关闭桌面 GPU 应用（游戏、浏览器等）；检查是否误开游戏；在 /api/desktop_vram 中查看具体进程并结束",
    related_events_query={"category": "system", "event": "desktop_"}
))
```

#### 新建端点：`vram-console/api/endpoints/diagnose.py`

```python
"""诊断相关 API 端点。"""
from api.router import router
from api.request import Request
from api.response import Response
from engine.diagnose import rule_engine


@router.post("/api/diagnose")
def post_diagnose(req: Request) -> Response:
    """执行根因诊断。

    Body 参数：
    - alert_type: 告警类型，如 "vram_critical"（必填）
    - alert_time: 告警时间 ISO 8601（可选，默认当前）
    - window_seconds: 回溯时间窗，默认 300
    - current_status: 当前系统状态（可选，不传则后端自行获取）
    """
    body = req.body or {}
    alert_type = body.get("alert_type")
    if not alert_type:
        return Response.json({"ok": False, "error": "alert_type is required"}, status=400)

    alert_time = body.get("alert_time")
    window_seconds = int(body.get("window_seconds", 300))
    current_status = body.get("current_status")  # 可选

    result = rule_engine.diagnose(
        alert_type=alert_type,
        alert_time=alert_time,
        window_seconds=window_seconds,
        current_status=current_status
    )

    return Response.json({
        "ok": True,
        "data": {
            "alert_type": result.alert_type,
            "window_seconds": result.window_seconds,
            "total_events": result.total_events,
            "root_causes": result.matched_rules,  # Top3
            "count": len(result.matched_rules)
        }
    })


@router.get("/api/diagnose/rules")
def get_diagnose_rules(req: Request) -> Response:
    """获取所有诊断规则的元信息。"""
    rules = rule_engine.get_all_rules()
    return Response.json({"ok": True, "data": {"rules": rules, "count": len(rules)}})
```

在 `api/endpoints/__init__.py` 中添加 `from . import diagnose`。

#### 新建测试：`vram-console/tests/test_diagnose.py`

```python
import unittest
import sys
sys.path.insert(0, ".")
from engine.diagnose import rule_engine, Rule, DiagnosisResult
from engine.event_bus import event_bus


class TestRuleEngine(unittest.TestCase):
    def setUp(self):
        # 清空事件
        event_bus._events.clear()

    def _make_event(self, category, event_name, message="test", metadata=None):
        return event_bus.record(category, "info", "test", event_name, message, metadata or {})

    def test_rc001_comfyui_task(self):
        # 构造事件：task_submit
        self._make_event("task", "task_submit", "ComfyUI task submitted")
        # 构造状态：comfyui running + vram low
        status = {"data": {"services": {"comfyui": {"ok": True}}, "vram_ledger": {"free_mb": 500}}}
        result = rule_engine.diagnose("vram_critical", current_status=status)
        rule_ids = [r["rule_id"] for r in result.matched_rules]
        self.assertIn("RC-001", rule_ids)

    def test_rc001_negative_no_task(self):
        # 无 task 事件，不应匹配 RC-001
        status = {"data": {"services": {"comfyui": {"ok": True}}, "vram_ledger": {"free_mb": 500}}}
        result = rule_engine.diagnose("vram_critical", current_status=status)
        rule_ids = [r["rule_id"] for r in result.matched_rules]
        self.assertNotIn("RC-001", rule_ids)

    def test_rc002_large_model(self):
        self._make_event("model", "model_loaded", "qwen3.5:9b loaded")
        status = {"data": {
            "ollama": {"loaded_models": ["qwen3.5:9b"]},
            "vram_ledger": {"free_mb": 1000}
        }}
        result = rule_engine.diagnose("vram_critical", current_status=status)
        rule_ids = [r["rule_id"] for r in result.matched_rules]
        self.assertIn("RC-002", rule_ids)

    def test_rc005_desktop_vram(self):
        status = {"data": {
            "desktop_vram": {"total_mb": 3000},
            "vram_ledger": {"free_mb": 1000}
        }}
        result = rule_engine.diagnose("vram_critical", current_status=status)
        rule_ids = [r["rule_id"] for r in result.matched_rules]
        self.assertIn("RC-005", rule_ids)

    def test_default_diagnosis_when_no_match(self):
        status = {"data": {"vram_ledger": {"free_mb": 100}, "services": {}}}
        result = rule_engine.diagnose("vram_critical", current_status=status)
        self.assertEqual(result.matched_rules[0]["rule_id"], "DEFAULT")

    def test_top3_only(self):
        # 构造多个匹配，验证只返回 Top3
        for i in range(10):
            self._make_event("task", f"task_submit_{i}")
            self._make_event("model", f"model_loaded_{i}")
        status = {"data": {
            "services": {"comfyui": {"ok": True}, "fooocus": {"ok": True}},
            "ollama": {"loaded_models": ["qwen3.5:9b"]},
            "desktop_vram": {"total_mb": 3000},
            "vram_ledger": {"free_mb": 500}
        }}
        result = rule_engine.diagnose("vram_critical", current_status=status)
        self.assertLessEqual(len(result.matched_rules), 3)
        # 按置信度降序
        confidences = [r["confidence"] for r in result.matched_rules]
        self.assertEqual(confidences, sorted(confidences, reverse=True))

    def test_get_all_rules(self):
        rules = rule_engine.get_all_rules()
        self.assertGreaterEqual(len(rules), 5)
        for r in rules:
            self.assertIn("id", r)
            self.assertIn("root_cause", r)
            self.assertIn("confidence", r)


if __name__ == "__main__":
    unittest.main()
```

#### S2.5 完成定义（DoD）
- [ ] `engine/diagnose.py` 存在，`RuleEngine` 类 + 5 条初始规则实现
- [ ] `api/endpoints/diagnose.py` 存在，`/api/diagnose` 和 `/api/diagnose/rules` 注册
- [ ] `test_diagnose.py` 8 个测试全部通过
- [ ] `POST /api/diagnose {"alert_type": "vram_critical"}` 返回 Top3 根因候选
- [ ] 每条结果含 root_cause/confidence/suggested_action/related_events
- [ ] 无匹配时返回 DEFAULT 诊断 + 最近 10 条事件

---

### S2 总体验收

- [ ] `/api/events/timeline` 返回统一格式事件，支持过滤
- [ ] `/api/diagnose` 返回 Top3 根因候选，含关联事件和处置建议
- [ ] QoS 状态跃迁、用户写操作、Docker 容器变化都记录事件
- [ ] `test_diagnose.py` 全部通过
- [ ] `test_event_bus.py`（如新建）全部通过
- [ ] 现有测试全部通过
- [ ] 模拟显存 critical 状态，诊断返回合理的根因候选

---

## S3：故障场景库 + 告警降噪（P1，5 人天）

> **前置条件**：S2 完成（event_bus + rule_engine 可用）
> **后置条件**：5 个故障场景文档 + 5 个注入脚本 + AlertManager + 4 条新规则

### S3.1 故障场景库文档（1 人天）

#### 新建文件：`vram-console/docs/故障场景库.md`

文档结构（每个场景含以下 6 个部分）：

```markdown
# 故障场景库

## FC-001：显存耗尽/OOM 风险

### 触发条件
- free_vram < 1GB 持续 10 秒
- 检测频率：每 5 秒检查一次

### 告警模板
- 级别：critical
- 标题：显存耗尽风险
- 内容：显存剩余 {free_mb}MB，已持续 {duration}秒，存在 OOM 死机风险
- 对应根因规则：RC-001/002/003/005

### 处置步骤（可执行）
1. 预览释放：`gmae vram free --dry-run`（查看将释放什么）
2. 一键释放：`POST /api/free {"level": "L1"}`（释放未使用模型）
3. 如仍 critical：暂停队列：`POST /api/queue/pause`
4. 如仍 critical：停止非必要容器：`POST /api/scene {"scene": "idle"}`
5. 验证：`GET /api/status` 确认 free_vram > 4GB

### 验证方法
- 处置后 10 秒内 free_vram > 4GB
- 告警自动消除（/api/alerts 中该告警消失）
- 无 OOM 崩溃

### 预防建议
- 避免同时加载多个大模型
- 生成高分辨率内容前先检查显存
- 启用自动防死机（/api/auto-protect/config，默认关闭）
```

5 个场景按此格式编写：FC-001 显存耗尽、FC-002 容器异常退出、FC-003 推理延迟升高、FC-004 任务队列堆积、FC-005 服务不可达。

#### S3.1 完成定义（DoD）
- [ ] `docs/故障场景库.md` 存在，5 个场景全部定义
- [ ] 每个场景含触发条件/告警模板/处置步骤/验证方法/预防建议
- [ ] 处置步骤是具体的 API 调用或 CLI 命令，不是文字描述

---

### S3.2 根因规则扩展（0.5 人天）

#### 修改文件：`vram-console/engine/diagnose.py`

新增 4 条规则（RC-006 ~ RC-009），对应 FC-002 ~ FC-005：

| 规则 ID | 名称 | 触发条件 | 置信度 | 处置建议 |
|---------|------|---------|-------|---------|
| RC-006 | 容器异常退出/频繁重启 | 5 分钟内 container_die 事件 ≥3 次 | 75 | 检查容器日志（docker logs）；重启容器；检查是否 OOM killed |
| RC-007 | 推理延迟升高 | 最近 3 次推理响应时间 > 阈值（LLM >30s/图 >120s） | 65 | 降低模型参数或 context；检查显存是否不足；切换到小模型 |
| RC-008 | 任务队列堆积 | ComfyUI 队列 pending >5 持续 30 秒 | 55 | 暂停新任务提交；取消低优先级任务；检查 worker 是否卡住 |
| RC-009 | 服务不可达 | health check 连续 3 次失败 | 80 | 重启服务容器；检查端口是否被占用；查看服务日志 |

每条规则的 condition 函数参考 S2.5 的格式编写。注意 RC-007 需要推理响应时间数据，如果当前没有采集，condition 简化为"显存不足 + 有推理任务"。

在文件末尾注册这 4 条规则到 `rule_engine`。

#### S3.2 完成定义（DoD）
- [ ] `diagnose.py` 中新增 RC-006~009 共 4 条规则
- [ ] `rule_engine.get_all_rules()` 返回 9 条规则
- [ ] 每条新规则有对应的单元测试（正例 + 反例）

---

### S3.3 告警管理器（2 人天）

#### 新建文件：`vram-console/engine/alert_manager.py`

```python
"""
告警管理器 — 告警聚合、静默、升级、历史记录。

核心数据结构：
- active_alerts: {alert_type: {level, message, metadata, first_triggered, last_triggered, count}}
- silenced_alerts: {alert_type: silence_until_timestamp}
- alert_history: deque(maxlen=100)，最近 100 条告警历史

核心功能：
- submit(alert_type, level, message, metadata): 提交告警，自动聚合/静默检查
- silence(alert_type, duration_minutes): 静默某类告警
- get_active(): 获取活跃告警列表
- get_history(): 获取告警历史
- 升级机制：持续未解决的告警自动升级 level（info→warning→danger→critical）
"""

import threading
import time
import json
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pathlib import Path


# 告警级别（数值越大越严重）
ALERT_LEVELS = {"info": 1, "warning": 2, "danger": 3, "critical": 4}
# 升级阈值（秒）：持续超过此时间未解决则升级
ALERT_ESCALATION_THRESHOLD = 600  # 10 分钟
# 最高级别
MAX_ALERT_LEVEL = "critical"


class AlertManager:
    def __init__(self, history_limit: int = 100, silence_file: Optional[str] = None):
        self._active: Dict[str, Dict] = {}
        self._silenced: Dict[str, float] = {}  # alert_type -> silence_until (epoch)
        self._history: deque = deque(maxlen=history_limit)
        self._lock = threading.Lock()
        self._silence_file = Path(silence_file) if silence_file else None
        self._load_silenced()

    def submit(self, alert_type: str, level: str, message: str,
               metadata: Optional[Dict] = None) -> Dict:
        """
        提交告警。

        Returns:
            告警对象。如果被静默，返回 {"silenced": True}。
            如果被聚合，返回更新后的告警对象（count+1）。
        """
        now = time.time()

        with self._lock:
            # 检查静默
            if alert_type in self._silenced:
                if now < self._silenced[alert_type]:
                    return {"silenced": True, "alert_type": alert_type}
                else:
                    del self._silenced[alert_type]  # 静默过期

            # 检查聚合
            if alert_type in self._active:
                alert = self._active[alert_type]
                alert["count"] += 1
                alert["last_triggered"] = now
                alert["message"] = message  # 更新为最新消息
                alert["metadata"] = metadata or {}
                # 如果新告警级别更高，升级
                if ALERT_LEVELS.get(level, 0) > ALERT_LEVELS.get(alert["level"], 0):
                    alert["level"] = level
                self._record_history(alert, "aggregated")
                return dict(alert)

            # 新建告警
            alert = {
                "alert_type": alert_type,
                "level": level,
                "message": message,
                "metadata": metadata or {},
                "first_triggered": now,
                "last_triggered": now,
                "count": 1,
                "status": "active"
            }
            self._active[alert_type] = alert
            self._record_history(alert, "new")
            return dict(alert)

    def resolve(self, alert_type: str) -> bool:
        """解决（移除）一个活跃告警。"""
        with self._lock:
            if alert_type in self._active:
                alert = self._active.pop(alert_type)
                self._record_history(alert, "resolved")
                return True
            return False

    def silence(self, alert_type: str, duration_minutes: int = 30) -> Dict:
        """静默某类告警。"""
        until = time.time() + duration_minutes * 60
        with self._lock:
            self._silenced[alert_type] = until
            # 静默时也从活跃中移除
            if alert_type in self._active:
                alert = self._active.pop(alert_type)
                self._record_history(alert, "silenced")
        self._save_silenced()
        return {"alert_type": alert_type, "silenced_until": until, "duration_minutes": duration_minutes}

    def check_escalation(self) -> List[Dict]:
        """
        检查并执行告警升级（应定期调用，如每 60 秒）。
        返回本次升级的告警列表。
        """
        now = time.time()
        escalated = []
        with self._lock:
            for alert_type, alert in list(self._active.items()):
                duration = now - alert["first_triggered"]
                if duration > ALERT_ESCALATION_THRESHOLD:
                    current_level_num = ALERT_LEVELS.get(alert["level"], 1)
                    if current_level_num < ALERT_LEVELS[MAX_ALERT_LEVEL]:
                        # 升级一级
                        new_level_num = current_level_num + 1
                        for name, num in ALERT_LEVELS.items():
                            if num == new_level_num:
                                alert["level"] = name
                                alert["escalated"] = True
                                alert["last_escalated"] = now
                                escalated.append(dict(alert))
                                self._record_history(alert, "escalated")
                                break
                    # 重置 first_triggered，避免每 10 分钟反复升级
                    alert["first_triggered"] = now
        return escalated

    def get_active(self) -> List[Dict]:
        """获取所有活跃告警。"""
        with self._lock:
            now = time.time()
            result = []
            for alert in self._active.values():
                alert_copy = dict(alert)
                alert_copy["duration_seconds"] = int(now - alert["first_triggered"])
                result.append(alert_copy)
            return result

    def get_history(self, limit: int = 50) -> List[Dict]:
        """获取告警历史。"""
        with self._lock:
            return list(self._history)[-limit:]

    def get_silenced(self) -> List[Dict]:
        """获取静默中的告警。"""
        now = time.time()
        with self._lock:
            result = []
            for alert_type, until in self._silenced.items():
                if now < until:
                    result.append({
                        "alert_type": alert_type,
                        "silenced_until": until,
                        "remaining_seconds": int(until - now)
                    })
            return result

    def _record_history(self, alert: Dict, action: str) -> None:
        """记录告警历史（调用方需持有锁）。"""
        self._history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,  # new/aggregated/resolved/silenced/escalated
            "alert_type": alert["alert_type"],
            "level": alert["level"],
            "message": alert["message"],
            "count": alert.get("count", 1)
        })

    def _load_silenced(self) -> None:
        """从文件加载静默配置。"""
        if self._silence_file and self._silence_file.exists():
            try:
                with open(self._silence_file, "r", encoding="utf-8") as f:
                    self._silenced = json.load(f)
            except Exception:
                self._silenced = {}

    def _save_silenced(self) -> None:
        """保存静默配置到文件。"""
        if self._silence_file:
            try:
                with open(self._silence_file, "w", encoding="utf-8") as f:
                    json.dump(self._silenced, f)
            except Exception:
                pass


# 全局单例
alert_manager = AlertManager(
    history_limit=100,
    silence_file="data/alerts_silenced.json"  # 静默持久化文件
)
```

#### 新建端点：`vram-console/api/endpoints/alerts.py`

```python
"""告警相关 API 端点。"""
from api.router import router
from api.request import Request
from api.response import Response
from engine.alert_manager import alert_manager


@router.get("/api/alerts")
def get_alerts(req: Request) -> Response:
    """获取活跃告警列表。"""
    alerts = alert_manager.get_active()
    return Response.json({"ok": True, "data": {"alerts": alerts, "count": len(alerts)}})


@router.get("/api/alerts/history")
def get_alerts_history(req: Request) -> Response:
    """获取告警历史。"""
    try:
        limit = min(int(req.query.get("limit", 50)), 100)
    except ValueError:
        limit = 50
    history = alert_manager.get_history(limit=limit)
    return Response.json({"ok": True, "data": {"history": history, "count": len(history)}})


@router.post("/api/alerts/{alert_type}/silence")
def post_alert_silence(req: Request, alert_type: str) -> Response:
    """静默某类告警。

    Body 参数：
    - duration_minutes: 静默时长（分钟），默认 30
    """
    body = req.body or {}
    try:
        duration = int(body.get("duration_minutes", 30))
    except ValueError:
        duration = 30
    result = alert_manager.silence(alert_type, duration_minutes=duration)
    return Response.json({"ok": True, "data": result})


@router.post("/api/alerts/{alert_type}/resolve")
def post_alert_resolve(req: Request, alert_type: str) -> Response:
    """手动解决（移除）一个活跃告警。"""
    success = alert_manager.resolve(alert_type)
    return Response.json({"ok": success, "data": {"alert_type": alert_type, "resolved": success}})


@router.get("/api/alerts/silenced")
def get_silenced_alerts(req: Request) -> Response:
    """获取静默中的告警。"""
    silenced = alert_manager.get_silenced()
    return Response.json({"ok": True, "data": {"silenced": silenced, "count": len(silenced)}})
```

> 注意：`@router.post("/api/alerts/{alert_type}/silence")` 这种路径参数语法需要确认 `api/router.py` 是否支持。如果不支持，改为 query 参数或 body 参数传递 alert_type。

在 `api/endpoints/__init__.py` 中添加 `from . import alerts`。

#### 集成：告警升级检查定时任务

在 server.py 中启动一个后台线程，每 60 秒调用 `alert_manager.check_escalation()`：

```python
import threading
import time
from engine.alert_manager import alert_manager

def _escalation_worker():
    while True:
        try:
            alert_manager.check_escalation()
        except Exception:
            pass
        time.sleep(60)

# 在 server 启动时
threading.Thread(target=_escalation_worker, daemon=True).start()
```

#### 集成：显存危险告警提交

在 QoS 状态机进入 danger/critical 时，调用 `alert_manager.submit()`：

```python
from engine.alert_manager import alert_manager

# 在状态跃迁到 danger/critical 时
if new_state in ("danger", "critical"):
    alert_manager.submit(
        alert_type=f"vram_{new_state}",
        level=new_state,
        message=f"显存剩余 {vram_free_mb}MB，进入 {new_state} 状态",
        metadata={"vram_free_mb": vram_free_mb, "danger_level": new_state}
    )
# 状态恢复到 safe 时
if new_state == "safe" and old_state in ("danger", "critical"):
    alert_manager.resolve(f"vram_{old_state}")
```

#### 新建测试：`vram-console/tests/test_alert_manager.py`

```python
import unittest
import time
import sys
sys.path.insert(0, ".")
from engine.alert_manager import AlertManager


class TestAlertManager(unittest.TestCase):
    def setUp(self):
        self.am = AlertManager(history_limit=50, silence_file=None)

    def test_submit_new_alert(self):
        alert = self.am.submit("vram_critical", "critical", "test")
        self.assertEqual(alert["alert_type"], "vram_critical")
        self.assertEqual(alert["count"], 1)

    def test_aggregation(self):
        self.am.submit("vram_critical", "critical", "first")
        alert = self.am.submit("vram_critical", "critical", "second")
        self.assertEqual(alert["count"], 2)
        self.assertEqual(alert["message"], "second")
        self.assertEqual(len(self.am.get_active()), 1)

    def test_silence(self):
        self.am.submit("vram_critical", "critical", "test")
        self.am.silence("vram_critical", duration_minutes=30)
        # 静默后提交应返回 silenced
        result = self.am.submit("vram_critical", "critical", "test2")
        self.assertTrue(result["silenced"])
        self.assertEqual(len(self.am.get_active()), 0)

    def test_resolve(self):
        self.am.submit("vram_critical", "critical", "test")
        self.assertTrue(self.am.resolve("vram_critical"))
        self.assertEqual(len(self.am.get_active()), 0)

    def test_escalation(self):
        # 提交一个 info 告警，手动修改 first_triggered 为 11 分钟前
        alert = self.am.submit("test_alert", "info", "test")
        with self.am._lock:
            self.am._active["test_alert"]["first_triggered"] = time.time() - 660
        escalated = self.am.check_escalation()
        self.assertEqual(len(escalated), 1)
        self.assertEqual(escalated[0]["level"], "warning")

    def test_history(self):
        self.am.submit("vram_critical", "critical", "test")
        self.am.resolve("vram_critical")
        history = self.am.get_history()
        actions = [h["action"] for h in history]
        self.assertIn("new", actions)
        self.assertIn("resolved", actions)

    def test_level_upgrade_on_submit(self):
        self.am.submit("vram_critical", "warning", "low")
        alert = self.am.submit("vram_critical", "critical", "high")
        self.assertEqual(alert["level"], "critical")


if __name__ == "__main__":
    unittest.main()
```

#### S3.3 完成定义（DoD）
- [ ] `engine/alert_manager.py` 存在，AlertManager 实现上述所有方法
- [ ] `api/endpoints/alerts.py` 存在，5 个 API 注册
- [ ] server 启动升级检查后台线程（每 60 秒）
- [ ] QoS 状态进入 danger/critical 时提交告警，恢复 safe 时 resolve
- [ ] `test_alert_manager.py` 8 个测试全部通过
- [ ] 连续触发同类型告警 3 次，`/api/alerts` 返回 1 条 count=3
- [ ] 静默后同类型告警不再推送
- [ ] 持续 10 分钟未解决的告警自动升级

---

### S3.4 故障注入演示脚本（1 人天）

#### 新建目录：`vram-console/scripts/fault_injection/`

每个脚本的统一结构：

```python
#!/usr/bin/env python3
"""
故障注入脚本：FC-001 显存耗尽
仅用于演示和测试，请勿在生产环境执行。

用法：
  python inject_vram_pressure.py --dry-run    # 预览将执行什么
  python inject_vram_pressure.py --execute     # 真实执行
  python inject_vram_pressure.py --recover     # 执行恢复操作
"""

import argparse
import sys
import time
import json
import urllib.request

SERVER = "http://127.0.0.1:8787"
TOKEN_FILE = ".api_token"


def get_token():
    try:
        with open(TOKEN_FILE, "r") as f:
            return f.read().strip()
    except Exception:
        return None


def api_call(method, path, body=None):
    url = f"{SERVER}{path}"
    headers = {"Content-Type": "application/json"}
    token = get_token()
    if token:
        headers["X-API-Key"] = token
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_vram():
    """检查当前显存，空闲 <4GB 时拒绝高显存压力注入。"""
    result = api_call("GET", "/api/status")
    if not result.get("ok"):
        return None
    free_mb = result.get("data", {}).get("vram_ledger", {}).get("free_mb", 0)
    return free_mb


def dry_run():
    print("=== DRY RUN：FC-001 显存耗尽注入 ===")
    print("将执行以下操作：")
    print("1. 检查当前显存状态")
    print("2. 加载大模型（qwen3.5:9b）")
    print("3. 提交高分辨率 ComfyUI 生成任务")
    print("4. 等待 30 秒，观察显存变化")
    print("预期：显存进入 critical 状态，触发告警")
    print()
    print("恢复操作：")
    print("1. 卸载大模型")
    print("2. 取消 ComfyUI 队列任务")
    print("3. 执行 /api/free 释放显存")


def execute():
    print("=== EXECUTE：FC-001 显存耗尽注入 ===")
    free = check_vram()
    if free is not None and free < 4096:
        print(f"[拒绝] 当前空闲显存 {free}MB < 4096MB，拒绝注入高显存压力")
        sys.exit(1)

    print(f"[1/4] 当前空闲显存：{free}MB")
    print("[2/4] 加载大模型 qwen3.5:9b...")
    result = api_call("POST", "/api/model", {"action": "load", "model": "qwen3.5:9b", "container": "ollama"})
    print(f"      结果：{json.dumps(result, ensure_ascii=False)[:200]}")

    print("[3/4] 提交高分辨率 ComfyUI 任务...")
    result = api_call("POST", "/api/queue", {
        "model": "flux",
        "workflow": "flux_q5",
        "parameters": {"width": 2048, "height": 2048, "batch_size": 4}
    })
    print(f"      结果：{json.dumps(result, ensure_ascii=False)[:200]}")

    print("[4/4] 等待 30 秒观察显存...")
    for i in range(6):
        time.sleep(5)
        free = check_vram()
        print(f"      [{i*5+5}s] 空闲显存：{free}MB")

    print()
    print("注入完成。请观察：")
    print("  - /api/alerts 中是否出现 vram_critical 告警")
    print("  - /api/diagnose 返回的根因候选")
    print("  - /api/events/timeline 中的事件流")


def recover():
    print("=== RECOVER：FC-001 恢复 ===")
    print("[1/3] 卸载大模型...")
    api_call("POST", "/api/model", {"action": "unload", "model": "qwen3.5:9b", "container": "ollama"})
    print("[2/3] 取消队列任务...")
    # 取消所有队列任务（需要先获取列表）
    print("[3/3] 释放显存...")
    result = api_call("POST", "/api/free", {"level": "L1"})
    print(f"      结果：{json.dumps(result, ensure_ascii=False)[:200]}")
    print("恢复完成。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FC-001 显存耗尽故障注入")
    parser.add_argument("--dry-run", action="store_true", help="预览操作")
    parser.add_argument("--execute", action="store_true", help="真实执行")
    parser.add_argument("--recover", action="store_true", help="执行恢复")
    args = parser.parse_args()

    if args.dry_run:
        dry_run()
    elif args.execute:
        execute()
    elif args.recover:
        recover()
    else:
        parser.print_help()
```

5 个脚本按此结构编写：
- `inject_vram_pressure.py`（FC-001）
- `inject_container_crash.py`（FC-002）：docker kill 容器
- `inject_latency.py`（FC-003）：提交超大 context 推理
- `inject_queue_backlog.py`（FC-004）：批量提交 10 个任务
- `inject_service_down.py`（FC-005）：停止 Ollama 容器

每个脚本都必须：
- 支持 `--dry-run` / `--execute` / `--recover` 三种模式
- 执行前检查显存状态，空闲 <4GB 时拒绝高显存压力注入
- 脚本顶部明确标注"仅用于演示和测试"
- 恢复操作能把系统恢复到注入前状态

#### S3.4 完成定义（DoD）
- [ ] `scripts/fault_injection/` 目录存在，5 个脚本全部编写
- [ ] 每个脚本支持 --dry-run/--execute/--recover
- [ ] 每个脚本执行前检查显存，<4GB 时拒绝高显存压力注入
- [ ] 至少 1 个脚本（如 inject_service_down.py）实测可运行并触发对应告警

---

### S3 总体验收

- [ ] `docs/故障场景库.md` 5 个场景完整定义
- [ ] `diagnose.py` 共 9 条规则（5 初始 + 4 扩展）
- [ ] `engine/alert_manager.py` 存在，聚合/静默/升级/历史全部实现
- [ ] `/api/alerts`、`/api/alerts/history`、`/api/alerts/{type}/silence`、`/api/alerts/{type}/resolve`、`/api/alerts/silenced` 全部可用
- [ ] `test_alert_manager.py` 全部通过
- [ ] 5 个故障注入脚本编写完成
- [ ] 显存进入 critical 时自动提交告警，恢复 safe 时自动 resolve
- [ ] 现有测试全部通过

---

## S4：前端重做（P0，8 人天）

> **前置条件**：S1-S3 的后端 API 全部可用（前端可用 mock 数据并行开发）
> **技术选型**：纯 ES Module 零构建（与 v2 相同技术栈，全新设计）
> **后置条件**：9 个页面全部可用，诊断中心和告警中心集成后端 API

### S4.1 设计系统 + 基础框架（1.5 人天）

#### 目录结构

```
web/
├── index.html              # 入口 HTML（挂载点 + ES Module）
├── css/
│   ├── variables.css       # 设计令牌（品牌色 #0d9488 + 语义色 + 间距 + 字体 + 阴影 + 圆角）
│   ├── reset.css           # 样式重置
│   ├── main.css            # 主样式入口（布局/网格/工具类）
│   └── components/         # 组件级样式
│       ├── button.css
│       ├── card.css
│       ├── modal.css
│       ├── sidebar.css
│       ├── toast.css
│       ├── table.css
│       ├── form.css
│       ├── badge.css
│       └── progress.css
├── js/
│   ├── main.js             # 应用入口
│   ├── core/
│   │   ├── utils.js        # 工具函数（格式化/防抖/DOM/escapeHtml）
│   │   ├── events.js       # 事件总线
│   │   ├── api.js          # API 客户端（封装全部后端 API，含新增的 events/diagnose/alerts）
│   │   ├── state.js        # 集中式状态管理
│   │   └── router.js       # 哈希路由
│   ├── components/
│   │   ├── sidebar.js      # 侧边栏导航
│   │   ├── header.js       # 顶部栏
│   │   ├── modal.js        # 弹窗/抽屉
│   │   ├── toast.js        # Toast 通知
│   │   ├── loading.js      # 加载状态
│   │   ├── vram-bar.js     # 显存水位能量条
│   │   ├── event-timeline.js # 事件时间线组件
│   │   └── alert-card.js   # 告警卡片组件
│   └── pages/
│       ├── dashboard.js    # 总览
│       ├── diagnose.js     # 诊断中心
│       ├── alerts.js       # 告警中心
│       ├── models.js       # 模型登记台
│       ├── vram.js         # 显存账本
│       ├── scenes.js       # 场景切换
│       ├── queue.js        # 任务队列
│       ├── guard.js        # 门卫
│       └── settings.js     # 设置
```

#### 核心 API 封装（`js/core/api.js`）必须包含的新增方法

```javascript
// 事件
api.eventsTimeline = (params) => get('/api/events/timeline', params)
api.eventsStats = (params) => get('/api/events/stats', params)

// 诊断
api.diagnose = (body) => post('/api/diagnose', body)
api.diagnoseRules = () => get('/api/diagnose/rules')

// 告警
api.alerts = () => get('/api/alerts')
api.alertsHistory = (params) => get('/api/alerts/history', params)
api.alertSilence = (alertType, duration) => post(`/api/alerts/${alertType}/silence`, {duration_minutes: duration})
api.alertResolve = (alertType) => post(`/api/alerts/${alertType}/resolve`, {})
api.alertsSilenced = () => get('/api/alerts/silenced')
```

#### S4.1 完成定义（DoD）
- [ ] `web/` 目录结构完整，所有基础文件创建
- [ ] CSS 变量定义完整（品牌色 #0d9488 + 语义色 + 间距 + 字体 + 阴影 + 圆角）
- [ ] `core/api.js` 封装全部后端 API（含新增的 events/diagnose/alerts）
- [ ] `core/router.js` 哈希路由可用
- [ ] `core/state.js` 状态管理可用
- [ ] `index.html` 入口可加载，显示应用框架（sidebar + header + content）
- [ ] 所有 JS 文件通过 `.mjs` 语法检查

---

### S4.2 Dashboard 总览页（1.5 人天）

#### 页面结构

```
┌──────────────────────────────────────────────────┐
│  Header：标题 + 活跃告警横幅 + 用户信息 + 退出      │
├──────────┬───────────────────────────────────────┤
│          │  显存水位能量条（L0 一瞥）               │
│          │  [████████████░░░░] 10.6GB/16GB  safe │
│          │                                       │
│  Sidebar │  快捷动作区（L1 动作）                  │
│          │  [一键释放] [预演模式] [场景切换] [诊断] │
│          │                                       │
│  - 总览  │  统计卡 4 张                           │
│  - 诊断  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐│
│  - 告警  │  │ GPU  │ │ 场景 │ │活跃模│ │ QoS  ││
│  - 模型  │  │10.6G │ │dialog│ │ 3 个 │ │GREEN ││
│  - 账本  │  └──────┘ └──────┘ └──────┘ └──────┘│
│  - 场景  │                                       │
│  - 队列  │  活跃告警卡片（如有）                    │
│  - 门卫  │  ⚠️ 显存危险 · 已持续 3 分钟 · [查看]  │
│  - 设置  │                                       │
│          │  服务活跃度 + 健康分                    │
│          │  Ollama ✅ 85分 | ComfyUI ❌ 0分 | ...│
└──────────┴───────────────────────────────────────┘
```

#### 核心功能
- 显存水位能量条：绿/黄/红状态机，危险等级闪烁，点击展开详情
- 快捷动作：一键释放（调 /api/free）、预演模式（调 /api/budget）、场景切换（跳场景页）、诊断（跳诊断页）
- 统计卡 4 张：GPU 显存/当前场景/活跃模型数/QoS 状态
- 活跃告警横幅：有告警时显示，点击跳告警中心；无告警时隐藏
- 服务活跃度：各服务在线状态 + 健康分（S5 完成后接入，先显示在线/离线）
- 10 秒轮询刷新

#### S4.2 完成定义（DoD）
- [ ] Dashboard 页面渲染正常，所有组件显示
- [ ] 显存水位条实时反映 /api/status 数据
- [ ] 一键释放按钮调用 /api/free 并刷新数据
- [ ] 有活跃告警时显示横幅，点击跳告警中心
- [ ] 10 秒轮询正常，页面无闪烁
- [ ] 浏览器 console 无错误

---

### S4.3 诊断中心页（1.5 人天）

#### 页面结构（三栏或上下布局）

```
┌──────────────────────────────────────────────────────────┐
│  诊断中心                                                  │
│  [告警类型下拉: vram_critical ▼] [时间窗: 5分钟 ▼] [诊断] │
├──────────────────────────┬───────────────────────────────┤
│  根因分析（Top3）          │  事件时间线                    │
│                          │                               │
│  ┌─ 1. ComfyUI 生成任务 ─┐│  12:05:23  task  task_submit│
│  │  置信度: ████████ 85% ││  12:05:15  vram  state_change│
│  │  根因: ComfyUI 生成... ││  12:04:58  model model_loaded│
│  │  建议: 暂停队列/降低... ││  12:04:30  user  scene_switch│
│  │  [查看关联事件] [执行建议]││  ...                         │
│  └────────────────────────┘│  [类别筛选: 全部 ▼] [级别: ▼]│
│  ┌─ 2. 大模型加载 ────────┐│  [搜索事件...]                │
│  │  置信度: ███████  80%  ││                               │
│  │  ...                    ││                               │
│  └────────────────────────┘│                               │
│  ┌─ 3. 桌面应用占用 ──────┐│                               │
│  │  置信度: ██████   75%  │                               │
│  └────────────────────────┘│                               │
├──────────────────────────┴───────────────────────────────┤
│  故障场景库（5 个场景卡片，点击展开处置步骤 + 注入演示按钮）    │
└──────────────────────────────────────────────────────────┘
```

#### 核心功能
- 根因分析面板：选择告警类型和时间窗 → 点击"诊断"→ 调用 `/api/diagnose` → 展示 Top3 根因候选
- 每个根因候选：根因描述、置信度进度条、处置建议、"查看关联事件"（高亮时间线中相关事件）、"执行建议"（调用对应 API）
- 事件时间线：垂直时间轴，按 category 颜色标记，支持筛选/搜索，默认显示最近 100 条
- 故障场景库：5 个场景卡片，展开显示处置步骤，提供"注入演示"按钮（调用 S3.4 的脚本，或显示命令让用户手动执行）

#### S4.3 完成定义（DoD）
- [ ] 诊断中心页面渲染正常
- [ ] 选择告警类型后点击诊断，调用 `/api/diagnose` 并展示 Top3
- [ ] 每个根因候选显示置信度进度条、处置建议、关联事件
- [ ] 点击"查看关联事件"，时间线中相关事件高亮
- [ ] 事件时间线实时显示 `/api/events/timeline` 数据，支持筛选
- [ ] 故障场景库 5 个卡片可展开，显示处置步骤
- [ ] 浏览器 console 无错误

---

### S4.4 告警中心页（1 人天）

#### 页面结构

```
┌──────────────────────────────────────────────────────┐
│  告警中心                                [活跃: 2] [静默: 1] │
├──────────────────────────────────────────────────────┤
│  活跃告警                                               │
│  ┌──────────────────────────────────────────────────┐ │
│  │ 🔴 vram_critical · 已持续 5 分钟 · 触发 3 次      │ │
│  │ 显存剩余 0.8GB，存在 OOM 风险                       │ │
│  │ [查看根因] [静默 30 分钟] [标记已解决]              │ │
│  └──────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────┐ │
│  │ 🟡 container_restart · 已持续 2 分钟 · 触发 1 次   │ │
│  │ ComfyUI 容器异常退出                                 │ │
│  │ [查看根因] [静默 30 分钟] [标记已解决]              │ │
│  └──────────────────────────────────────────────────┘ │
│                                                        │
│  静默中的告警                                           │
│  ┌──────────────────────────────────────────────────┐ │
│  │ ⚪ vram_warning · 剩余静默 25 分钟   [取消静默]     │ │
│  └──────────────────────────────────────────────────┘ │
│                                                        │
│  告警历史（最近 50 条）                                  │
│  时间 | 动作 | 类型 | 级别 | 消息                        │
│  12:05 | new | vram_critical | critical | 显存剩余...  │
│  12:06 | aggregated | vram_critical | critical | ...   │
│  ...                                                    │
└──────────────────────────────────────────────────────┘
```

#### 核心功能
- 活跃告警列表：告警类型、级别（颜色编码）、持续时长、触发次数（聚合）、消息
- 操作：查看根因（跳诊断中心，带 alert_type 参数）、静默（30 分钟/1 小时/自定义）、标记已解决
- 静默中的告警：显示剩余静默时间，可取消静默
- 告警历史：最近 50 条，含动作（new/aggregated/resolved/silenced/escalated）
- 5 秒轮询刷新活跃告警

#### S4.4 完成定义（DoD）
- [ ] 告警中心页面渲染正常
- [ ] 活跃告警列表实时反映 `/api/alerts` 数据
- [ ] 静默按钮调用 `/api/alerts/{type}/silence`，静默后告警从活跃列表移除
- [ ] 标记已解决调用 `/api/alerts/{type}/resolve`
- [ ] 查看根因跳诊断中心并自动填充 alert_type
- [ ] 告警历史显示 `/api/alerts/history` 数据
- [ ] 5 秒轮询正常
- [ ] 浏览器 console 无错误

---

### S4.5 其余页面（1.5 人天）

以下页面沿用 v2 的功能逻辑，但用新设计系统重写 UI：

| 页面 | 核心功能 | 优先级 |
|------|---------|-------|
| models.js 模型登记台 | 模型卡片网格 + 分类筛选 + 详情抽屉 + 扫描登记 | P1 |
| vram.js 显存账本 | 显存分布条 + 进程级明细表 + 趋势图 + Helper 启停 | P1 |
| scenes.js 场景切换 | 6 场景卡片 + 当前状态高亮 + 切换日志 | P1 |
| queue.js 任务队列 | 任务提交表单 + 队列列表 + 进度 + 取消 | P1 |
| guard.js 门卫 | 进程治理 + 驱逐 + 桌面进程 | P2 |
| settings.js 设置 | 系统配置 + 服务状态 + QoS + 账号 + 自动防死机 | P2 |

每个页面必须：
- 通过 `core/api.js` 调用后端 API，禁止直接 fetch
- 通过 `core/state.js` 管理状态
- 支持页面进入/离开生命周期（onEnter/onLeave）
- 空状态和错误状态处理
- 所有 JS 文件通过 `.mjs` 语法检查

#### S4.5 完成定义（DoD）
- [ ] 6 个页面全部创建并注册路由
- [ ] 每个页面可正常渲染和交互
- [ ] P1 页面（models/vram/scenes/queue）功能完整
- [ ] P2 页面（guard/settings）至少基础功能可用
- [ ] sidebar 导航可切换所有页面
- [ ] 浏览器 console 无错误

---

### S4 总体验收

- [ ] 9 个页面全部创建并注册路由
- [ ] Dashboard/诊断中心/告警中心（P0 页面）功能完整
- [ ] models/vram/scenes/queue（P1 页面）功能完整
- [ ] guard/settings（P2 页面）基础功能可用
- [ ] 登录 → Dashboard → 各页面导航无 404
- [ ] 诊断中心全链路：模拟告警 → 根因分析 → 关联事件高亮 → 处置执行
- [ ] 告警中心全链路：聚合/静默/升级/历史
- [ ] 所有 JS 文件通过 `.mjs` 语法检查
- [ ] 无全局变量污染，CSS 无冲突
- [ ] 浏览器 console 无错误
- [ ] 根路径 `/` 返回新前端（不再是占位页）

---

## S5：拓扑图 + 健康度评分（P2，可选，6.5 人天）

> **前置条件**：S1 完成（实时数据可用）、S4 完成（前端框架可用）
> **建议**：S1-S4 完成后如时间充裕再做，否则跳过

### S5.1 资源拓扑图（5 人天）

#### 新建组件：`web/js/components/topology-graph.js`

纯 SVG 实现，四层节点：
- 顶层：GPU 节点（型号、总显存、已用/空闲、危险等级颜色）
- 第二层：容器节点（ComfyUI/Ollama/Fooocus/OWUI 等，运行状态、显存占用）
- 第三层：模型节点（每个容器下加载的模型，模型名、显存占用、状态）
- 第四层：任务节点（ComfyUI 队列中的任务，状态、进度）

布局算法：简单树形分层布局，手动计算坐标（节点数 <20 不需要力导向）。

交互：
- 点击容器节点 → 展开/折叠下属模型
- 点击模型节点 → 显示模型详情（复用模型登记台抽屉）
- 悬停节点 → 显示显存占用 tooltip
- 显存危险时相关节点红色闪烁

#### S5.1 完成定义（DoD）
- [ ] 拓扑图组件渲染：GPU 节点 + 容器节点 + 模型节点，层级关系正确
- [ ] 节点显存数据与 /api/status 一致
- [ ] 点击容器节点展开/折叠模型正常
- [ ] 显存危险时 GPU 节点红色闪烁
- [ ] 无模型加载时显示空状态提示

---

### S5.2 健康度评分（1.5 人天）

#### 后端：在 `api/endpoints/status.py` 的 `_build_status()` 中计算健康分

每个服务的健康分（0-100）：
- 可用性（40%）：在线=100，离线=0，启动中=50
- 响应速度（30%）：最近 API 调用响应时间（<1s=100，1-3s=70，3-10s=40，>10s=10）
- 稳定性（20%）：最近 1 小时重启次数（0次=100，1次=70，2次=40，≥3次=10）
- 资源健康（10%）：显存占用是否安全（<70%=100，70-85%=70，85-95%=40，>95%=10）

需要在 S1 的 docker events 中记录容器重启次数，在 status 调用中记录各服务响应时间。

#### 前端：Dashboard 服务卡片显示健康分

颜色编码：≥80 绿，50-79 黄，<50 红。

#### S5.2 完成定义（DoD）
- [ ] 所有在线服务健康分 ≥50
- [ ] 停止一个服务后其健康分变为 0
- [ ] Dashboard 服务卡片显示健康分和颜色
- [ ] 健康分计算逻辑有单元测试

---

## S6：演示整合 + 大赛材料（P0，3 人天）

### S6.1 演示流程设计（1 人天）

#### 5 分钟完整版脚本

| 时间 | 画面 | 旁白/字幕 | 操作 |
|------|------|----------|------|
| 0:00-0:30 | Dashboard 总览 | "GMae 实时掌握 GPU→容器→模型→任务的全链路状态" | 展示显存水位、服务状态、健康分 |
| 0:30-1:30 | 故障注入 | "模拟高负载场景：加载大模型 + 提交高分辨率生成任务" | 运行 inject_vram_pressure.py --execute |
| 1:30-2:30 | 告警弹出 | "显存进入 critical 状态，GMae 自动告警（聚合+升级）" | 展示告警中心，告警持续触发显示聚合计数 |
| 2:30-3:30 | 根因诊断 | "一键根因分析：Top3 根因候选 + 事件时间线关联" | 诊断中心，点击诊断，展示根因候选，点击关联事件高亮时间线 |
| 3:30-4:30 | 处置执行 | "点击处置建议一键释放，显存恢复，告警自动消除" | 点击"执行建议"，调用 /api/free，展示显存恢复，告警从活跃列表移除 |
| 4:30-5:00 | 收尾 | "GMae 不仅管显存，还能诊断故障——One GPU, Infinite Models" | 展示告警中心历史 + 健康度，总结 |

#### 3 分钟展示版脚本
压缩为：开场（15s）→ 故障注入+告警（45s）→ 根因诊断（1min）→ 处置执行（45s）→ 收尾（15s）

---

### S6.2 一键演示模式（1 人天）

#### 优化 v2 的一键演示 overlay，适配新前端

5 幕脚本（在新前端中重新实现）：
1. 显存秒级释放（真实 /api/free）
2. 门卫强制驱逐（模拟，不真实 kill）
3. 预算引擎智能决策（真实 /api/budget）
4. 故障注入→告警→根因→处置（真实调用 S3.4 脚本 + /api/diagnose）
5. 多场景稳定切换（模拟，不真实启停容器）

控制：开始/暂停/单步/停止/关闭，进度条+计时+当前显存实时刷新。

---

### S6.3 大赛材料更新（1 人天）

- 更新 `docs/作品介绍.md`：新增"可观测与诊断"章节，体现故障注入→告警→根因→处置闭环
- 更新 `docs/作品介绍.pdf`：重新生成 PDF
- 更新 `README.md`：新增功能说明（事件关联引擎、根因诊断、告警管理、故障场景库）
- 演示视频录制（需主公配合操作）
- 代码仓库整理：清理临时文件，补充 LICENSE/CONTRIBUTING

---

## 实施顺序与里程碑

```
第 1 周（9/1-9/7）：S1 轻量采集优化
  ├── S1.1 指标缓存层（1.5天）
  ├── S1.2 Docker Events（1天）
  ├── S1.3 并行化（0.5天）
  └── S1.4 nvidia-smi 缓存（0.5天）
  里程碑：/api/status <3秒，缓存命中 <500ms

第 2 周（9/8-9/14）：S2 事件关联引擎 + S4 前端框架启动（并行）
  ├── S2.1 EventBus + 事件 API（1.5天）
  ├── S2.2 显存状态变化事件（0.5天）
  ├── S2.3 用户操作事件审计（1天）
  ├── S2.4 Docker events 接入（0.5天）
  ├── S2.5 规则引擎（2天）
  └── S4.1 设计系统 + 基础框架（1.5天，并行）
  里程碑：/api/diagnose 返回 Top3 根因；前端框架可用

第 3 周（9/15-9/21）：S3 故障场景+告警降噪 + S4 前端页面（并行）
  ├── S3.1 故障场景库文档（1天）
  ├── S3.2 规则扩展（0.5天）
  ├── S3.3 告警管理器（2天）
  ├── S3.4 注入脚本（1天）
  ├── S4.2 Dashboard（1.5天，并行）
  ├── S4.3 诊断中心（1.5天，并行）
  └── S4.4 告警中心（1天，并行）
  里程碑：告警聚合/静默/升级可用；Dashboard/诊断/告警三页面完成

第 4 周（9/22-9/28）：S4 剩余页面 + S5（可选）
  ├── S4.5 其余 6 页面（1.5天）
  └── S5 拓扑图 + 健康度（6.5天，如时间充裕）
  里程碑：前端全部页面完成

第 5 周（9/29-10/5）：S6 演示整合
  ├── S6.1 演示流程设计（1天）
  ├── S6.2 一键演示模式（1天）
  └── S6.3 大赛材料更新（1天）
  里程碑：故障注入→告警→根因→处置完整演示闭环

第 6 周（10/6-10/10）：最终打磨 + 视频录制
  里程碑：演示视频完成，仓库整理完成

10/11：大赛截止
```

---

## 风险登记与应对

| # | 风险 | 影响 | 概率 | 应对措施 |
|---|------|------|------|---------|
| 1 | /api/status 缓存导致数据不一致 | 用户看到旧数据 | 中 | API 响应加 cached/cached_at 标记；写操作后主动失效；前端显示"数据更新于 X 秒前" |
| 2 | Docker events 在 Windows 下不稳定 | 容器状态不实时 | 中 | 降级方案：events 失败时回退到 docker exec ps（缓存 5 秒） |
| 3 | 规则引擎规则覆盖不全 | 根因诊断不准 | 高 | 初始 9 条规则覆盖常见场景；未匹配时返回默认诊断 + 事件时间线；文档说明"基于规则的推断，非 AI 分析" |
| 4 | 故障注入脚本误操作 | 影响生产环境 | 中 | 脚本开头加确认提示 + dry-run 模式；执行前检查显存，<4GB 时拒绝高显存压力注入；脚本名明确标注"仅用于演示和测试" |
| 5 | 前端重做工作量超预期 | 工期延误 | 高 | P0 页面优先（Dashboard/诊断/告警），P2 页面简化或延后；沿用 v2 的功能逻辑只重写 UI；必要时 S5 跳过 |
| 6 | 大赛时间紧 | 材料准备不足 | 中 | S6 演示整合提前准备脚本；核心演示流程在 S3 完成后即可预演 |
| 7 | 告警管理器状态丢失 | server 重启后告警/静默失效 | 低 | 活跃告警内存存储（可接受）；静默期持久化到 alerts_silenced.json |
| 8 | 新增 API 端点与现有路由冲突 | 404 或错误匹配 | 低 | 新增端点前用 `router.list_routes()` 检查现有路径；遵循现有命名规范 |

---

## 总体验收标准（全部完成后）

### 性能
- [ ] /api/status 热路径 <3 秒，缓存命中 <500ms
- [ ] 写操作后缓存失效

### 可观测与诊断
- [ ] /api/events/timeline 统一格式，支持过滤
- [ ] /api/diagnose 返回 Top3 根因候选，含关联事件和处置建议
- [ ] 9 条规则单元测试通过
- [ ] 5 个故障场景文档完整
- [ ] 5 个故障注入脚本可运行

### 告警
- [ ] /api/alerts 聚合/静默/升级/历史全部可用
- [ ] 显存 critical 自动提交告警，恢复 safe 自动 resolve
- [ ] 告警管理器单元测试通过

### 前端
- [ ] 9 个页面全部可用
- [ ] 诊断中心全链路：告警→根因→关联事件→处置
- [ ] 告警中心全链路：聚合/静默/升级/历史
- [ ] 浏览器 console 无错误

### 演示
- [ ] 故障注入→告警→根因→处置完整闭环可演示
- [ ] 一键演示模式可自动播放
- [ ] 演示视频录制完成

### 质量
- [ ] 所有新增模块配套单元测试
- [ ] 现有 98 个测试全部通过
- [ ] 代码工程最高指南评分 ≥8/10
- [ ] 文档同步更新（工作交接/开发日志/项目进度跟踪）

---

## 文档维护

- 本文档是开发指导手册，实施过程中：
  - 每个子任务完成后，在本文档对应位置标记 ✅
  - 发现与本文档不一致的实现，更新本文档
  - 踩坑记录追加到 `开发日志.md`
  - 进度更新到 `项目进度跟踪.md`
- 全部完成后：
  - 申请更新蓝图（补充"可观测与诊断层"设计章节）
  - 更新作品介绍和 README

---

*本文档由 2026-09-01 会话生成，作为 S1-S6 重构的开发指导。每个子任务含具体文件路径、类/函数名、数据结构、API 参数、测试用例和完成定义，可直接按顺序执行。*
