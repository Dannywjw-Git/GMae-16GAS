# 贡献指南

感谢你对 16GB AI Studio 的关注！欢迎提交 Issue 和 PR。

## 项目简介

在消费级 16GB 显卡上跑通全模态本地 AI 生成（文生图/图生图/文生视频/图生视频/AI写歌/本地对话）。核心资产是显存调度方法论和 16GB 适配经验。

## 开发环境

- **Python 3.8+**（vram-console 后端，零依赖，纯标准库）
- **Node.js 16+**（run_comfy.js 工作流运行器）
- **Docker + Docker Compose v2**（ComfyUI / OWUI 等服务）
- **Git**

## 目录结构

```
16gb-ai-studio/
├── vram-console/       # 显存调度中心（Python 后端 + 单文件 HTML 前端）
├── scripts/            # 工具脚本（gpu_release / run_comfy.js / game-on）
├── workflows/          # ComfyUI 工作流（API 格式 JSON）
├── docker/             # Docker Compose 模板
├── docs/               # 文档（部署指南/踩坑集/审计报告等）
└── examples/           # 生成效果样例
```

## 提交规范

使用 [Conventional Commits](https://www.conventionalcommits.org/) 风格：

```
feat: 新增功能
fix: 修复 bug
docs: 文档更新
style: 代码格式（不影响功能）
refactor: 重构
perf: 性能优化
test: 测试相关
chore: 构建/工具/依赖变动
```

示例：
- `fix(vram): 防止 model_action 命令注入`
- `docs: 更新 H3 部署指南 torch 2.13 升级步骤`
- `feat(workflow): 新增 Flux 图生图工作流`

## PR 流程

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feature/your-feature`
3. 提交更改：`git commit -m 'feat: 描述你的改动'`
4. 推送到分支：`git push origin feature/your-feature`
5. 提交 Pull Request

## 代码风格

### Python（vram-console/server.py）
- 零外部依赖，仅用标准库
- 函数名 snake_case，常量 UPPER_SNAKE_CASE
- 包含用户输入的命令必须用 `shell=False` + 参数数组
- 用户输入必须做白名单/格式校验

### JavaScript（scripts/run_comfy.js）
- 无构建步骤，直接用 Node.js 运行
- 异步操作使用 async/await
- 必须有超时机制，禁止无限轮询

### PowerShell（scripts/*.ps1）
- 文件编码 UTF-8 with BOM（中文不乱码）
- 支持 `-ExecutionPolicy Bypass -File` 方式运行
- 参数使用 `param()` 声明

## 工作流规范

- 工作流文件为 ComfyUI API 格式（非 UI 格式）
- 模型文件名与 README 模型清单一致
- 提示词使用英文（ComfyUI 节点兼容性更好）
- 提交前在本地验证可运行

## 安全要求

提交前请自查：
- [ ] 无硬编码密钥/Token/个人信息
- [ ] 用户输入经过校验，无命令注入风险
- [ ] 不包含大文件（模型文件 >10MB 不入库，用下载链接）
- [ ] 文档中无内部代号/敏感路径

## 报告 Issue

报告问题时请提供：
1. 硬件配置（GPU 型号/显存/内存）
2. 系统环境（Windows/Linux，Docker 版本）
3. 复现步骤
4. 预期行为 vs 实际行为
5. 相关日志/截图

## 联系

- GitHub Issues：https://github.com/Dannywjw-Git/Local-AI-Studio/issues
- Gitee：https://gitee.com/dnnywang/local-ai-studio
