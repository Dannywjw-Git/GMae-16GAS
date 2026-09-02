#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DockerEventsMonitor 单元测试（S1.2 Docker Events API）

测试覆盖：
- 基本状态查询（get_container_state / get_all_states / is_available）
- 事件处理（start / stop / die / kill / restart / destroy）
- 非容器事件忽略（image / network / volume 事件不更新状态）
- 状态变化回调（on_state_change 在容器状态变化时触发）
- 线程安全（并发访问不崩溃）
- 降级模式（is_available=False 时不影响其他功能）

注意：本测试不调用 start()/stop()（避免实际启动 docker events 子进程），
直接测试 _handle_event 和其他纯逻辑方法。
"""
import unittest
import sys
import os
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.docker_events import DockerEventsMonitor


def _make_event(action: str, container_name: str = "test_container",
                event_type: str = "container") -> dict:
    """构造一个模拟的 docker events JSON 事件。"""
    return {
        "Type": event_type,
        "Action": action,
        "Actor": {
            "ID": "abc123def456",
            "Attributes": {
                "name": container_name,
                "image": "test_image:latest",
            },
        },
        "time": int(time.time()),
        "timeNano": int(time.time() * 1e9),
    }


class TestDockerEventsBasic(unittest.TestCase):
    """基本功能测试。"""

    def setUp(self):
        self.monitor = DockerEventsMonitor()

    def test_initial_state(self):
        """初始状态：无容器记录，不可用（未启动）。"""
        self.assertEqual(self.monitor.get_all_states(), {})
        self.assertIsNone(self.monitor.get_container_state("nonexistent"))
        self.assertFalse(self.monitor.is_available())

    def test_get_container_state_unknown(self):
        """查询不存在的容器返回 None。"""
        self.assertIsNone(self.monitor.get_container_state("ollama"))

    def test_get_all_states_returns_copy(self):
        """get_all_states 返回副本，外部修改不影响内部状态。"""
        self.monitor._handle_event(_make_event("start", "ollama"))
        states = self.monitor.get_all_states()
        states["hacked"] = "running"
        # 内部状态不应被修改
        self.assertNotIn("hacked", self.monitor.get_all_states())


class TestDockerEventsHandling(unittest.TestCase):
    """事件处理测试。"""

    def setUp(self):
        self.monitor = DockerEventsMonitor()

    def test_start_event(self):
        """start 事件：容器状态变为 running。"""
        self.monitor._handle_event(_make_event("start", "ollama"))
        self.assertEqual(self.monitor.get_container_state("ollama"), "running")

    def test_stop_event(self):
        """stop 事件：容器状态变为 exited。"""
        self.monitor._handle_event(_make_event("start", "comfyui"))
        self.monitor._handle_event(_make_event("stop", "comfyui"))
        self.assertEqual(self.monitor.get_container_state("comfyui"), "exited")

    def test_die_event(self):
        """die 事件：容器状态变为 exited。"""
        self.monitor._handle_event(_make_event("start", "fooocus"))
        self.monitor._handle_event(_make_event("die", "fooocus"))
        self.assertEqual(self.monitor.get_container_state("fooocus"), "exited")

    def test_kill_event(self):
        """kill 事件：容器状态变为 exited。"""
        self.monitor._handle_event(_make_event("start", "ollama"))
        self.monitor._handle_event(_make_event("kill", "ollama"))
        self.assertEqual(self.monitor.get_container_state("ollama"), "exited")

    def test_restart_event(self):
        """restart 事件：容器状态变为 running。"""
        self.monitor._handle_event(_make_event("stop", "comfyui"))
        self.monitor._handle_event(_make_event("restart", "comfyui"))
        self.assertEqual(self.monitor.get_container_state("comfyui"), "running")

    def test_destroy_event(self):
        """destroy 事件：容器从状态表中移除。"""
        self.monitor._handle_event(_make_event("start", "old_container"))
        self.assertIsNotNone(self.monitor.get_container_state("old_container"))
        self.monitor._handle_event(_make_event("destroy", "old_container"))
        self.assertIsNone(self.monitor.get_container_state("old_container"))

    def test_multiple_containers(self):
        """多个容器的状态独立维护。"""
        self.monitor._handle_event(_make_event("start", "ollama"))
        self.monitor._handle_event(_make_event("start", "comfyui"))
        self.monitor._handle_event(_make_event("stop", "comfyui"))
        self.assertEqual(self.monitor.get_container_state("ollama"), "running")
        self.assertEqual(self.monitor.get_container_state("comfyui"), "exited")
        self.assertEqual(len(self.monitor.get_all_states()), 2)

    def test_non_container_event_ignored(self):
        """非容器事件（image/network/volume）不更新状态表。"""
        self.monitor._handle_event(_make_event("pull", "nginx", event_type="image"))
        self.monitor._handle_event(_make_event("create", "test_net", event_type="network"))
        self.assertEqual(self.monitor.get_all_states(), {})

    def test_event_without_container_name_ignored(self):
        """没有容器名的事件不更新状态表。"""
        event = {"Type": "container", "Action": "start", "Actor": {"ID": "abc", "Attributes": {}}}
        self.monitor._handle_event(event)
        self.assertEqual(self.monitor.get_all_states(), {})

    def test_other_container_actions_ignored(self):
        """其他容器事件（create/rename/pause/exec_create）不更新状态。"""
        self.monitor._handle_event(_make_event("create", "new_container"))
        self.assertIsNone(self.monitor.get_container_state("new_container"))
        self.monitor._handle_event(_make_event("pause", "new_container"))
        self.assertIsNone(self.monitor.get_container_state("new_container"))


class TestDockerEventsCallback(unittest.TestCase):
    """状态变化回调测试。"""

    def setUp(self):
        self.callback_calls = []
        self.monitor = DockerEventsMonitor(
            on_state_change=lambda name, action: self.callback_calls.append((name, action))
        )

    def test_callback_on_start(self):
        """start 事件触发回调。"""
        self.monitor._handle_event(_make_event("start", "ollama"))
        self.assertEqual(len(self.callback_calls), 1)
        self.assertEqual(self.callback_calls[0], ("ollama", "start"))

    def test_callback_on_stop(self):
        """stop 事件触发回调。"""
        self.monitor._handle_event(_make_event("start", "ollama"))
        self.monitor._handle_event(_make_event("stop", "ollama"))
        self.assertEqual(len(self.callback_calls), 2)
        self.assertEqual(self.callback_calls[1], ("ollama", "stop"))

    def test_callback_on_destroy(self):
        """destroy 事件触发回调。"""
        self.monitor._handle_event(_make_event("start", "temp"))
        self.monitor._handle_event(_make_event("destroy", "temp"))
        self.assertEqual(len(self.callback_calls), 2)
        self.assertEqual(self.callback_calls[1], ("temp", "destroy"))

    def test_no_callback_for_non_state_events(self):
        """非状态变化事件（create/pause/exec_create）不触发回调。"""
        self.monitor._handle_event(_make_event("create", "new_container"))
        self.monitor._handle_event(_make_event("pause", "new_container"))
        self.assertEqual(len(self.callback_calls), 0)

    def test_callback_exception_does_not_crash(self):
        """回调抛出异常不影响事件处理。"""
        def bad_callback(name, action):
            raise RuntimeError("callback error")

        monitor = DockerEventsMonitor(on_state_change=bad_callback)
        # 不应抛出异常
        monitor._handle_event(_make_event("start", "ollama"))
        self.assertEqual(monitor.get_container_state("ollama"), "running")

    def test_callback_can_be_set_after_init(self):
        """回调可以在初始化后设置。"""
        monitor = DockerEventsMonitor()
        calls = []
        monitor.on_state_change = lambda name, action: calls.append(name)
        monitor._handle_event(_make_event("start", "comfyui"))
        self.assertEqual(calls, ["comfyui"])


class TestDockerEventsThreadSafety(unittest.TestCase):
    """线程安全测试。"""

    def setUp(self):
        self.monitor = DockerEventsMonitor()

    def test_concurrent_event_handling(self):
        """并发处理事件不崩溃，状态一致。"""
        errors = []

        def worker(container_prefix):
            try:
                for i in range(20):
                    name = f"{container_prefix}_{i}"
                    self.monitor._handle_event(_make_event("start", name))
                    self.monitor._handle_event(_make_event("stop", name))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"c{t}",)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(len(errors), 0, f"Thread safety errors: {errors}")
        # 所有容器最终状态应为 exited
        states = self.monitor.get_all_states()
        for name, state in states.items():
            self.assertEqual(state, "exited")

    def test_concurrent_read_and_write(self):
        """并发读写不崩溃。"""
        errors = []

        def writer():
            try:
                for i in range(30):
                    self.monitor._handle_event(_make_event("start", f"w_{i}"))
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(30):
                    _ = self.monitor.get_all_states()
                    _ = self.monitor.get_container_state("w_0")
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(len(errors), 0, f"Concurrent read/write errors: {errors}")


class TestDockerEventsDegraded(unittest.TestCase):
    """降级模式测试。"""

    def test_unavailable_does_not_affect_methods(self):
        """is_available=False 时，查询方法正常返回空/None。"""
        monitor = DockerEventsMonitor()
        # 未启动，is_available=False
        self.assertFalse(monitor.is_available())
        self.assertEqual(monitor.get_all_states(), {})
        self.assertIsNone(monitor.get_container_state("any"))

    def test_stop_without_start_does_not_crash(self):
        """未启动时调用 stop() 不崩溃。"""
        monitor = DockerEventsMonitor()
        monitor.stop()  # 不应抛出异常
        self.assertFalse(monitor.is_available())


if __name__ == "__main__":
    unittest.main(verbosity=2)
