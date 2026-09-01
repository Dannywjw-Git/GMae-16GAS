# GMae CLI - 显存指挥家命令行工具

> **One GPU, Infinite Models** — 在终端直接操控 GMae 调度中心，支持脚本自动化与批量操作。

## 安装

```bash
cd vram-console
pip install -e .
```

安装后即可使用 `gmae` 命令。零第三方依赖，仅需 Python 3.8+。

## 快速开始

### 1. 配置 API Token

```bash
# 方式一：直接设置 Token（推荐）
gmae auth login --token your-api-token

# 方式二：环境变量
export GMAE_TOKEN=your-api-token
export GMAE_SERVER=http://127.0.0.1:8787

# 方式三：配置文件 ~/.gmae/config.json
gmae config set server http://127.0.0.1:8787
gmae config set token your-api-token
```

### 2. 查看状态

```bash
gmae status            # 系统状态总览（显存/场景/模型/QoS）
gmae service status    # 所有服务运行状态
gmae model list        # 已登记模型列表
```

## 命令组一览

| 命令组 | 功能 | 常用子命令 |
|--------|------|-----------|
| `status` | 系统状态总览 | — |
| `vram` | 显存管理 | `free` / `budget` / `advice` / `desktop` |
| `scene` | 场景切换 | `list` / `switch` / `combo` |
| `model` | 模型管理 | `list` / `load` / `unload` / `scan` / `register` |
| `queue` | 任务队列 | `list` / `submit` / `cancel` |
| `guard` | 门卫管理 | `check` / `evict` / `kick` |
| `service` | 服务控制 | `status` / `start` / `stop` / `helper` / `container` |
| `logs` | 日志查看 | `-n` / `--level` / `--event` |
| `config` | 配置管理 | `show` / `set` / `autoprotect` / `qos` |
| `auth` | 认证管理 | `status` / `login` / `logout` / `whoami` |

## 常用示例

### 显存管理

```bash
gmae vram free                    # 一键释放全部显存
gmae vram budget                  # 预算引擎：各模型能否运行
gmae vram budget --context qwen3.5:9b:32768  # 上下文覆盖重算
gmae vram advice                  # 智能显存建议
gmae vram desktop                 # 桌面进程显存占用
```

### 场景与模型

```bash
gmae scene list                   # 列出可用场景
gmae scene switch comfyui         # 切换到 ComfyUI 场景
gmae scene combo 9b               # 切换对话模型到 9B
gmae model list --category llm    # 仅列出 LLM 模型
gmae model load qwen3.5:9b       # 加载模型
gmae model unload qwen3.5:9b     # 卸载模型
gmae model scan                   # 扫描新模型
```

### 任务队列

```bash
gmae queue list                            # 查看队列
gmae queue submit sdxl --prompt "a cat"   # 提交文生图任务
gmae queue submit sdxl --params '{"steps":30,"cfg":7.5}'
gmae queue cancel task-123                 # 取消任务
```

### 门卫与服务

```bash
gmae guard check                  # 检查未登记/异常进程
gmae guard evict                  # 执行驱逐建议
gmae guard kick 12345             # 强制结束进程
gmae service start comfyui        # 启动服务
gmae service stop ollama          # 停止服务
gmae service helper start         # 启动桌面 Helper
```

### 日志与配置

```bash
gmae logs -n 50                   # 最近 50 条日志
gmae logs -n 20 --level error     # 仅错误日志
gmae logs --event vram_danger      # 按事件筛选
gmae config show                  # 显示 CLI 配置
gmae config autoprotect status    # 自动防死机状态
gmae config autoprotect enable --mode standard --level danger
gmae config qos check             # 触发 QoS 检查
```

## 输出格式

```bash
# 默认：人类可读表格
gmae status

# JSON 输出（脚本集成）
gmae status --json
gmae model list --json | jq '.models[] | .name'

# 全局 JSON 模式
gmae config set output json
```

## 全局选项

| 选项 | 说明 |
|------|------|
| `--server URL` | 覆盖服务器地址 |
| `--token TOKEN` | 覆盖 API Token |
| `--timeout N` | 覆盖请求超时（秒） |
| `--no-color` | 禁用彩色输出 |
| `-v, --version` | 显示版本 |
| `-h, --help` | 显示帮助 |

## 配置文件

位置：`~/.gmae/config.json`

```json
{
  "server": "http://127.0.0.1:8787",
  "token": "your-api-token",
  "timeout": 30,
  "output": "table",
  "color": true
}
```

环境变量 `GMAE_SERVER` / `GMAE_TOKEN` / `GMAE_TIMEOUT` 优先级高于配置文件。

## 架构

```
cli/
├── __init__.py          # 版本信息
├── __main__.py          # python -m cli 入口
├── main.py              # argparse 主入口 + 命令分发
├── client.py            # HTTP 客户端（封装全部 30+ API）
├── config.py            # 配置管理（文件 + 环境变量）
├── formatter.py         # 输出格式化（表格/JSON/颜色/显存条）
└── commands/
    ├── status.py        # 系统状态
    ├── vram.py          # 显存管理
    ├── scene.py         # 场景切换
    ├── model.py         # 模型管理
    ├── queue.py         # 任务队列
    ├── guard.py         # 门卫
    ├── service.py       # 服务控制
    ├── logs.py          # 日志
    ├── config_cmd.py    # 配置
    └── auth.py          # 认证
```

## 许可

MIT License
