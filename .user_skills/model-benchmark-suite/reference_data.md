# 参考数据 — 标准 Prompt 集与行业基准

> 本文件是评估套件的参考数据，从 SKILL.md 拆分出来以便独立更新。
> 最后更新：2026-08-27

---

## 一、标准化测试 Prompt 集

### 1.1 图像生成（9条，含中文测试）

| ID | 类型 | Prompt |
|----|------|--------|
| IMG-01 | 写实人像 | "A 25-year-old woman with curly brown hair, wearing a vintage leather jacket, standing in a rainy Tokyo street at night, neon lights reflecting on wet pavement, cinematic lighting, 8k" |
| IMG-02 | 英文文字渲染 | "A minimalist poster with bold text 'GMae 2026' in the center, black background, gold geometric shapes, modern design" |
| IMG-02C | 中文文字渲染 | "一张极简海报，中央有醒目的中文文字'显存指挥家'，黑色背景，金色几何图形，现代设计风格" |
| IMG-03 | 多物体计数 | "Five red apples and three green bananas arranged on a wooden table, natural window light, photorealistic" |
| IMG-04 | 颜色/位置 | "A blue cat sitting on top of a red car, yellow sun in background, green grass, simple illustration style" |
| IMG-05 | 科幻场景 | "A futuristic city with flying cars, massive glass skyscrapers, sunset orange sky, cyberpunk style, highly detailed" |
| IMG-06 | 艺术风格 | "Starry Night style painting of a modern city skyline, thick brushstrokes, swirling clouds, vibrant colors" |
| IMG-07 | 产品图 | "A matte black wireless headphones on a white pedestal, soft studio lighting, product photography, sharp focus" |
| IMG-08 | 复杂场景 | "A medieval marketplace with merchants selling fruits, a knight in armor walking by, a castle in the distance, busy crowd, warm afternoon light, oil painting style" |

### 1.2 视频生成（8条）

| ID | 类型 | Prompt |
|----|------|--------|
| VID-01 | 人物运动 | "A woman with long hair walking slowly towards camera on a beach at sunset, waves crashing, wind blowing hair, cinematic, slow motion" |
| VID-02 | 物体动态 | "A coffee cup with steam rising, placed on a wooden table, morning sunlight through window, camera slowly panning left" |
| VID-03 | 自然场景 | "Aerial view of a forest in autumn, leaves falling, camera flying forward over treetops, golden hour lighting" |
| VID-04 | 城市动态 | "Timelapse of a busy intersection in Tokyo at night, cars moving, neon signs flickering, rain, high angle" |
| VID-05 | 文字动画 | "Text 'GMae' appearing letter by letter with golden particles, black background, elegant typography animation" |
| VID-06 | 动物行为 | "A cat chasing a laser pointer dot on a living room wall, playful, quick movements, cozy interior, warm light" |
| VID-07 | 科幻动态 | "A spaceship taking off from a desert planet, dust clouds, engine glow, camera tracking from side, epic scale" |
| VID-08 | 抽象艺术 | "Abstract liquid metal morphing into various shapes, reflective surface, colorful studio lighting, smooth transitions" |

### 1.3 音频生成（6条）

| ID | 类型 | Prompt |
|----|------|--------|
| AUD-01 | 电子音乐 | "Upbeat electronic dance music, 128 BPM, synth lead, strong bass drop, festival atmosphere" |
| AUD-02 | 钢琴独奏 | "Emotional piano solo, slow tempo, minor key, reverb, melancholic mood, solo instrument" |
| AUD-03 | 环境音 | "Rainforest ambient sounds, birds chirping, distant water stream, gentle wind, relaxing, 3D spatial audio" |
| AUD-04 | 语音合成 | "Hello, welcome to GMae, your personal AI studio. Today we will explore the future of creative intelligence."（英文女声） |
| AUD-05 | 电影配乐 | "Epic orchestral movie soundtrack, strings section, brass, timpani, building tension, heroic theme, cinematic" |
| AUD-06 | 音效 | "Sci-fi UI interface sounds, holographic button clicks, data processing whooshes, futuristic ambient tech sounds" |

### 1.4 LLM（8条，含自动评分）

