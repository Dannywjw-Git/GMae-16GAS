# GPU Maestro 看门狗与自启动登记册

> **目的**：统一登记系统中所有看门狗、自启动、定时任务，避免多 agent 重复创建或失控。
> **维护者**：任何 agent 修改看门狗配置后必须更新此文件。
> **最后更新**：2026-08-26

---

## 一、看门狗清单（当前生效）

| 名称 | 类型 | 路径 | 状态 | 作用 | 启动方式 |
|------|------|------|------|------|---------|
| **GMae-Watchdog** | Python 脚本 | `vram-console/watchdog.py` | ✅ 唯一看门狗 | 监控 server.py，崩溃 5 秒后自动重启 | 开机自启 / 手动 start.bat |

### GMae-Watchdog 详情
- **脚本**：`vram-console/watchdog.py`
- **启动器**：`vram-console/run_watchdog.bat`（自动查找 python.exe 路径）
- **隐藏启动**：`vram-console/watchdog.vbs`（调用 run_watchdog.bat，隐藏窗口）
- **监控对象**：`vram-console/server.py`（调度中心后端，端口 8787）
- **重启策略**：进程退出后等待 5 秒重启
- **防死循环**：1 小时内最多重启 10 次，超过则暂停 5 分钟
- **日志**：`vram-console/logs/watchdog.log`
- **服务日志**：`vram-console/logs/vram-console.log`（按天轮转，保留 30 天）

### 重要：沙箱环境限制说明
AI Agent 通过工具调用（Start-Process 等）启动的后台进程，在工具调用结束后可能被沙箱清理。
**正确启动方式**：
1. 用户手动双击 `start.bat`（推荐）
2. 重启电脑，开机自启项自动生效
3. Agent 如需启动，应告知用户手动操作，而非依赖工具调用的持久性

---

## 二、自启动项

| 名称 | 位置 | 指向 | 状态 |
|------|------|------|------|
| VRAM_Console.vbs | `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\` | `python.exe watchdog.py` | ✅ 启用 |

> 开机后自动启动 GMae-Watchdog，看门狗再启动 server.py。

---

## 三、统一管理脚本

| 脚本 | 作用 | 用法 |
|------|------|------|
| `start.bat` | 启动看门狗（最小化窗口） | 双击运行（推荐用户手动启动） |
| `stop.bat` | 停止看门狗 + 服务（杀所有 python 进程） | 双击运行 |
| `status.bat` | 查看进程、端口、健康检查、最近日志 | 双击运行 |
| `run_watchdog.bat` | 看门狗启动器（自动找 python 路径） | 被 start.bat 和开机自启调用 |
| `watchdog.vbs` | 隐藏窗口启动 run_watchdog.bat | 被开机自启项调用 |

### 当前 vram-console 目录下的脚本文件
- `server.py` — 调度中心主程序
- `watchdog.py` — 看门狗程序
- `run_watchdog.bat` — 看门狗启动器（自动找 python）
- `start.bat` — 用户启动入口
- `stop.bat` — 停止服务
- `status.bat` — 查看状态
- `watchdog.vbs` — 隐藏窗口启动（供开机自启用）
- `WATCHDOGS.md` — 本登记文件

---

## 四、Docker 容器重启策略（Docker 层面的看门狗）

| 容器 | 重启策略 | 说明 |
|------|---------|------|
| ollama | unless-stopped | 手动停止后不重启 |
| open-webui | unless-stopped | |
| comfyui | unless-stopped | **禁止 docker compose up -d**（会清空容器改动） |
| fooocus | unless-stopped | |
| searxng | unless-stopped | |
| caddy | unless-stopped | |
| n8n | unless-stopped | |
| immich-server | always | 总是重启 |
| immich-redis | always | |
| immich-database | always | |
| immich-machine-learning | always | |
| nextcloud-* | unless-stopped | |

---

## 五、已废弃/已删除的看门狗

| 名称 | 原路径 | 删除时间 | 原因 |
|------|--------|---------|------|
| watchdog.bat | `vram-console/watchdog.bat` | 2026-08-26 | bat 循环不稳定，cmd 进程莫名退出 |
| start.bat（旧版） | `vram-console/start.bat` | 2026-08-26 | 直接 pythonw 启动，无看门狗 |
| start_with_log.bat | `vram-console/start_with_log.bat` | 2026-08-26 | 直接启动，无看门狗 |

---

## 六、Agent 操作规范

### 新 agent 接手时必须做：
1. 阅读本文件，确认当前看门狗状态
2. 运行 `status.bat` 或执行 `curl http://127.0.0.1:8787/api/health` 确认服务正常
3. **禁止**创建新的看门狗，如需修改必须先停止现有看门狗

### 修改看门狗前必须做：
1. 运行 `stop.bat` 停止现有看门狗
2. 修改 `watchdog.py`
3. 运行 `start.bat` 启动并验证
4. 更新本文件

### 禁止行为
- ❌ 禁止创建多个看门狗同时监控同一服务
- ❌ 禁止用 pythonw.exe 启动 watchdog.py（经测试不稳定，subprocess 会异常退出）
- ❌ 禁止删除 Startup 中的 VRAM_Console.vbs 而不更新本文件
- ❌ 禁止在未停止现有看门狗的情况下直接启动 server.py（会导致端口冲突）

---

## 七、故障排查

### 服务不可用
1. 运行 `status.bat` 查看进程和端口
2. 查看 `logs/watchdog.log` 确认看门狗是否在运行
3. 查看 `logs/vram-console.log` 查看服务崩溃原因
4. 如看门狗也挂了，运行 `start.bat` 重启

### 端口冲突（8787 被占用）
1. `netstat -ano | findstr :8787` 找到占用进程 PID
2. 确认是否是旧的 server.py 残留
3. 运行 `stop.bat` 清理后重新 `start.bat`

### 看门狗反复重启（1小时10次）
- 说明 server.py 有持续崩溃的 bug
- 查看 `logs/vram-console.log` 的 server_crash 事件
- 修复 bug 后再启动

---

*文档版本：v1.0 | 创建：2026-08-26 | 任何修改必须更新此文件*
