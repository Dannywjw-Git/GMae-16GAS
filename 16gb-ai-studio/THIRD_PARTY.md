# Third-Party Notices / 第三方组件声明

> 本文件登记 GMae / 16G-AI-Studio 使用、依赖或参考的第三方开源项目。
> 主许可证：MIT（见 [LICENSE](LICENSE)）。合规规则见 `docs/开源借鉴与许可证合规指南.md`。
> 最后更新：2026-09-03

---

## 一、运行时依赖（随程序安装/调用）

| 项目 | 版本 | 许可证 | 用途 | 使用方式 |
|------|------|--------|------|---------|
| psutil | 7.x | BSD-3-Clause | CPU/内存/磁盘/网络系统信息探测（`core/system_info.py`） | pip 依赖，API 调用 |
| Python 标准库 | 3.13 | PSF-2.0 | 运行时基础 | 内置 |

## 二、开发/测试依赖

| 项目 | 许可证 | 用途 | 使用方式 |
|------|--------|------|---------|
| pytest | MIT | 单元测试框架 | 开发依赖 |
| setuptools | MIT | 打包 | 开发依赖 |

## 三、外部系统组件（独立进程/容器，非 GMae 代码衍生）

> 以下组件以独立容器或外部进程方式被 GMae 调度编排，进程间通过 HTTP/Docker API 交互，**不构成 GMae 的衍生作品**，各自遵循其独立许可证。

| 组件 | 许可证 | 用途 |
|------|--------|------|
| Docker / Docker Compose | Apache-2.0 | 容器运行时 |
| Ollama | MIT | 本地大模型推理服务 |
| ComfyUI | GPL-3.0（独立进程，仅 API 调度） | 图像/视频生成工作流引擎 |
| Open WebUI | MIT（独立容器） | 对话前端 |
| NVIDIA driver / nvidia-smi | NVIDIA EULA | GPU 硬件接口（命令行调用） |

## 四、设计参考项目（学习思路，未复制源码）

> 以下项目仅用于架构/算法思路参考，GMae 代码独立实现。

| 项目 | 许可证 | 参考内容 |
|------|--------|---------|
| Ordo-AI-Stack (AlienWalker1995) | MIT | GPU 仲裁模型（resident/burst/exempt）、lease 准入门控、声明式服务 manifest、MCP Gateway 思路 |
| gpu-orchestrator (darks0l) | MIT | VRAM 软上限分级策略（strict/balanced/lenient）、多计算后端探测、运行时配置生成 |
| GPU Memory Guard (CastelDazur) | 见其仓库 | 模型加载前 VRAM 预检、防 OOM 检查清单思路 |
| PromptChain | 见其仓库 | 受限显存下多模型自动卸载/加载切换思路 |
| MMGP (deepbeepmeep) | **GPL-3.0（仅学思路，禁止复制源码）** | 显存分层 offload、低显存档位策略 |

## 五、计划引入的库（尚未集成，引入前复核许可证）

| 项目 | 许可证 | 计划用途 | 状态 |
|------|--------|---------|------|
| nvitop（仅 `nvitop.api`） | Apache-2.0（API）/ GPL-3.0（TUI，不使用） | 增强 GPU 进程级监控，替代手写 nvidia-smi 解析 | 待引入，只用 API 层 |
| dagre | MIT | 5层拓扑图自动分层布局 | 待引入 |
| Cytoscape.js | MIT | 复杂拓扑交互（折叠/搜索/过滤） | 中期评估 |

---

## 维护规则

1. 新增任何第三方依赖或参考项目时，必须在本文件登记一行。
2. 从 MIT/Apache/BSD 项目**复制源码**时，在被复制文件顶部保留原版权头（模板见合规指南第三节）。
3. **禁止**把 GPL/AGPL 项目源码复制进 GMae 代码树；GPL 程序只能作为独立外部进程被调度。
4. 定期用 `pip-licenses` 扫描 Python 传递依赖许可证。
