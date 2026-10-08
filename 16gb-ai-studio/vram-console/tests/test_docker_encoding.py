"""Docker emits UTF-8 regardless of the Windows locale."""
from types import SimpleNamespace
from core import utils


def test_docker_text_uses_utf8(monkeypatch):
    seen = {}
    def run(args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(returncode=0, stdout='容器配置', stderr='')
    monkeypatch.setattr(utils.subprocess, 'run', run)
    assert utils.run_args(['docker', 'inspect', 'comfyui']) == (0, '容器配置')
    assert seen['encoding'] == 'utf-8'
    assert seen['errors'] == 'replace'
