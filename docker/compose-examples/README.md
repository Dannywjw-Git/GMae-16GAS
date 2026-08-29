# Docker Compose 部署模板

> ⚠️ **本目录为参考模板，尚未在全新环境完整验证。** ai-dock/comfyui 镜像的启动参数传递方式（`COMFYUI_ARGS` 环境变量）可能与实际不符，使用前请对照 [ai-dock 官方文档](https://github.com/ai-dock/comfyui) 调整。国内用户请配置镜像加速器。
>
> 适用于 16GB 显卡的本地 AI 生成环境。按需要选择单个服务或全套部署。

## 前置要求

- Docker + Docker Compose v2
- NVIDIA GPU + NVIDIA Container Toolkit
- 100GB+ 磁盘空间（模型文件）

---

## 1. ComfyUI（核心生成服务）

```yaml
# docker-compose.comfyui.yml
services:
  comfyui:
    image: ai-dock/comfyui:latest
    container_name: comfyui
    restart: unless-stopped
    ports:
      - "8188:8188"
    volumes:
      - ./models:/opt/ComfyUI/models
      - ./output:/opt/ComfyUI/output
      - ./custom_nodes:/opt/ComfyUI/custom_nodes
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
      - COMFYUI_ARGS=--reserve-vram 2.5
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8188/system_stats"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
```

**启动：**
```bash
docker compose -f docker-compose.comfyui.yml up -d
```

**关键参数：**
- `--reserve-vram 2.5`：为 OS 预留 2.5GB 显存，防止打满死机（必带）
- 模型目录挂载到 `./models`，按 [模型清单](../../README.md#-模型清单) 下载

---

## 2. Open WebUI（对话界面）

```yaml
# docker-compose.owui.yml
services:
  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    container_name: open-webui
    restart: unless-stopped
    ports:
      - "3000:8080"
    volumes:
      - ./owui-data:/app/backend/data
    environment:
      - OLLAMA_BASE_URL=http://host.docker.internal:11434
      - ENABLE_SIGNUP=false
      - DEFAULT_MODELS=qwen3.5:9b
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

> 国内镜像源：`registry.cn-hangzhou.aliyuncs.com/xxx` 或配置 Docker 镜像加速。

---

## 3. 全套部署（ComfyUI + OWUI + SearXNG + Caddy）

```yaml
# docker-compose.full.yml
services:
  comfyui:
    # 见上方 comfyui 配置
    # ...

  open-webui:
    # 见上方 owui 配置
    # ...

  searxng:
    image: searxng/searxng:latest
    container_name: searxng
    restart: unless-stopped
    ports:
      - "8888:8080"
    volumes:
      - ./searxng:/etc/searxng
    environment:
      - BASE_URL=http://localhost:8888/
      - INSTANCE_NAME=searxng

  caddy:
    image: caddy:2
    container_name: caddy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy-data:/data
      - caddy-config:/config

volumes:
  caddy-data:
  caddy-config:
```

---

## 4. Caddy 反向代理示例

```Caddyfile
# Caddyfile
ai.localhost {
    handle_path /comfyui/* {
        reverse_proxy comfyui:8188
    }
    handle_path /owui/* {
        reverse_proxy open-webui:8080
    }
    handle {
        respond "AI Hub" 200
    }
}
```

---

## 常用命令

```bash
# 启动
docker compose up -d

# 查看日志
docker compose logs -f comfyui

# 重启
docker compose restart comfyui

# 进入容器
docker exec -it comfyui bash

# 停止（保留数据）
docker compose down

# 停止并删除数据（危险）
docker compose down -v
```

---

## 注意事项

1. **显存互斥**：ComfyUI 跑大模型时（Flux/H3/Music3），不要同时运行其他 GPU 服务
2. **模型下载**：首次启动后，按模型清单下载到挂载的 models 目录
3. **国内网络**：Docker 镜像拉取慢的话，配置镜像加速器或使用国内源
4. **权限问题**：如果容器内输出目录权限报错，执行 `chown -R 1000:1000 ./output`
