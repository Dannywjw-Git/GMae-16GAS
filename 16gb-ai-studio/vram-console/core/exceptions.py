#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 自定义异常类体系
- 业务错误 vs 系统错误分类
- 支持错误链传播（raise ... from）
- 所有模块统一使用本异常体系
"""


class GMaeError(Exception):
    """GMae 基础异常类，所有自定义异常的基类。"""
    def __init__(self, message: str = "", detail: dict = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}

    def to_dict(self) -> dict:
        return {"error": self.__class__.__name__, "message": self.message, "detail": self.detail}


# ============================================================
# 业务错误（用户操作导致，可恢复）
# ============================================================

class BusinessError(GMaeError):
    """业务逻辑错误基类。"""
    pass


class ModelNotFoundError(BusinessError):
    """模型未找到或未登记。"""
    pass


class ModelNotLoadedError(BusinessError):
    """模型未加载。"""
    pass


class InsufficientVRAMError(BusinessError):
    """显存不足，无法执行操作。"""
    pass


class AdmissionDeniedError(BusinessError):
    """准入闸门拒绝操作。"""
    pass


class InvalidActionError(BusinessError):
    """无效的操作类型或参数。"""
    pass


class SceneSwitchError(BusinessError):
    """场景切换失败。"""
    pass


class QueueFullError(BusinessError):
    """任务队列已满。"""
    pass


class TaskNotFoundError(BusinessError):
    """任务不存在。"""
    pass


class AuthenticationError(BusinessError):
    """认证失败。"""
    pass


class PermissionDeniedError(BusinessError):
    """权限不足。"""
    pass


# ============================================================
# 系统错误（基础设施问题，需人工介入）
# ============================================================

class SystemError(GMaeError):
    """系统级错误基类。"""
    pass


class ServiceUnavailableError(SystemError):
    """外部服务不可用（Ollama/ComfyUI/Docker 等）。"""
    pass


class GPUDetectError(SystemError):
    """GPU 检测失败。"""
    pass


class DockerError(SystemError):
    """Docker 操作失败。"""
    pass


class ConfigError(SystemError):
    """配置文件错误。"""
    pass


class RegistryError(SystemError):
    """模型注册表错误。"""
    pass


class HardwareProbeError(SystemError):
    """硬件探测失败。"""
    pass


# ============================================================
# 工具函数
# ============================================================

def wrap_error(message: str, original_error: Exception, error_class: type = GMaeError) -> GMaeError:
    """包装原始异常，保留错误链。

    Args:
        message: 新异常的描述信息
        original_error: 原始异常
        error_class: 要创建的异常类

    Returns:
        GMaeError 子类实例

    Usage:
        try:
            ...
        except Exception as e:
            raise wrap_error("操作失败", e, ServiceUnavailableError) from e
    """
    return error_class(message, detail={"original": str(original_error), "original_type": type(original_error).__name__})
