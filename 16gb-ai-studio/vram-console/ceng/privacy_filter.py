"""
GMae v0.3.1 C-Eng — 隐私过滤器

调用云端 API 前过滤敏感信息。
三级：🟢公开级（可发）/ 🟡敏感级（可选）/ 🔴禁止级（永不发）
"""
import json


class PrivacyFilter:
    def __init__(self, send_prompts_to_cloud: bool = False):
        self.send_prompts = send_prompts_to_cloud

    def filter_for_cloud(self, state: dict, user_input: str) -> dict:
        """
        发送到云端前的隐私过滤。

        🟢 保留：系统资源状态（显存、场景、模型名、队列深度）
        🟡 处理：用户创作内容（默认不发，只发任务类型分类）
        🔴 过滤：文件路径、API Key、生成内容、完整进程列表
        """
        filtered = {}

        # 🟢 系统资源状态
        vram = state.get("vram", {})
        filtered["vram"] = {
            "total_gb": vram.get("total_gb"),
            "used_gb": vram.get("used_gb"),
            "free_gb": vram.get("free_gb"),
        }
        filtered["scene"] = state.get("scene")
        filtered["danger_level"] = state.get("danger_level")
        filtered["queue_depth"] = state.get("queue_depth", 0)

        # 已加载模型名（不含路径）
        filtered["loaded_models"] = [
            {"name": m.get("name"), "size_gb": m.get("size_gb")}
            for m in state.get("loaded_models", [])
        ]

        # 🟡 用户输入处理
        if self.send_prompts:
            filtered["user_request"] = user_input
        else:
            filtered["user_request_type"] = self._classify_task_type(user_input)

        # 🔴 绝不发送的字段（显式过滤）
        for key in ["file_paths", "api_keys", "generated_content",
                     "full_process_list", "desktop_processes", "container_details"]:
            filtered.pop(key, None)

        return filtered

    def _classify_task_type(self, text: str) -> str:
        """不发具体内容，只做任务类型分类（关键词匹配）。"""
        text_lower = text.lower()
        if any(k in text_lower for k in ["图", "image", "picture", "画", "photo"]):
            if any(k in text_lower for k in ["视频", "video", "动"]):
                return "video_generation"
            return "image_generation"
        if any(k in text_lower for k in ["音乐", "music", "音频", "audio", "歌", "sound"]):
            return "music_generation"
        if any(k in text_lower for k in ["对话", "chat", "问", "聊", "翻译", "写"]):
            return "dialogue"
        if any(k in text_lower for k in ["显存", "vram", "状态", "status", "释放", "free"]):
            return "system_query"
        if any(k in text_lower for k in ["模型", "model", "加载", "load", "切换", "switch"]):
            return "model_management"
        return "general_request"
