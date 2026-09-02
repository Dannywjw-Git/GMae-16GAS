#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae HTTP 路由注册器（中间层重构 M1）
- 零依赖装饰器风格路由（类似 Flask，但用标准库实现）
- 端点函数签名：def handler(req: Request) -> Response
- 支持 GET/POST 注册，精确路径匹配
- 预留路径参数扩展接口（当前 API 均为固定路径）
"""
from typing import Callable, Optional, Tuple, List, Dict
from api.request import Request


# 端点函数类型
EndpointHandler = Callable[[Request], "Response"]


class Route:
    """单条路由记录。"""

    def __init__(self, method: str, path: str, handler: EndpointHandler, name: str = ""):
        self.method = method.upper()
        self.path = path
        self.handler = handler
        self.name = name or handler.__name__

    def __repr__(self) -> str:
        return f"<Route {self.method} {self.path} -> {self.name}>"


class Router:
    """HTTP 路由注册器。装饰器风格注册，精确路径匹配。

    用法：
        router = Router()

        @router.get("/api/health")
        def health(req: Request) -> Response:
            return Response.success({"ok": True})

        @router.post("/api/scene")
        def switch_scene(req: Request) -> Response:
            scene = req.body.get("scene", "")
            return Response.success(scene_switch(scene))

        # 匹配
        handler, params = router.match("GET", "/api/health")
    """

    def __init__(self):
        self._routes: List[Route] = []
        self._index: Dict[Tuple[str, str], Route] = {}  # (method, path) -> Route

    def get(self, path: str, name: str = "") -> Callable:
        """注册 GET 路由。"""
        return self._register("GET", path, name)

    def post(self, path: str, name: str = "") -> Callable:
        """注册 POST 路由。"""
        return self._register("POST", path, name)

    def _register(self, method: str, path: str, name: str = "") -> Callable:
        """内部注册方法，返回装饰器。"""
        def decorator(handler: EndpointHandler) -> EndpointHandler:
            route = Route(method, path, handler, name)
            key = (method, path)
            if key in self._index:
                # 覆盖已注册的路由（允许模块重新加载时更新）
                old = self._index[key]
                self._routes = [r for r in self._routes if r is not old]
            self._routes.append(route)
            self._index[key] = route
            return handler
        return decorator

    def match(self, method: str, path: str) -> Tuple[Optional[EndpointHandler], dict]:
        """匹配路由。返回 (handler, path_params)。未匹配返回 (None, {})。

        当前为精确路径匹配。path_params 始终为空 dict（预留路径参数扩展）。
        """
        key = (method.upper(), path)
        route = self._index.get(key)
        if route:
            return route.handler, {}
        return None, {}

    def has_route(self, method: str, path: str) -> bool:
        """检查是否已注册某路由。"""
        return (method.upper(), path) in self._index

    def list_routes(self) -> List[Route]:
        """列出所有已注册路由。"""
        return list(self._routes)

    def count(self) -> int:
        """已注册路由数量。"""
        return len(self._routes)

    def __len__(self) -> int:
        return len(self._routes)

    def __repr__(self) -> str:
        return f"<Router {len(self._routes)} routes>"


# 全局路由实例（端点模块通过 from api.router import router 注册）
router = Router()
