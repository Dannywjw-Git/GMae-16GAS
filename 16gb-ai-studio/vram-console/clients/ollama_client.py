#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae Ollama API 客户端
- 封装所有 Ollama HTTP API 调用
- 提供模型列表、已加载模型、停止模型等接口
- 所有调用统一超时和错误处理
"""
import json
import urllib.request
import hashlib
import re
import threading
from core.logger import log_error

OLLAMA_BASE = "http://127.0.0.1:11434"
_blob_cache = {}
_blob_lock = threading.Lock()


def _get(path: str, timeout: int = 5) -> tuple:
    """发送 GET 请求到 Ollama API。

    Args:
        path: API 路径（如 /api/ps）
        timeout: 超时秒数

    Returns:
        tuple: (ok: bool, data: dict, error: str)
    """
    try:
        with urllib.request.urlopen(OLLAMA_BASE + path, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return True, data, ""
    except Exception as e:
        return False, {}, str(e)


def list_loaded_models() -> dict:
    """查询 Ollama 已加载模型（/api/ps）。

    Returns:
        dict: {"ok": bool, "models": [{"name": str, "size_gb": float, "until": str}]}
    """
    ok, d, err = _get("/api/ps", timeout=3)
    if not ok:
        return {"ok": False, "models": [], "error": "offline/timeout"}
    models = [{
        "name": m.get("name") or m.get("model", ""),
        "model": m.get("model") or m.get("name", ""),
        # Keep the legacy field name, but use GPU-resident GiB, not CPU+GPU size.
        "size_gb": m.get("size_vram", 0) / (1024 ** 3),
        "total_size_gb": m.get("size", 0) / (1024 ** 3),
        "vram_known": "size_vram" in m,
        "until": (m.get("expires_at") or "")[11:19],
    } for m in d.get("models", [])]
    return {"ok": True, "models": models}


def list_installed_models() -> set:
    """获取已安装的 Ollama 模型名称集合（/api/tags）。

    Returns:
        set: 模型名称集合，失败返回空 set
    """
    ok, d, err = _get("/api/tags", timeout=5)
    if not ok:
        return set()
    return {m.get("name", "") for m in d.get("models", [])}


def is_online() -> bool:
    """检查 Ollama 服务是否在线。

    Returns:
        bool: 在线返回 True
    """
    ok, _, _ = _get("/api/tags", timeout=3)
    return ok


def live_profile_environment(model):
    """Fresh deployment/file metadata with bounded content cache, not name trust."""
    from core.config import OLLAMA_CONTAINER
    from core.utils import run_args
    from clients.docker_client import _get_docker_cmd
    from core.ollama_profile import environment_from_identity
    def read(args,timeout=10):
        rc,output=run_args(args,timeout)
        if rc: raise ValueError('live identity unavailable')
        return output.strip()
    request=urllib.request.Request(OLLAMA_BASE+'/api/show',data=json.dumps({'model':model}).encode(),
                                   headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=10) as response: show=json.load(response)
    matches=re.findall(r'^FROM\s+"?(/[^"\s]+/sha256-[0-9a-f]{64})"?\s*$',show.get('modelfile',''),re.MULTILINE)
    if len(matches)!=1: raise ValueError('blob identity unavailable')
    path=matches[0];docker=_get_docker_cmd()
    instance=read([docker,'inspect','--format','{{.Id}}',OLLAMA_CONTAINER])
    metadata=read([docker,'exec',OLLAMA_CONTAINER,'stat','-c','%d:%i:%s:%Y:%Z',path])
    key=(instance,path,metadata)
    with _blob_lock:
        digest=_blob_cache.get(key)
        if digest is None:
            digest=read([docker,'exec',OLLAMA_CONTAINER,'sha256sum',path],120).split()[0]
            if digest!=path.rsplit('sha256-',1)[1]: raise ValueError('blob content mismatch')
            _blob_cache.clear();_blob_cache[key]=digest
    if (read([docker,'exec',OLLAMA_CONTAINER,'stat','-c','%d:%i:%s:%Y:%Z',path])!=metadata
            or read([docker,'inspect','--format','{{.Id}}',OLLAMA_CONTAINER])!=instance):
        raise ValueError('deployment changed during identity check')
    ok,tags,_=_get('/api/tags');ok_version,version,_=_get('/api/version')
    if not ok or not ok_version: raise ValueError('backend identity unavailable')
    manifest=next(item['digest'] for item in tags['models'] if item['name']==model)
    if read([docker,'exec',OLLAMA_CONTAINER,'ollama','--version'])!='ollama version is '+version['version']:
        raise ValueError('container/API version mismatch')
    values=read(['nvidia-smi','--id=0','--query-gpu=name,uuid,driver_version,memory.total',
                 '--format=csv,noheader,nounits']).split(',')
    name,uuid,driver,total=(part.strip() for part in values)
    artifact=dict(container_id=instance,blob_sha256=digest,blob_stat=metadata,
        blob_path_sha256=hashlib.sha256(path.encode()).hexdigest(),model_details=show['details'],
        model_configuration_sha256=hashlib.sha256(json.dumps(show,sort_keys=True,separators=(',',':')).encode()).hexdigest())
    return environment_from_identity(dict(name=name,driver=driver,
        uuid_sha256=hashlib.sha256(uuid.encode()).hexdigest()),int(total),artifact,version['version'],manifest)
