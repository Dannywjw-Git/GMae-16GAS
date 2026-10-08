"""Offline suite: service experiments require an explicit command."""
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# These are live scripts, not offline tests. The first executes HTTP calls on import.
# Run them directly only in a disposable GPU environment.
collect_ignore = ["test_e2e_improvements.py", "test_queue_e2e.py"]


@pytest.fixture(autouse=True)
def isolate_auth_files(tmp_path, monkeypatch):
    from api import auth
    monkeypatch.setattr(auth, "USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setattr(auth, "SESSIONS_FILE", str(tmp_path / "sessions.json"))
    monkeypatch.setattr(auth, "SESSIONS", {})
    monkeypatch.setattr(auth, "RESET_CODES", {})
