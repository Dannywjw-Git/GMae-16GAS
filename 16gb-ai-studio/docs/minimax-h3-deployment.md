# MiniMax H3 本地部署指南（16GB 显卡）

> **定位**：在 16GB 消费级显卡上跑通 MiniMax H3 文生/图生视频（带原生音频）。
> **实测环境**：RTX 4060 Ti 16GB / ComfyUI 0.33.0 / Windows + WSL2
> **效果**：640×640 · 5秒视频 · 4步采样 · ~4分钟出片（含音频）

---

## 一、为什么选 H3

| 项 | MiniMax H3 | LTX-2.3 | Wan 2.2 |
|---|---|---|---|
| 16G 实测画质 | ✅ 全清晰、文字正确 | ❌ 低分辨率、跳帧 | 中 |
| 原生音视频同步 | ✅ 自带音频（MV神器） | ❌ 需另合 | 部分 |
| 分辨率上限 | 768p（开源权重） | 512p | 720p |
| 16G 可行性 | ✅ 量化版+offload | ✅ 但画质差 | 较难 |

> **结论**：在"写实真人 + 原生音频 + 16GB 单卡"组合上，H3 是当前最优解。

---

## 二、模型清单（共 ~52GB）

| 文件 | 大小 | 目录 | 下载源 |
|---|---|---|---|
| `minimax_h3_fl2va_int8_convrot.safetensors` | 31.7GB | `diffusion_models/` | [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3) |
| `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | 14.6GB | `text_encoders/` | 同上 |
| `minimax_h3_video_vae_fp16.safetensors` | 4.85GB | `vae/` | 同上 |
| `minimax_h3_audio_vae_fp32.safetensors` | 0.56GB | `vae/` | 同上 |
| `minimax_h3_fl2va_4step_lora.safetensors` | 0.7GB | `loras/` | [joyfox/MiniMax-H3-Turbo](https://huggingface.co/joyfox/MiniMax-H3-Turbo) |

> **国内下载**：用 `hf-mirror.com` 替换 `huggingface.co`，或魔搭（ModelScope）搜索同名模型。大文件建议分段多线程下载。

---

## 三、环境准备：torch 2.13 升级（ComfyUI 0.33 硬依赖）

> **⚠️ 容器内 pip 下 nvidia-* 包极慢（几百 KB/s），必须用宿主机 curl 下载后 cp 进容器。**

### 3.1 版本要求

| 组件 | 版本 | 说明 |
|---|---|---|
| torch | 2.13.0+cu130 | ComfyUI 0.33 必需，旧版 2.4.1 直接 FATAL |
| torchvision | 0.28.0+cu130 | 与 torch 匹配 |
| torchaudio | 2.11.0+cu130 | 与 torch 匹配 |
| triton | 3.7.1 | torch 2.13 依赖 |
| Python | 3.10 | cp310 wheel |

### 3.2 宿主机批量下载 wheel（共 ~2.6GB）

**PyTorch 官方包（4个，从 download.pytorch.org）：**
```
https://download.pytorch.org/whl/cu130/torch-2.13.0%2Bcu130-cp310-cp310-manylinux_2_28_x86_64.whl
https://download.pytorch.org/whl/cu130/torchvision-0.28.0%2Bcu130-cp310-cp310-manylinux_2_28_x86_64.whl
https://download.pytorch.org/whl/cu130/torchaudio-2.11.0%2Bcu130-cp310-cp310-manylinux_2_28_x86_64.whl
https://download.pytorch.org/whl/triton-3.7.1-cp310-cp310-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl
```

**NVIDIA CUDA 运行时包（16个，从 pypi.nvidia.com）：**
```
https://pypi.nvidia.com/cuda-toolkit/cuda_toolkit-13.0.3.0-py2.py3-none-any.whl
https://pypi.nvidia.com/nvidia-cublas/nvidia_cublas-13.1.1.3-py3-none-manylinux_2_27_x86_64.whl
https://pypi.nvidia.com/nvidia-cuda-cupti/nvidia_cuda_cupti-13.0.85-py3-none-manylinux_2_25_x86_64.whl
https://pypi.nvidia.com/nvidia-cuda-nvrtc/nvidia_cuda_nvrtc-13.0.88-py3-none-manylinux2010_x86_64.manylinux_2_12_x86_64.whl
https://pypi.nvidia.com/nvidia-cuda-runtime/nvidia_cuda_runtime-13.0.96-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
https://pypi.nvidia.com/nvidia-cudnn-cu13/nvidia_cudnn_cu13-9.20.0.48-py3-none-manylinux_2_27_x86_64.whl
https://pypi.nvidia.com/nvidia-cufft/nvidia_cufft-12.0.0.61-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
https://pypi.nvidia.com/nvidia-cufile/nvidia_cufile-1.15.1.6-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
https://pypi.nvidia.com/nvidia-curand/nvidia_curand-10.4.0.35-py3-none-manylinux_2_27_x86_64.whl
https://pypi.nvidia.com/nvidia-cusolver/nvidia_cusolver-12.0.4.66-py3-none-manylinux_2_27_x86_64.whl
https://pypi.nvidia.com/nvidia-cusparse/nvidia_cusparse-12.6.3.3-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
https://pypi.nvidia.com/nvidia-cusparselt-cu13/nvidia_cusparselt_cu13-0.8.1-py3-none-manylinux2014_x86_64.whl
https://pypi.nvidia.com/nvidia-nccl-cu13/nvidia_nccl_cu13-2.29.7-py3-none-manylinux_2_18_x86_64.whl
https://pypi.nvidia.com/nvidia-nvjitlink/nvidia_nvjitlink-13.3.33-py3-none-manylinux2010_x86_64.manylinux_2_12_x86_64.whl
https://pypi.nvidia.com/nvidia-nvshmem-cu13/nvidia_nvshmem_cu13-3.4.5-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
https://pypi.nvidia.com/nvidia-nvtx/nvidia_nvtx-13.0.85-py3-none-manylinux1_x86_64.manylinux_2_5_x86_64.whl
```

> 宿主机 curl 速度几十 MB/s，全部下载约 1-2 分钟。用 `curl -L -C - -o <file> <url>` 支持断点续传。

### 3.3 安装流程

```bash
# 1. cp 所有 wheel 进容器
docker cp _installers/*.whl comfyui:/tmp/

# 2. 容器内安装（本地 wheel，不走网络）
docker exec comfyui /opt/environments/python/comfyui/bin/pip install \
  /tmp/torch-2.13.0+cu130-cp310-cp310-manylinux_2_28_x86_64.whl \
  /tmp/torchvision-0.28.0+cu130-cp310-cp310-manylinux_2_28_x86_64.whl \
  /tmp/torchaudio-2.11.0+cu130-cp310-cp310-manylinux_2_28_x86_64.whl \
  /tmp/triton-3.7.1-cp310-cp310-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl \
  --find-links /tmp/

# 3. 验证
docker exec comfyui /opt/environments/python/comfyui/bin/python -c \
  "import torch; print('torch:', torch.__version__); print('cuda:', torch.cuda.is_available())"

# 4. 装 ComfyUI 完整依赖
docker exec comfyui /opt/environments/python/comfyui/bin/pip install -r /opt/ComfyUI/requirements.txt

# 5. 验证 models 软链
docker exec comfyui ls -la /opt/ComfyUI/models
# 应指向 /workspace/models，否则重建软链

# 6. 启动 ComfyUI
docker exec comfyui supervisorctl start comfyui

# 7. 验证 H3 节点
curl -s http://localhost:8188/object_info | grep -i minimax | head -10
```

### 3.4 已知坑

- `--find-links /tmp/` 对 nvidia-cusparse/cusolver 可能不生效（版本通配符匹配问题），这两个包会从网络慢下，容忍即可
- `docker restart` 会清空 /tmp，wheel 文件需重新 cp
- 安装完成后**必须 `docker commit` 固化**，否则下次重建容器回退

---

## 四、ComfyUI 节点要求

ComfyUI **0.33.0+ 原生支持 H3**，无需额外 custom nodes。核心节点：

| 节点 | 用途 |
|---|---|
| `UNETLoader` | 加载 H3 主模型（diffusion_models/） |
| `LoraLoaderModelOnly` | 加载 Turbo LoRA（4步加速关键） |
| `MiniMaxH3SigmaShift` | 双时钟偏移（shift_video=12, shift_audio=3） |
| `CLIPLoader` | 加载 Qwen3-VL 文本编码器（type=minimax） |
| `CLIPTextEncode` | 文本编码 |
| `EmptyMiniMaxH3LatentAV` | T2V 空 latent（音视频联合） |
| `MiniMaxH3ImageToVideo` | I2V 图片转视频 |
| `KSamplerSelect` + `BasicScheduler` + `BasicGuider` + `SamplerCustomAdvanced` | 采样（高级采样链） |
| `VAELoader` + `VAEDecode` | 视频解码 |
| `VAELoader` + `VAEDecodeAudio` | 音频解码 |
| `CreateVideo` + `SaveVideo` | 合成 MP4（H.264+AAC） |

---

## 五、关键参数（照抄，避免踩坑）

### T2V 工作流核心参数

```
UNETLoader:      minimax_h3_fl2va_int8_convrot.safetensors / default
LoraLoader:      minimax_h3_fl2va_4step_lora.safetensors / strength=1.0
SigmaShift:      shift_video=12.0, shift_audio=3.0
CLIPLoader:      qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors / type=minimax
EmptyLatentAV:   640×640 × 73帧（~5秒 @24fps）
Scheduler:       simple / 4步 / denoise=1.0
Sampler:         euler
VAEDecode:       minimax_h3_video_vae_fp16
VAEDecodeAudio:  minimax_h3_audio_vae_fp32
CreateVideo:     fps=24 / 带音频
SaveVideo:       mp4 / h264
```

> **🔑 Turbo LoRA 是必带项，不是可选项**：4步采样把出片时间从 8 分钟压到 4 分钟，提速 50%+。

---

## 六、显存与性能

| 指标 | 实测值 |
|---|---|
| 生成时显存 | 12.8–14GB（独占全卡） |
| 宿主内存 | offload 常驻，峰值 ~20GB |
| 640×640·5s·4步 | ~4分钟/片（首次预热 8-9分钟） |
| 864×480·5s | 同像素量，耗时相近 |
| 1344×768（768p） | 3-5倍耗时，仅最终精选用 |

> **⚠️ 768p 是开源权重上限**，别期望本地 2K/4K。

---

## 七、避坑清单

| # | 坑 | 表现 | 解决 |
|---|---|---|---|
| 1 | TE-Speed 失真 | 文字乱码、手/嘴崩坏 | **禁用 TE-Speed**，只用 SageAttention |
| 2 | 忘挂 Turbo LoRA | 速度没翻倍 | 工作流必须加 `LoraLoaderModelOnly` |
| 3 | 模型文件名带 hash | 报"找不到模型" | 重命名去掉 `-<hash>` 后缀 |
| 4 | 首次生成慢 | 第1条 8-9分钟 | Sage/Triton JIT 预热，第2条起才是真实速度 |
| 5 | 同 seed 重跑秒完成 | 第2次 15s"完成" | 结果缓存命中，换 seed 或删缓存 |
| 6 | `POST /free` 异常 | 500 错误 | 切场景释放，或重启 ComfyUI |
| 7 | 宿主内存不足 | offload 失败/换页 | 32GB 内存起步，生成时关闭其他程序 |

---

## 八、工作流文件

本仓库包含可直接使用的工作流：

- `workflows/h3-t2v.json` — 文生视频（4步 euler，640×640，带音频）
- `workflows/h3-i2v.json` — 图生视频（需上传首帧图片）

用法：
```bash
# 提交工作流到 ComfyUI 并自动拉取输出
node scripts/run_comfy.js workflows/h3-t2v.json my_video
```

---

## 九、相关链接

- [Comfy-Org/MiniMax-H3（官方打包模型）](https://huggingface.co/Comfy-Org/MiniMax-H3)
- [joyfox/MiniMax-H3-Turbo（4步 LoRA）](https://huggingface.co/joyfox/MiniMax-H3-Turbo)
- [ComfyUI 官方文档](https://docs.comfy.org/)

---

*本指南基于 RTX 4060 Ti 16GB 实测沉淀。不同硬件请调整分辨率和步数。*
