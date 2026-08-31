# 评估结果目录

> 所有模型评估结果存放在此目录，按模态/模型/日期组织。

## 目录结构

```
results/
├── images/          # 图像生成评估结果
│   └── {模型名}_{量化}_{YYYYMMDD}/
│       ├── IMG-01.png
│       ├── IMG-02C.png
│       ├── ...
│       └── batch_result.json
├── videos/          # 视频生成评估结果
│   └── {模型名}_{量化}_{YYYYMMDD}/
├── audio/           # 音频生成评估结果
│   └── {模型名}_{量化}_{YYYYMMDD}/
└── llm/             # LLM 评估结果
    └── {模型名}_{YYYYMMDD}/
        ├── llm_eval_{模型}.json
        └── 评估记录.md
```

## 命名规范

- 目录名：`{模型名}_{量化}_{YYYYMMDD}`（如 `flux_dev_Q5_20260827`）
- 评估记录：`{模型名}_{量化}_{YYYYMMDD}_评估记录.md`
- 对比报告：`{对比主题}_{YYYYMMDD}_对比报告.md`
- 原始数据：`batch_result.json`（图像/视频）或 `llm_eval_{模型}.json`（LLM）

## 说明

- 每次评估创建独立目录，不要覆盖历史结果
- 原始 JSON 数据必须保留，便于后续重新分析
- 对比报告引用各模型的评估记录路径
