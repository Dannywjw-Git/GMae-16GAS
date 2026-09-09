"""修复 qos_check：stale 数据时仍触发 auto_protect，增加日志"""
import io

path = r"D:\Users\Danny\Documents\GMae_Amanda\16gb-ai-studio\vram-console\engine\qos.py"

with open(path, "rb") as f:
    raw = f.read()
has_bom = raw.startswith(b"\xef\xbb\xbf")
content = raw.decode("utf-8-sig")
original_newline = "\r\n" if "\r\n" in content else "\n"
content_norm = content.replace("\r\n", "\n")

old_func = '''def qos_check():
    """QoS 检查：按显存水位分级，危急时触发自动防死机。"""
    from services.helper import _auto_protect_cfg
    if not QOS_CFG["enabled"]:
        return {"level": "disabled"}
    gpu = gpu_status()
    if not gpu.get("ok"):
        return {"level": "unknown", "error": "nvidia-smi unavailable"}
    free_mb = gpu.get("free_mb", 99999)'''

new_func = '''def qos_check():
    """QoS 检查：按显存水位分级，危急时触发自动防死机。"""
    from services.helper import _auto_protect_cfg
    if not QOS_CFG["enabled"]:
        return {"level": "disabled"}
    gpu = gpu_status()
    if not gpu.get("ok"):
        # nvidia-smi 完全不可用且无缓存：保守触发 auto_protect（安全优先）
        log_error("qos_check_gpu_unavailable", message="nvidia-smi failed, no stale data")
        return {"level": "unknown", "error": "nvidia-smi unavailable"}
    if gpu.get("stale"):
        log_error("qos_check_using_stale", stale_age_s=gpu.get("stale_age_s"),
                  free_mb=gpu.get("free_mb"), message="using stale GPU data for safety")
    free_mb = gpu.get("free_mb", 99999)'''

if old_func in content_norm:
    content_norm = content_norm.replace(old_func, new_func)
    content_out = content_norm.replace("\n", original_newline)
    out = content_out.encode("utf-8-sig") if has_bom else content_out.encode("utf-8")
    with open(path, "wb") as f:
        f.write(out)
    print("OK: qos_check patched with stale handling")
else:
    print("ERROR: old func not found")
    idx = content_norm.find("def qos_check")
    print(repr(content_norm[idx:idx+300]))
