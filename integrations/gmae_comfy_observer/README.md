# GMae ComfyUI 驻留观察扩展

可选、只读的 ComfyUI custom-node 包，不提供生成节点，不改变模型参数或显存分配。目前仅识别标准 SDXL checkpoint `sd_xl_base_1.0.safetensors` 的 UNet、CLIP、VAE 对象。

扩展包装标准 checkpoint loader，保留原返回值和异常，使用弱引用记录实际模型对象的加载来源及文件元数据。观察错误明确计数，不影响原生成返回，但不能报告完整可信驻留。不根据历史模型名补齐未知身份；不持有额外模型权重引用。

## 安装与查询

已配置并运行的受管 Docker 容器 `comfyui`：

```powershell
.venv\Scripts\python.exe scripts\install_comfy_observer.py --output observer-installation.json
```

脚本取得 GMae 正式 GPU 0 所有权，检查账本和其他工作，检查已存在扩展的源码一致性。不同源码不会覆盖。先保存本地私有容器快照，再经现有持久协调器重启；不使用 compose 重建。大型快照可能较慢。快照失败不执行重启，保留失败记录；不要仅因等待超时重复重启。安装是明确执行的操作，不在 GMae 启动时自动进行。

普通原生 ComfyUI 部署可把本目录的 `observer.py` 和 `__init__.py` 放入其 custom_nodes/gmae_comfy_observer；按照部署自身流程备份、确认无任务后激活。已经存在且不同的扩展需自行审核，不能盲目覆盖。扩展需要上游已有的 aiohttp/ComfyUI/Python 3.10+，不下载或添加模型。

后端 `GET /gmae/residency?request_id=<canonical UUID>` 返回不可缓存快照。GMae 提供按需 `GET /api/coordinator/residency`，每次发送独立请求身份并验证响应；接口缺失、超时或矛盾数据返回明确不可用，不改变正式准入策略。

## 证据边界

快照包括后端启动实例、加载 epoch、观察失败数、队列前后读数、组件类型、加载时文件 dev/ino/size/mtime/ctime、路径摘要及真实 loaded_size/model_size。只支持 CUDA 0。完整标志要求三个已记录组件均完全驻留、未打补丁、来源文件未变，且无活动或观察失败。部分卸载、未知对象、文件改变和缺失组件明确不能报告完整状态。

`path_sha256` 是路径身份摘要，**不是文件内容摘要**。`artifact_digest_verified=false`；调用方仍必须核验实际文件 SHA-256、环境身份和测量 Profile。元数据假设普通不可变模型部署，不提供对抗恶意保持文件元数据的篡改防御或对权重内容的远程认证。

`warm_admission_enabled=false` 始终保留。观察接口不是 warm 准入、OOM 保证或后端恰好执行一次。队列前后检查不能隔离外部客户端；正式受管入口的所有权机制仍必需。单次完整观察不证明未来驻留状态或性能收益。

扩展源码使用仓库 [MIT 许可证](../../LICENSE)。上游 ComfyUI、运行环境和模型保留各自许可证。私有部署快照只保存在本机，不能作为公共发行镜像直接上传。
