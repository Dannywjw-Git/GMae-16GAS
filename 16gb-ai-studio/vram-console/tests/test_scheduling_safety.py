"""Regression tests for real scheduling defects, without a GPU or services."""
import unittest
from contextlib import ExitStack
from unittest.mock import patch
from engine import budget, queue


class BudgetSafetyTests(unittest.TestCase):
    def evaluate(self, used=8192, known=6144, vram=8, gpu=None, exclusive=False, loaded=False, ctx=None, system=None):
        model = {"id": "target", "vram_gb": vram, "exclusive": exclusive,
                 "ctx": 8192, "context_vram": {"8192": vram}}
        reg = {"system": {"gpu_vram_total_gb": 16, "gpu_base_noise_gb": 1,
                          "vram_reserve_gb": 2.5},
               "ollama": {"models": [model]}, "comfyui": {"models": []}}
        if system:
            reg["system"].update(system)
        with ExitStack() as stack:
            stack.enter_context(patch.object(budget, "REGISTRY", reg))
            stack.enter_context(patch.object(budget, "gpu_status", return_value= gpu if gpu is not None else
                               {"ok": True, "used_mb": used, "free_mb": 16384-used, "total_mb": 16384}))
            stack.enter_context(patch.object(budget, "gpu_processes", return_value=
                               {"ok": True, "known_total_mb": known, "unknown_mb": 0, "desktop_used_mb": 0}))
            stack.enter_context(patch.object(budget, "load_gen_stats", return_value={}))
            stack.enter_context(patch("services.ollama.ollama_ps", return_value=
                               {"models": [{"model": "target"}] if loaded else [{"model": "other"}]}))
            stack.enter_context(patch("services.comfy.comfy_loaded_models", return_value={"models": []}))
            return budget.budget_engine(ctx)

    def test_resident_models_require_release(self):
        self.assertEqual(self.evaluate()["models"][0]["decision"], "free_L1")

    def test_invalid_peak_is_rejected_without_crashing(self):
        import json
        for value in (float("nan"), float("inf"), -1, 0, None, "invalid"):
            with self.subTest(value=value):
                result = self.evaluate(vram=value)
                self.assertEqual(result["models"][0]["decision"], "reject")
                json.dumps(result, allow_nan=False)

    def test_invalid_allowance_blocks_budget(self):
        for value in (-1, float("nan"), float("inf"), "invalid"):
            with self.subTest(value=value):
                self.assertFalse(self.evaluate(system={"vram_reserve_gb": value})["ok"])

    def test_impossible_peak_is_rejected_even_with_releasable_models(self):
        self.assertEqual(self.evaluate(vram=20)["models"][0]["decision"], "reject")

    def test_live_capacity_overrides_16gb_reference(self):
        gpu = {"ok": True, "total_mb": 8192, "used_mb": 1024, "free_mb": 7168}
        result = self.evaluate(used=1024, known=0, gpu=gpu)
        self.assertEqual(result["total_gb"], 8)
        self.assertEqual(result["models"][0]["decision"], "reject")

    def test_missing_telemetry_blocks_admission(self):
        self.assertFalse(self.evaluate(gpu={"ok": False})["ok"])

    def test_stale_telemetry_blocks_admission(self):
        gpu = {"ok": True, "stale": True, "total_mb": 16384, "used_mb": 1024, "free_mb": 15360}
        self.assertFalse(self.evaluate(gpu=gpu)["ok"])

    def test_unknown_context_cannot_reuse_default_estimate(self):
        item = self.evaluate(ctx={"target": 131072})["models"][0]
        self.assertEqual(item["decision"], "reject")

    def test_exclusive_model_requires_release_of_other_models(self):
        self.assertEqual(self.evaluate(used=3072, known=2048, vram=2, exclusive=True)["models"][0]["decision"], "free_L1")

    def test_loaded_model_has_no_zero_cost_promise(self):
        self.assertEqual(self.evaluate(used=14336, known=12288, loaded=True)["models"][0]["decision"], "reject")


class QueueSafetyTests(unittest.TestCase):
    def task(self):
        return {"id": "test", "model": "target", "workflow": "test.json", "params": {},
                "status": "queued", "error": "", "started": None}

    def run_task(self, decisions, release=None, activity=None):
        model = {"id": "target", "workflow": "test.json"}
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(queue, "REGISTRY", {"comfyui": {"models": [model]}}))
        stack.enter_context(patch.object(queue, "budget_engine", side_effect=decisions))
        stack.enter_context(patch.object(queue, "gpu_guard_evict", return_value=release or {"ok": True}))
        stack.enter_context(patch.object(queue, "time"))
        stack.enter_context(patch("engine.reaper.service_activity", return_value=activity or {"services": {}}))
        stack.enter_context(patch.object(queue, "_load_workflow", return_value={"1": {"inputs": {}}}))
        stack.enter_context(patch.object(queue, "_queue_wait", return_value="failed"))
        submit = stack.enter_context(patch.object(queue, "_queue_submit_comfy", return_value=("pid", None)))
        task = self.task()
        queue._run_task(task)
        return task, submit

    def decision(self, decision="ok", ok=True):
        return {"ok": ok, "models": [{"id": "target", "decision": decision, "note": "test"}]}

    def test_unavailable_budget_never_submits(self):
        task, submit = self.run_task([self.decision(ok=False)])
        self.assertEqual(task["status"], "failed")
        submit.assert_not_called()

    def test_missing_budget_entry_never_submits(self):
        task, submit = self.run_task([{"ok": True, "models": []}])
        self.assertEqual(task["status"], "failed")
        submit.assert_not_called()

    def test_release_is_rechecked(self):
        # A successful /free response does not prove memory was actually released.
        _, submit = self.run_task([self.decision("free_L2"), self.decision("free_L2")])
        submit.assert_not_called()

    def test_busy_service_is_not_evicted(self):
        _, submit = self.run_task([self.decision("free_L2")], activity={"services": {"comfyui": {"busy": True}}})
        submit.assert_not_called()
        queue.gpu_guard_evict.assert_not_called()

    def test_failed_release_never_submits(self):
        _, submit = self.run_task([self.decision("free_L2")], release={"ok": False})
        submit.assert_not_called()

    def test_fresh_budget_can_change_before_submission(self):
        _, submit = self.run_task([self.decision(), self.decision("reject")])
        submit.assert_not_called()

    def test_verified_release_can_submit(self):
        task, submit = self.run_task([self.decision("free_L2"), self.decision()])
        submit.assert_called_once()
        self.assertEqual(task["prompt_id"], "pid")

    def test_canceled_precheck_never_submits(self):
        task = self.task()
        task["cancel_requested"] = True
        with patch.object(queue, "_queue_submit_comfy") as submit:
            queue._run_task(task)
        self.assertEqual(task["status"], "canceled")
        submit.assert_not_called()
