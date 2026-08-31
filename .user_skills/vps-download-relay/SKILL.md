---
name: vps-download-relay
description: 通过海外 VPS 中转下载国内难以直接拉取的大文件（Docker 镜像、PyTorch wheel、AI 模型等）。当遇到 docker pull 超时/中断、pip install 大包极慢、ghcr.io/Docker Hub 无法访问、或需要下载数 GB 级文件时使用。支持 HTTP 文件中转和 Docker Registry 镜像中转两种模式，包含文件完整性验证流程，避免下载损坏文件。
---

# VPS 中转下载

通过海外 VPS 作为跳板，下载国内网络难以直接获取的大文件，再传回本地。

## 何时使用

- `docker pull` 反复超时、中断、速度极慢（<100KB/s）
- `pip install` 大 wheel 包（torch、tensorflow 等）数小时未完成
- ghcr.io、Docker Hub、HuggingFace 等国外源无法访问或被限流
- 需要下载 >1GB 的文件（模型、镜像、安装包）
- 国内镜像源找不到所需版本

## 两种模式

### 模式 A：HTTP 文件中转（适合 wheel、模型、安装包）

```
本地 → VPS(下载源文件) → VPS(HTTP服务) → 本地(aria2多线程下载) → 验证完整性
```

**步骤：**

1. **VPS 上下载文件**
   ```bash
   ssh root@<VPS_IP> "cd /root/downloads && wget -c '<URL>' -O <filename>"
   # 或用 aria2 多线程
   ssh root@<VPS_IP> "cd /root/downloads && aria2c -x 16 -s 16 '<URL>'"
   ```

2. **VPS 上启动 HTTP 服务**
   ```bash
   # 临时用 python（简单但性能一般，适合 <2GB）
   ssh root@<VPS_IP> "cd /root/downloads && nohup python3 -m http.server 8080 > /tmp/http.log 2>&1 &"
   
   # 大文件推荐 nginx（性能好，支持多线程）
   ssh root@<VPS_IP> "apt install -y nginx && systemctl start nginx && cp <file> /var/www/html/"
   ```

3. **开放防火墙端口**
   ```bash
   ssh root@<VPS_IP> "ufw allow 8080/tcp && ufw reload"
   ```

4. **本地用 aria2 多线程下载**
   ```powershell
   aria2c -x 16 -s 16 --file-allocation=none "http://<VPS_IP>:8080/<filename>" -d "<本地目录>"
   ```
   ⚠️ **必须加 `--file-allocation=none`**，否则 aria2 会预分配磁盘空间，文件显示完整大小但实际未下载完。

5. **验证文件完整性（必须！）**
   ```powershell
   # zip/whl/jar 等
   unzip -t <filename>
   
   # tar/tar.gz
   tar -tf <filename> > $null
   
   # 对比大小（仅作参考，不能作为唯一依据）
   # 对比 VPS 上的文件大小和本地文件大小
   ```

6. **清理 VPS 临时文件**（可选，VPS 空间紧张时）
   ```bash
   ssh root@<VPS_IP> "rm -f /root/downloads/<filename> && pkill -f 'http.server 8080'"
   ```

### 模式 B：Docker Registry 中转（适合 Docker 镜像）

```
本地 → VPS(docker pull) → VPS(docker push到本地Registry) → 本地(docker pull从VPS Registry)
```

**步骤：**

1. **VPS 上启动 Registry**
   ```bash
   ssh root@<VPS_IP> "docker run -d -p 5000:5000 --restart=always --name registry registry:2"
   ssh root@<VPS_IP> "ufw allow 5000/tcp && ufw reload"
   ```

2. **VPS 上拉取并推送镜像**
   ```bash
   ssh root@<VPS_IP> "docker pull <原镜像名>:<tag>"
   ssh root@<VPS_IP> "docker tag <原镜像名>:<tag> localhost:5000/<镜像名>:<tag>"
   ssh root@<VPS_IP> "docker push localhost:5000/<镜像名>:<tag>"
   ```

3. **本地配置 insecure-registries**
   - 编辑 `%USERPROFILE%\.docker\daemon.json`
   - 添加：`"insecure-registries": ["<VPS_IP>:5000"]`
   - 重启 Docker Desktop

4. **本地从 VPS Registry 拉取**
   ```powershell
   docker pull <VPS_IP>:5000/<镜像名>:<tag>
   docker tag <VPS_IP>:5000/<镜像名>:<tag> <原镜像名>:<tag>
   ```

## 关键注意事项

### ⚠️ 文件大小 ≠ 下载完成

这是最常见的错误。下载工具（aria2、wget、curl）可能会：
- **预分配磁盘空间**：文件显示完整大小但实际只下载了一部分
- **断点续传失败**：显示下载完成但文件损坏

**正确判断下载完成的依据：**
1. 下载工具明确输出 `Download complete` / `(OK)` / `100%`
2. 下载进程正常退出（不是被 kill 或超时）
3. **下载后必须验证完整性**（见上方步骤 5）

### ⚠️ 必须验证完整性

| 文件类型 | 验证命令 |
|---------|---------|
| .whl / .zip / .jar | `unzip -t <file>` |
| .tar / .tar.gz | `tar -tf <file> > $null` |
| .iso / .img | 对比官方 SHA256/MD5 |
| Docker 镜像 | `docker inspect <image>` 看大小是否匹配 |
| 模型文件 | 对比官方文件大小 + 尝试加载 |

### ⚠️ Python HTTP 服务性能差

`python3 -m http.server` 是单线程的，即使 aria2 开 16 线程也无法有效并行。
- **<2GB 文件**：可以用，简单方便
- **>2GB 文件**：推荐 nginx 或 `aria2c --enable-rpc` 做种

### ⚠️ 防火墙

VPS 通常默认只开 22 端口。启动 HTTP/Registry 服务后必须开放对应端口：
```bash
ufw allow 8080/tcp  # HTTP
ufw allow 5000/tcp  # Docker Registry
ufw reload
```

## 常用 VPS 信息

> 具体 VPS 信息以项目实际配置为准，以下为示例格式。

| VPS | IP | 用途 | 磁盘 |
|-----|-----|------|------|
| 日本东京 | <IP> | Exit Node + Registry + 文件中转 | 50G |
| 香港 | <IP> | Registry Mirror + CMI 优化线路 | 20G |

## 故障排查

**问题：本地从 VPS 下载速度慢**
- 检查 VPS 带宽限制
- 换用 nginx 替代 python HTTP 服务
- 检查是否被 VPS 服务商限流

**问题：下载的文件损坏**
- 确认下载工具明确提示完成（不是预分配空间）
- 用 `unzip -t` / `tar -tf` 验证
- 删除损坏文件重新下载

**问题：Docker pull from VPS Registry 失败**
- 确认本地 `daemon.json` 配置了 `insecure-registries`
- 确认 VPS 防火墙开放了 5000 端口
- 确认 VPS 上 Registry 容器正在运行

**问题：VPS 磁盘满**
- 下载前检查 `df -h`
- 大文件下载后及时清理
- Docker 镜像用 `docker system prune` 清理
