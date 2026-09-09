## 变更类型

<!-- 勾选适用的类型 -->
- [ ] 🐛 Bug 修复
- [ ] ✨ 新功能
- [ ] 📝 文档更新
- [ ] 🎨 代码重构
- [ ] ⚡ 性能优化
- [ ] 🔧 工具/配置
- [ ] 🧪 测试

## 变更描述

<!-- 清晰简洁地描述本次 PR 做了什么 -->

## 关联 Issue

<!-- 例如：Closes #123 -->

## 测试

- [ ] 本地运行通过 `python -m py_compile` 语法检查
- [ ] 调度中心启动正常（`start.bat` / `start.sh`）
- [ ] 健康检查通过（`curl http://127.0.0.1:8787/api/health`）
- [ ] 场景切换测试通过
- [ ] 无新增警告/错误日志

## 影响范围

<!-- 描述本次变更影响的模块 -->
- 影响模块：______
- 是否有破坏性变更：是 / 否

## 自检清单

- [ ] 代码遵循项目分层规范（core/gpu/services/engine/api）
- [ ] 无硬编码路径/容器名（使用 config.py 配置）
- [ ] 无硬编码显存阈值（使用 get_threshold_value）
- [ ] 敏感文件（.api_token/users.json/config.json）未提交
- [ ] 已更新相关文档（README/蓝图/开发日志）
- [ ] Commit 信息清晰（feat:/fix:/docs:/chore:）

## 附加说明

<!-- 任何需要 Reviewer 特别注意的事项 -->
