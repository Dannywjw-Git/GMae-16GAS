from unittest.mock import patch
import pytest
from clients.nvidia_smi import query_gpu_memory


@pytest.mark.parametrize("record", ["", "16384, N/A, 8192, 0", "bad",
    "16384, 100, 16284, 0\n16384, 200, 16184, 0", "16384, -1, 16385, 0"])
def test_bad_records_do_not_crash_or_admit(record):
    with patch("clients.nvidia_smi.run_args", return_value=(0, record)):
        assert not query_gpu_memory()["ok"]


def test_single_gpu_is_selected_explicitly():
    with patch("clients.nvidia_smi.run_args", return_value=(0, "16384, 2048, 14336, 5")) as command:
        assert query_gpu_memory()["free_mb"] == 14336
        assert "--id=0" in command.call_args.args[0]
