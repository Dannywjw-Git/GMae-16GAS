"""修复 auto_protect：critical 级别不保留对话模型，actions 为空时强制 L4"""
import io

path = r"D:\Users\Danny\Documents\GMae_Amanda\16gb-ai-studio\vram-console\engine\qos.py"

with open(path, "rb") as f:
    raw = f.read()
has_bom = raw.startswith(b"\xef\xbb\xbf")
content = raw.decode("utf-8-sig")
original_newline = "\r\n" if "\r\n" in content else "\n"
content_norm = content.replace("\r\n", "\n")

# 修复1：critical 级别不保留对话模型
old1 = '''            keep = loaded[-1].get("model") if (scene == "dialogue" and loaded) else None'''
new1 = '''            # critical 级别（<1GB，即将死机）不保留任何模型，强制全部卸载
            keep = loaded[-1].get("model") if (scene == "dialogue" and loaded and level != "critical") else None'''

if old1 in content_norm:
    content_norm = content_norm.replace(old1, new1)
    print("Fix 1 applied: critical level does not keep dialogue model")
else:
    print("ERROR: Fix 1 target not found")

# 修复2：actions 为空但 level==critical 时，强制 L4 停止容器
old2 = '''    if not actions:
        return None
    st["last_trigger_ts"] = now'''
new2 = '''    # critical 级别但软释放无动作（如单模型dialogue场景）：强制 L4 停止容器
    if not actions and level == "critical":
        try:
            from services.docker import container_stop
            for cname in ("ollama", "comfyui", "fooocus"):
                if cname in names:
                    try:
                        r = container_stop(cname)
                        if r.get("ok"):
                            actions.append({"level": "L4", "action": f"强制停止 {cname} 容器（critical 无软释放动作）"})
                    except Exception as e:
                        log_error("auto_protect_l4_fallback_error", error=str(e), container=cname)
            time.sleep(3)
        except Exception as e:
            log_error("auto_protect_l4_fallback_failed", error=str(e))
    if not actions:
        return None
    st["last_trigger_ts"] = now'''

if old2 in content_norm:
    content_norm = content_norm.replace(old2, new2)
    print("Fix 2 applied: critical fallback to L4 when no soft actions")
else:
    print("ERROR: Fix 2 target not found")

# 写回
content_out = content_norm.replace("\n", original_newline)
out = content_out.encode("utf-8-sig") if has_bom else content_out.encode("utf-8")
with open(path, "wb") as f:
    f.write(out)
print("Done")
