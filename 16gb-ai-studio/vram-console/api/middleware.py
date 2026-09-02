#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae HTTP 中间件框架（中间层重构 M1）
- 中间件签名：(req: Request, next: Callable) -> Response
- 中间件链：按注册顺序执行，每个中间件可选择：
  1. 直接返回 Response（短路，不调用 next）
  2. 调用 next(req) 继续执行链，可对请求/响应做前后处理
- 常用中间件：错误处理、缓存失效、请求日志、认证（M2 接入）
"""
import time
from typing import Callable, List, Optional
from api.request import Request
from api.response import Response
from core.logger import log_event, log_error


# 中间件类型
Middleware = Callable[[Request, Callable[[Request], Response]], Response]


class MiddlewareChain:
    """中间件链。按注册顺序执行，最后调用端点 handler。

    用法：
        chain = MiddlewareChain([
            error_handler_middleware,
            request_logger_middleware,
            cache_invalidate_middleware,
        ])

        response = chain.execute(req, endpoint_handler)
    """

    def __init__(self, middlewares: Optional[List[Middleware]] = None):
        self._middlewares: List[Middleware] = list(middlewares or [])

    def add(self, middleware: Middleware) -> "MiddlewareChain":
        """注册中间件（追加到链尾）。"""
        self._middlewares.append(middleware)
        return self

    def execute(self, req: Request, endpoint: Callable[[Request], Response]) -> Response:
        """执行中间件链，最后调用端点 handler。"""
        # 构建调用链：从最后一个中间件开始，逐层包装
        handler = endpoint
        for middleware in reversed(self._middlewares):
            # 闭包捕获当前 middleware 和下一层 handler
            next_handler = handler
            mw = middleware

            def wrapped(request: Request, _mw=mw, _next=next_handler) -> Response:
                return _mw(request, _next)

            handler = wrapped
        return handler(req)

    def __len__(self) -> int:
        return len(self._middlewares)


# ============================================================
# 常用中间件实现
# ============================================================

def error_handler_middleware(req: Request, next: Callable) -> Response:
    """错误处理中间件：捕获端点和后续中间件的异常，返回 500。

    应放在链的最外层（第一个注册），确保能捕获所有异常。
    """
    try:
        return next(req)
    except Exception as e:
        log_error("api_unhandled_exception", error=str(e), path=req.path, method=req.method)
        return Response.internal_error("服务器内部错误", details={"error": str(e)})


def request_logger_middleware(req: Request, next: Callable) -> Response:
    """请求日志中间件：记录请求方法、路径、耗时、状态码。

    降噪策略：只记录有意义的请求，过滤轮询噪音：
    - POST/PUT/DELETE 写操作（用户操作）
    - 耗时 >500ms 的慢请求
    - 状态码 >=400 的错误请求
    - GET 请求只记录到日志文件，不发布到事件总线
    """
    start = time.time()
    response = next(req)
    elapsed_ms = int((time.time() - start) * 1000)

    # 判断是否为有意义的事件（需要发布到事件总线）
    is_write = req.method in ("POST", "PUT", "DELETE")
    is_slow = elapsed_ms > 500
    is_error = response.status_code >= 400
    is_meaningful = is_write or is_slow or is_error

    if is_meaningful:
        log_event(
            "api_request",
            method=req.method,
            path=req.path,
            status=response.status_code,
            elapsed_ms=elapsed_ms,
            client_ip=req.client_ip,
        )
    else:
        # 普通 GET 轮询只记录到日志，不发布事件（避免淹没重要事件）
        pass

    return response


def cache_invalidate_middleware(req: Request, next: Callable) -> Response:
    """缓存失效中间件：POST/PUT/DELETE 请求时失效状态缓存。

    复用现有 services.status 中的 invalidate_status_cache。
    """
    if req.method in ("POST", "PUT", "DELETE"):
        try:
            from services.status import invalidate_status_cache
            invalidate_status_cache()
        except Exception:
            pass  # 缓存失效失败不影响请求
    return next(req)


def no_cache_headers_middleware(req: Request, next: Callable) -> Response:
    """API 响应禁用缓存中间件：添加 Cache-Control: no-store。"""
    response = next(req)
    if req.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


# ============================================================
# 默认中间件链（M2 迁移端点时使用）
# ============================================================

def build_default_chain() -> MiddlewareChain:
    """构建默认中间件链（M1 基础设施，M2 接入认证中间件）。

    顺序（从外到内）：
    1. error_handler — 最外层，捕获所有异常
    2. request_logger — 记录请求日志
    3. no_cache_headers — API 禁用缓存
    4. cache_invalidate — POST 失效缓存
    5. (M2 接入) auth — 认证中间件
    6. 端点 handler
    """
    return MiddlewareChain([
        error_handler_middleware,
        request_logger_middleware,
        no_cache_headers_middleware,
        cache_invalidate_middleware,
    ])
