"""Memory counters must distinguish GPU residency, CPU offload and MiB/GiB."""
from unittest.mock import patch
from clients.ollama_client import list_loaded_models
from engine.budget import _diagnose_desktop_processes


def test_ollama_partial_offload_uses_gpu_bytes():
    response = {"models": [{"name": "model-a", "size": 8 * 1024**3, "size_vram": 3 * 1024**3}]}
    with patch("clients.ollama_client._get", return_value=(True, response, "")):
        model = list_loaded_models()["models"][0]
    assert model["size_gb"] == 3
    assert model["total_size_gb"] == 8
    assert model["model"] == "model-a"


def test_missing_gpu_size_does_not_invent_reclaimable_memory():
    with patch("clients.ollama_client._get", return_value=(True, {"models": [{"name": "a", "size": 8*1024**3}]}, "")):
        model = list_loaded_models()["models"][0]
    assert not model["vram_known"]
    assert model["size_gb"] == 0


def test_desktop_helper_mib_is_not_multiplied_by_1024():
    with patch("services.helper._helper_health", return_value=True), patch(
        "services.helper._helper_req", return_value=(True, {"ok": True,
        "processes": [{"Pid": 123, "Name": "editor", "MB": 256}]})):
        result = _diagnose_desktop_processes(1024)
    assert result["desktop"][0]["used_mb"] == 256
    assert result["unknown_mb"] == 768
