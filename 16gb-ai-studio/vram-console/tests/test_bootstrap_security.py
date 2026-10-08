"""HTTP dispatch and authentication regressions in a fresh checkout."""
from unittest.mock import Mock, patch
from api.routes import Handler
from api.endpoints import router
from api import auth


def handler(headers=None):
    h = object.__new__(Handler)
    h.headers = headers or {}
    h._error = Mock()
    return h


def test_first_run_does_not_allow_privileged_api():
    h = handler()
    assert not h._check_auth()
    h._error.assert_called_once()


def test_token_works_before_admin_setup():
    with patch("api.routes.API_TOKEN", "configured-token"):
        assert handler({"X-API-Key": "configured-token"})._check_auth()
        assert not handler({"X-API-Key": "wrong-token"})._check_auth()


def test_password_change_revocation_survives_reload():
    auth.setup_admin("admin@example.com", "old-password")
    sid = auth.create_session("admin@example.com")
    ok, _ = auth.change_password("admin@example.com", "old-password", "new-password")
    assert ok
    auth._load_sessions()
    assert auth.get_session(sid) is None


def test_dispatcher_registers_core_endpoints():
    for method, path in [("GET", "/api/health"), ("POST", "/api/auth/setup"),
                         ("POST", "/api/queue"), ("GET", "/api/status"),
                         ("POST", "/api/scene"), ("POST", "/api/admission")]:
        fn, _ = router.match(method, path)
        assert callable(fn), (method, path)