| ID | 类型 | Prompt | 自动评分方式 |
|----|------|--------|------------|
| LLM-01 | 推理 | "一个农夫要带狼、羊、白菜过河，船每次只能带一样。农夫不在时狼吃羊、羊吃白菜。怎么安排才能全部安全过河？" | 关键词检查 |
| LLM-02 | 编程 | "用Python写一个快速排序函数，要求支持自定义比较函数，并有完整的类型注解和docstring。只输出代码。" | 代码运行验证 |
| LLM-03 | 知识 | "解释Transformer模型中自注意力机制的计算过程，包括Q/K/V的含义和缩放点积注意力的公式。" | 关键词检查 |
| LLM-04 | 指令遵循 | "用不超过50个字，以李白的诗风，写一首关于人工智能的七言绝句。" | 长度检查 |
| LLM-05 | 多轮对话 | 第一轮："我喜欢科幻电影"；第二轮："推荐3部不太知名但评分很高的"；第三轮："第二部的导演还拍过什么？" | 人工评估连贯性 |
| LLM-06 | 数学 | "一个水池有进水管和出水管。单开进水管6小时注满，单开出水管8小时放完。两管同时开，几小时注满？" | 数值验证（答案24） |
| LLM-07 | 创意 | "为一个16GB显存的AI工作室产品写一句slogan，要求不超过10个字，包含'无限'一词。" | 关键词检查 |
| LLM-08 | 中文理解 | "请用中文解释'显存调度'的含义，要求让一个完全不懂技术的人也能听懂，用一个生活中的比喻来说明。" | 关键词检查（比喻词） |

---

## 二、评估维度与权重

### 2.1 通用维度（所有模态必评）

| 维度 | 说明 | 数据来源 |
|------|------|---------|
| 模型大小 | 参数量 / 文件大小 | 模型卡 |
| 量化方式 | FP16/FP8/Q8/Q5/Q4/GGUF等 | 模型文件名 |
| 峰值显存 | 生成过程中的GPU峰值占用 | vram_monitor.py（0.5s采样） |
| 生成速度 | 单条平均耗时（秒） | 脚本自动计时 |
| 分辨率/时长 | 输出规格 | 工作流参数 |
| 开源协议 | Apache/MIT/非商用等 | 模型卡 |
| 成功率 | 成功/失败比例 | 脚本自动统计 |
| 失败类型 | OOM/超时/输出损坏/内容违规/其他 | 人工分类 |

### 2.2 图像生成主观维度（A/B 盲评用）

| 维度 | 权重 | 说明 |
|------|------|------|
| 提示词遵循 | 25% | 元素是否齐全、属性是否正确 |
| 美学质量 | 20% | 整体美感、艺术水准 |
| 文字渲染 | 15% | 中英文文字是否清晰正确 |
| 细节/纹理 | 15% | 材质真实感、细节丰富度 |
| 构图 | 15% | 画面布局、视觉重心 |
| 色彩 | 10% | 调色、光影、色彩和谐 |

### 2.3 视频生成主观维度

| 维度 | 权重 | 说明 |
|------|------|------|
| 提示词遵循 | 15% | 内容是否符合描述 |
| 主体一致性 | 20% | 主体是否变形/闪烁 |
| 运动质量 | 20% | 动作是否自然、物理合理 |
| 时序连贯性 | 15% | 帧间是否连贯、有无跳变 |
| 画质 | 15% | 清晰度、细节、噪声 |
| 闪烁控制 | 10% | 画面闪烁程度 |
| 创意性 | 5% | 创意表现 |

### 2.4 音频生成主观维度

| 维度 | 权重 | 说明 |
|------|------|------|
| 音质 | 25% | 清晰度、噪声、失真 |
| 风格符合 | 25% | 是否符合描述的风格 |
| 旋律/节奏 | 20% | 悦耳度、节奏感 |
| 人声自然度 | 15% | 语音的自然人声度 |
| 乐器分离度 | 10% | 各乐器可分辨度 |
| 创意性 | 5% | 创意表现 |

### 2.5 LLM 主观维度

