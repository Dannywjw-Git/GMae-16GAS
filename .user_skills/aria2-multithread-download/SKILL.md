---
name: aria2-multithread-download
description: Aria2 多线程下载（智能路由版）。自动判断国内/国外源：HuggingFace 模型自动走 hf-mirror.com，国内厂商走 ModelScope，国外源回退 VPS 中转。所有 HTTP/HTTPS/FTP 大文件下载（模型权重/安装包/数据集）必须使用本 Skill，支持断点续传和完整性验证。
---

# Aria2 多线程下载 Skill（智能路由版）

> 所有 HTTP/HTTPS/FTP/SFTP 下载任务必须使用本 Skill。**自动判断国内/国外源，国内模型走镜像直连，国外源走 VPS 中转。**

## 何时使用

- ✅ 下载模型权重（GGUF/safetensors/pth 等）
- ✅ 下载大文件安装包（>100MB）
- ✅ 下载数据集、备份文件
- ✅ 任何需要断点续传的下载
- ❌ 小文件（<100MB）可用 curl，但优先用本工具统一管理

---

## 🧭 智能路由决策（核心）

下载前**必须**先判断走哪条路线，禁止盲目走 VPS。

### 路线 A：国内镜像直连（默认优先，速度快 10-50MB/s）

**满足以下任一条件，直接国内下载，不走 VPS：**

1. **HuggingFace 任意模型** → 自动替换域名 `huggingface.co` → `hf-mirror.com`
   - 例：`https://huggingface.co/Org/Repo/resolve/main/file.safetensors`
   - 改为：`https://hf-mirror.com/Org/Repo/resolve/main/file.safetensors`
   - hf-mirror.com 同步所有 HuggingFace 公开模型，国内直连

2. **国内厂商模型**（ModelScope / 魔搭）
   - 阿里 Wan-AI / Wan-Video（Wan2.1、Wan2.2 等）
   - 腾讯 Tencent-Hunyuan（HunyuanVideo 等）
   - 智谱 THUDM（CogVideoX 等）
   - 字节 ByteDance / bytedance（GRN 等）
   - MiniMax、百度、小米等国内厂商
   - 下载链接格式：`https://modelscope.cn/models/<repo>/resolve/master/<file>`

3. **国内可访问的源**
   - GitHub release（先试 ghproxy 镜像：`https://ghproxy.com/<url>`）
   - PyPI 包（用国内镜像：`pip install -i https://pypi.tuna.tsinghua.edu.cn/simple`）

### 路线 B：VPS 中转下载（国内直连失败/无镜像时）

**满足以下条件，走 VPS 中转：**

1. **Docker 镜像**（Docker Hub / ghcr.io / nvcr.io）
   - docker pull 超时、速度 <100KB/s
   - 用 VPS Registry 中转模式（见 vps-download-relay Skill）

2. **国外厂商模型且 hf-mirror.com 无同步**
   - Lightricks / LTX（部分非 HF 源）
   - NVIDIA 官网模型
   - 其他非 HuggingFace 托管的国外源

3. **hf-mirror.com 下载失败或速度极慢（<1MB/s 持续 1 分钟）**
   - 回退到 VPS 中转

4. **pip 大 wheel 包**（torch、tensorflow 等，国内镜像也慢时）

### 路由判断流程

```
收到下载 URL
    │
    ├─ 是 HuggingFace (huggingface.co)？
    │   └─ 是 → 替换为 hf-mirror.com → aria2 直连
    │
    ├─ 是 ModelScope (modelscope.cn)？
    │   └─ 是 → aria2 直连
    │
    ├─ 是 Docker 镜像？
    │   └─ 是 → VPS Registry 中转
    │
    ├─ 是 GitHub release 大文件？
    │   ├─ 先试 ghproxy 镜像直连
    │   └─ 失败 → VPS HTTP 中转
    │
    └─ 其他国外源？
        ├─ 先试 aria2 直连 1 分钟
        ├─ 速度 >1MB/s → 继续直连
        └─ 速度 <1MB/s 或失败 → VPS HTTP 中转
```

---

## 工具路径

```
C:\Users\Danny\AppData\Local\Microsoft\WinGet\Packages\aria2.aria2_Microsoft.Winget.Source_8wekyb3d8bbwe\aria2-1.37.0-win-64bit-build1\aria2c.exe
```

VPS 信息：`ai-registry-jp`（167.179.66.179，东京，52G 磁盘）

---

## 标准用法

### 1. HuggingFace 模型（自动走 hf-mirror 国内镜像）

