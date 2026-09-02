#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
进程调用统一封装 Client（P1-3 外部服务封装）

为所有 subprocess 调用提供统一接口，包含：
- 超时保护（默认30秒）
- 统一错误处理（返回 Result 对象，不抛异常）
- 日志记录（自动记录命令、耗时、返回码）
- 编码处理（自动处理 UTF-8/GBK 编码）
- 可 mock（依赖注入，不硬编码全局状态）

使用方式：
    from clients.process_client import process_client, ProcessResult

    # 简单调用
    result = process_client.run(["docker", "ps", "--format", "{{.Names}}"])
    if result.ok:
        print(result.stdout)
    else:
        print(f"失败: {result.error}")

    # 带超时和输入
    result = process_client.run(["nvidia-smi"], timeout=10, input_data="")
"""
import subprocess
import threading
import time
from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass, field


@dataclass
class ProcessResult:
    """进程执行结果（统一返回对象）"""
    ok: bool = False
    returncode: int = -1
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None
    duration_ms: float = 0.0
    command: List[str] = field(default_factory=list)
    timed_out: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于序列化）"""
        return {
            "ok": self.ok,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "command": self.command,
            "timed_out": self.timed_out,
        }


class ProcessClient:
    """进程调用统一封装（线程安全）"""

    def __init__(self, default_timeout: float = 30.0, encoding: str = "utf-8"):
        """初始化进程客户端

        Args:
            default_timeout: 默认超时时间（秒）
            encoding: 默认输出编码
        """
        self._default_timeout = default_timeout
        self._encoding = encoding
        self._lock = threading.Lock()
        self._history: List[ProcessResult] = []
        self._max_history = 100

    def run(
        self,
        command: Union[str, List[str]],
        timeout: Optional[float] = None,
        input_data: Optional[str] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        shell: bool = False,
        encoding: Optional[str] = None,
    ) -> ProcessResult:
        """执行命令并返回统一结果

        Args:
            command: 命令（字符串或列表）
            timeout: 超时时间（秒），None 则使用默认值
            input_data: 标准输入数据
            cwd: 工作目录
            env: 环境变量
            shell: 是否使用 shell 执行
            encoding: 输出编码，None 则使用默认值

        Returns:
            ProcessResult 统一结果对象
        """
        if timeout is None:
            timeout = self._default_timeout
        if encoding is None:
            encoding = self._encoding

        # 统一命令格式
        if isinstance(command, str):
            cmd_list = command.split()
        else:
            cmd_list = list(command)

        start_time = time.time()
        result = ProcessResult(command=cmd_list)

        try:
            proc = subprocess.Popen(
                cmd_list if not shell else command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE if input_data is not None else None,
                cwd=cwd,
                env=env,
                shell=shell,
            )

            try:
                stdout_bytes, stderr_bytes = proc.communicate(
                    input=input_data.encode(encoding) if input_data else None,
                    timeout=timeout,
                )
                result.returncode = proc.returncode
                result.stdout = self._decode(stdout_bytes, encoding)
                result.stderr = self._decode(stderr_bytes, encoding)
                result.ok = proc.returncode == 0
                if not result.ok:
                    result.error = f"命令返回非零退出码: {proc.returncode}"
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                result.timed_out = True
                result.ok = False
                result.error = f"命令超时（{timeout}秒）"
                result.stdout = self._decode(proc.stdout.read() if proc.stdout else b"", encoding)
                result.stderr = self._decode(proc.stderr.read() if proc.stderr else b"", encoding)

        except FileNotFoundError as e:
            result.ok = False
            result.error = f"命令未找到: {e}"
        except PermissionError as e:
            result.ok = False
            result.error = f"权限不足: {e}"
        except Exception as e:
            result.ok = False
            result.error = f"执行异常: {type(e).__name__}: {e}"

        result.duration_ms = (time.time() - start_time) * 1000

        # 记录历史
        with self._lock:
            self._history.append(result)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

        return result

    def run_capture_output(self, command: Union[str, List[str]], **kwargs) -> str:
        """执行命令并返回 stdout（失败时返回空字符串）

        适用于只关心输出内容的场景。
        """
        result = self.run(command, **kwargs)
        return result.stdout if result.ok else ""

    def check_output(self, command: Union[str, List[str]], **kwargs) -> str:
        """执行命令并返回 stdout，失败时抛异常

        适用于需要严格错误处理的场景。
        """
        result = self.run(command, **kwargs)
        if not result.ok:
            raise RuntimeError(f"命令执行失败: {result.error}\nstdout: {result.stdout}\nstderr: {result.stderr}")
        return result.stdout

    def get_history(self, limit: int = 10) -> List[ProcessResult]:
        """获取最近的执行历史"""
        with self._lock:
            return list(self._history[-limit:])

    def _decode(self, data: bytes, encoding: str) -> str:
        """解码字节数据，自动处理编码问题"""
        if not data:
            return ""
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            try:
                return data.decode("gbk")
            except UnicodeDecodeError:
                return data.decode("utf-8", errors="replace")


# 全局单例
process_client = ProcessClient(default_timeout=30.0, encoding="utf-8")