| 维度 | 权重 | 说明 |
|------|------|------|
| 指令遵循 | 20% | 是否精确执行所有约束 |
| 推理能力 | 20% | 逻辑推理正确性 |
| 知识准确性 | 15% | 事实准确性、幻觉率 |
| 编程能力 | 15% | 代码质量和可运行性 |
| 多轮对话 | 10% | 上下文记忆和连贯性 |
| 创造力 | 10% | 输出创意和新意 |
| 响应速度 | 5% | tokens/s |
| 中文能力 | 5% | 中文理解和表达质量 |

---

## 三、行业排行榜参考数据

> 以下为公开可核验的参考数据，具体数值以官方最新发布为准。本地评测结果应与这些公开基准交叉验证。

### 3.1 图像生成（Artificial Analysis Arena Elo）

| 排名 | 模型 | Elo | 备注 |
|------|------|-----|------|
| 1 | GPT Image 2 (high) | ~1320 | OpenAI |
| 2 | Nano Banana 2 | ~1318 | Google |
| 3 | Flux 2 Pro | ~1315 | BFL |
| 4 | Midjourney v7 | ~1310 | Midjourney |
| 5 | MAI-Image 2.6 | ~1303 | Microsoft |

### 3.2 视频生成（VBench / RAVEN-Eval）

| 模型 | 类型 | 参数量 | 特点 |
|------|------|--------|------|
| Sora 2 | 闭源 | — | 综合质量最高 |
| Kling 3.0 | 闭源 | — | 国产最强 |
| MiniMax H3 | 开源 | ~52B(FP16) | 音视频同步 |
| Wan2.2 | 开源 | 14B | 低显存友好 |
| LTX-2.3 | 开源 | 22B | 长视频 |
| CogVideoX | 开源 | 5B | 轻量 |

### 3.3 LLM（LMSYS Arena / MT-Bench）

| 排名 | 模型 | MT-Bench | 备注 |
|------|------|----------|------|
| 1 | Claude Fable 5 | ~9.5 | 已停用(出口管制) |
| 2 | GPT-5.6 Sol | ~9.3 | OpenAI |
| 3 | Gemini 3.7 Pro | ~9.2 | Google |
| 4 | Claude Opus 4.8 | ~9.1 | Anthropic |
| 5 | Qwen3.6 35B | ~8.5 | 开源最强 |

### 3.4 综合基准

- **ALL Bench Leaderboard 2026**：跨6模态91模型的3层置信度排行榜
- **GenEval / DPG-Bench**：图像生成物体计数、颜色、位置、属性绑定
- **VBench-2.0 / EvalCrafter**：视频生成时序一致性、运动质量
- **MusicBench / FAD**：音频生成音质、旋律
- **MMLU / MT-Bench / Arena Hard / GSM8K**：LLM 综合能力

---

## 四、16GB 显存可行性参考表

> 基于 RTX 4060 Ti 16GB 实测数据，供模型选型参考。

| 模型 | 量化 | 文件大小 | 峰值显存 | 16GB可行 | 备注 |
|------|------|---------|---------|---------|------|
| SDXL 1.0 | FP16 | 6.5GB | ~8GB | ✅ | 稳定，推荐 |
| Flux.1 dev | Q5_K_S GGUF | 7.8GB | ~12GB | ✅ | 需关闭其他服务 |
| Flux.1 dev | FP16 | 23GB | >20GB | ❌ | 不可行 |
| MiniMax H3 | INT8 pruned | 11GB | ~14GB | ⚠️ | 顶格，需独占 |
| MiniMax Music3 | FP16 | 4.6GB | ~10GB | ✅ | 稳定 |
| Wan2.2 14B | Q4_K_S | 8.2GB×2 | ~15GB | ⚠️ | 双模型，顶格 |
| LTX-2.3 22B | Q4_K_M | 6.0GB | ~13GB | ✅ | 需关闭其他服务 |
| Qwen3.5 9B | FP16 | ~18GB | >16GB | ❌ | 需量化 |
| Qwen3.5 9B | Q4 | ~5GB | ~6GB | ✅ | 推荐 |
| Qwen3 27B | Q4 | ~16GB | ~14GB | ⚠️ | 顶格，需独占 |

> ⚠️ 标记为"顶格"的模型，生成前必须释放显存到 <4GB，且不能与其他GPU服务并发。