```powershell
$aria2 = "C:\Users\Danny\AppData\Local\Microsoft\WinGet\Packages\aria2.aria2_Microsoft.Winget.Source_8wekyb3d8bbwe\aria2-1.37.0-win-64bit-build1\aria2c.exe"

# 原始 HF URL 自动替换域名
$hfUrl = "https://huggingface.co/Org/Repo/resolve/main/model.safetensors"
$mirrorUrl = $hfUrl -replace "huggingface.co", "hf-mirror.com"

& $aria2 -c -x 16 -s 16 -k 1M --console-log-level=warn -d "D:\models" -o "model.safetensors" $mirrorUrl
```

### 2. ModelScope 模型（国内直连）

```powershell
& $aria2 -c -x 16 -s 16 -k 1M --console-log-level=warn `
  -d "D:\models" -o "model.safetensors" `
  "https://modelscope.cn/models/Wan-AI/Wan2.2-TI2V-5B/resolve/master/model.safetensors"
```

### 3. VPS HTTP 中转（国外源回退）

详见 `vps-download-relay` Skill。简要流程：
1. VPS 上 wget/aria2 下载源文件
2. VPS 上 nginx 或 python http.server 提供下载
3. 本地 aria2 从 VPS 多线程下载
4. 验证完整性

### 4. 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-c` | 断点续传 | 必加 |
| `-x 16` | 单服务器最大连接数 16 | 16 |
| `-s 16` | 总连接数 16 | 16 |
| `-k 1M` | 分片大小 1MB | 1M |
| `-d` | 下载目录 | 当前目录 |
| `-o` | 输出文件名 | URL 文件名 |
| `--console-log-level=warn` | 只输出警告和错误 | warn |
| `--max-tries=5` | 最大重试次数 | 5 |
| `--retry-wait=3` | 重试等待秒数 | 3 |

### 5. 后台运行（大文件下载）

在 PowerShell 中使用 `run_in_background: true` 执行，避免阻塞会话。

---

## 下载进度检查

```powershell
# 检查文件大小
Get-Item "D:\models\model.gguf" | Select-Object Name, @{N='SizeGB';E={[math]::Round($_.Length/1GB,2)}}

# 检查 aria2c 进程是否还在运行
Get-Process aria2c -ErrorAction SilentlyContinue | Select-Object Id, CPU

# 检查临时文件（.aria2 存在表示未完成）
Get-ChildItem "D:\models\*.aria2" -ErrorAction SilentlyContinue
```

---

## 国内镜像源汇总

| 源 | 用途 | 前缀/替换规则 |
|----|------|--------------|
| hf-mirror.com | HuggingFace 所有模型 | `huggingface.co` → `hf-mirror.com` |
| modelscope.cn | 阿里魔搭（国内模型首选） | `https://modelscope.cn/models/<repo>/resolve/master/<file>` |
| ghproxy.com | GitHub release/源码 | `https://ghproxy.com/<原始GitHub URL>` |
| pypi.tuna.tsinghua.edu.cn | PyPI 包 | `pip install -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| docker.m.daocloud.io | Docker Hub 镜像 | `docker pull docker.m.daocloud.io/<image>` |

---

## 注意事项

1. **文件大小 ≠ 下载完成**：aria2 会预分配磁盘空间，必须确认 `.aria2` 临时文件已消失且进程退出，才算真正完成
2. **下载后验证**：大文件下载完成后建议用 `Get-FileHash` 校验 MD5/SHA256（如果源提供了校验值）
3. **磁盘空间**：下载前检查目标磁盘剩余空间，确保至少有文件大小的 1.2 倍余量
4. **VPS 中转必须验证完整性**：VPS 下载后传回本地的文件，必须用 `unzip -t` / `tar -tf` / 对比大小等方式验证
5. **禁止盲目走 VPS**：国内模型（Wan、Hunyuan、CogVideoX 等）必须先试国内镜像，速度快且省 VPS 流量

---

## 故障排查

| 问题 | 解决方案 |
|------|---------|
| hf-mirror.com 404 | 该模型可能未同步，回退到 VPS 中转 |
| 下载速度慢 | 确认是否用了国内镜像；增加 `-x 16 -s 16`；国外源走 VPS |
| 连接被重置 | 加 `--max-tries=10 --retry-wait=5`，断点续传会自动恢复 |
| 文件名乱码 | 用 `-o` 显式指定输出文件名 |
| 磁盘空间不足 | aria2 会自动暂停，清理空间后重新运行相同命令即可续传 |
| SSL 证书错误 | 加 `--check-certificate=false`（仅可信源使用） |
| VPS 磁盘满 | 下载前 `df -h` 检查，大文件下载后及时清理 |

---

*创建日期：2026-08-26*
*更新日期：2026-08-27（v2.0 加入智能路由：国内镜像直连优先，VPS 中转回退）*
*版本：v2.0*
*适用范围：所有会话的 HTTP/HTTPS/FTP 下载任务*
