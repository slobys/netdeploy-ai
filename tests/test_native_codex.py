"""Windows-native Codex worker regression: no Docker and no inherited VPS secrets.

All process and SDK actions are mocked; these tests work in Linux/Windows CI.
"""
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import native_codex
import app.main as main


ROOT = Path(__file__).resolve().parents[1]


def test_native_autostart_requires_windows_and_explicit_quickstart_switch(monkeypatch):
    monkeypatch.setattr(native_codex, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.delenv("NETDEPLOY_CODEX_NATIVE_AUTO_START", raising=False)
    assert native_codex.native_enabled() is False
    monkeypatch.setenv("NETDEPLOY_CODEX_NATIVE_AUTO_START", "1")
    assert native_codex.native_enabled() is True
    monkeypatch.setenv("NETDEPLOY_CODEX_AUTO_START", "0")
    assert native_codex.native_enabled() is False
    monkeypatch.setattr(native_codex, "sys", SimpleNamespace(platform="linux"))
    assert native_codex.native_enabled() is False


def test_native_environment_does_not_inherit_admin_ssh_api_or_docker(monkeypatch):
    for key, value in {
        "NETDEPLOY_ADMIN_TOKEN": "must-never-leak",
        "NETDEPLOY_SSH_KEY_FILE": "private-ssh-key",
        "NETDEPLOY_DATA": "secret-database-folder",
        "SSH_AUTH_SOCK": "sensitive-agent",
        "OPENAI_API_KEY": "sk-secret",
        "CODEX_API_KEY": "api-billing-not-allowed",
        "DOCKER_HOST": "ssh://remote",
        "PYTHONPATH": "untrusted-imports",
        "PATH": "/tmp/untrusted",
        "LOCALAPPDATA": "C:\\temp",
        "SystemRoot": "C:\\Windows",
    }.items():
        monkeypatch.setenv(key, value)
    env = native_codex.NativeCodexManager._env()
    for key in ("NETDEPLOY_ADMIN_TOKEN", "NETDEPLOY_SSH_KEY_FILE",
                "NETDEPLOY_DATA", "SSH_AUTH_SOCK", "OPENAI_API_KEY",
                "CODEX_API_KEY", "DOCKER_HOST", "PYTHONPATH"):
        assert key not in env
    assert "/tmp/untrusted" not in env["PATH"]
    assert env["PYTHONNOUSERSITE"] == "1"


def test_local_proxy_works_without_forwarding_remote_proxy_or_credentials(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.com:3128")
    monkeypatch.setenv("ALL_PROXY", "http://user:pass@localhost:7891")
    env = native_codex.NativeCodexManager._env()
    assert env.get("HTTPS_PROXY") == "http://127.0.0.1:7890"
    assert "HTTP_PROXY" not in env
    assert "ALL_PROXY" not in env
    assert env["NO_PROXY"].startswith("localhost")
    monkeypatch.setenv("HTTPS_PROXY", "http://localhost:bad-port")
    assert "HTTPS_PROXY" not in native_codex.NativeCodexManager._env()


class FakeChild:
    def __init__(self):
        self.done = False
        self.terminated = False
    def poll(self):
        return 0 if self.done else None
    def terminate(self):
        self.terminated = True
        self.done = True
    def wait(self, timeout=None):
        return 0
    def kill(self):
        self.done = True


def test_native_worker_copies_only_api_module_and_preserves_login(monkeypatch, tmp_path):
    monkeypatch.setenv("NETDEPLOY_WORKER_TOKEN", "native-test-token-" + "x" * 32)
    monkeypatch.setenv("NETDEPLOY_ADMIN_TOKEN", "must-not-enter-worker")
    monkeypatch.setenv("NETDEPLOY_SSH_KEY_FILE", "must-not-enter-worker")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-enter-worker")
    manager = native_codex.NativeCodexManager(ROOT, tmp_path / "data",
                                             local_root=tmp_path / "isolated")
    calls = []
    child = FakeChild()
    statuses = iter((False, True))
    monkeypatch.setattr(manager, "_status", lambda token: next(statuses))
    monkeypatch.setattr(manager, "_port_in_use", lambda: False)
    def fake_setup(args, cwd, env, *, timeout, error):
        calls.append(("setup", args, cwd, env))
        if args[1:3] == ["-m", "venv"]:
            py = tmp_path / "isolated" / "venv" / "Scripts" / "python.exe"
            py.parent.mkdir(parents=True)
            py.touch()
    monkeypatch.setattr(manager, "_run_setup", fake_setup)
    def fake_spawn(args, cwd, env):
        calls.append(("worker", args, cwd, env))
        return child
    monkeypatch.setattr(manager, "_spawn", fake_spawn)
    manager._run()
    assert (tmp_path / "isolated" / "runtime" / "app" / "ai_worker.py").is_file()
    assert (tmp_path / "isolated" / "auth" / "config.toml").read_text().find(
        "prefer_mxc = true"
    ) >= 0
    assert (tmp_path / "isolated" / "requirements.sha256").is_file()
    assert len([c for c in calls if c[0] == "setup"]) == 2
    worker_args = [c for c in calls if c[0] == "worker"][0]
    _, args, cwd, env = worker_args
    assert str(cwd).endswith("workspace")
    assert "--host" in args and args[args.index("--host") + 1] == "127.0.0.1"
    assert "--port" in args and args[args.index("--port") + 1] == "8789"
    assert env["NETDEPLOY_CODEX_NATIVE"] == "1"
    assert env["CODEX_HOME"].endswith("auth")
    assert env["NETDEPLOY_CODEX_PARENT_PID"].isdigit()
    assert str(ROOT) not in str(cwd)
    for key in ("NETDEPLOY_ADMIN_TOKEN", "NETDEPLOY_SSH_KEY_FILE",
                "NETDEPLOY_DATA", "OPENAI_API_KEY", "DOCKER_HOST"):
        assert key not in env
    assert "127.0.0.1" not in str(cwd)
    assert manager.child is child
    assert "ready" in (tmp_path / "data" / "codex-worker-startup.json").read_text()
    manager.stop()
    assert child.terminated
    assert '"stopped"' in (tmp_path / "data" / "codex-worker-startup.json").read_text()


def test_native_worker_refuses_unknown_local_service(monkeypatch, tmp_path):
    monkeypatch.setenv("NETDEPLOY_WORKER_TOKEN", "native-test-token-" + "x" * 32)
    manager = native_codex.NativeCodexManager(ROOT, tmp_path / "data",
                                             local_root=tmp_path / "isolated")
    monkeypatch.setattr(manager, "_status", lambda _: None)
    monkeypatch.setattr(manager, "_port_in_use", lambda: True)
    manager._run()
    state = (tmp_path / "data" / "codex-worker-startup.json").read_text()
    assert '"failed"' in state
    assert "8789" in state
    assert not (tmp_path / "isolated").exists()


def test_native_worker_does_not_start_from_admin_process(monkeypatch, tmp_path):
    monkeypatch.setenv("NETDEPLOY_WORKER_TOKEN", "native-test-token-" + "x" * 32)
    manager = native_codex.NativeCodexManager(
        ROOT, tmp_path / "data", local_root=tmp_path / "isolated"
    )
    monkeypatch.setattr(manager, "_running_elevated", lambda: True)
    manager._run()
    state = (tmp_path / "data" / "codex-worker-startup.json").read_text()
    assert '"failed"' in state
    assert "管理员权限" in state
    assert not (tmp_path / "isolated").exists()


def test_failed_worker_health_probe_reaps_native_process(monkeypatch, tmp_path):
    monkeypatch.setenv("NETDEPLOY_WORKER_TOKEN", "native-test-token-" + "x" * 32)
    manager = native_codex.NativeCodexManager(
        ROOT, tmp_path / "data", local_root=tmp_path / "isolated"
    )
    child = FakeChild()
    class InstantEvent:
        def is_set(self):
            return False
        def wait(self, seconds):
            return False
    manager.stop_event = InstantEvent()
    monkeypatch.setattr(manager, "_status", lambda _: None)
    monkeypatch.setattr(manager, "_port_in_use", lambda: False)
    def fake_setup(args, cwd, env, *, timeout, error):
        if args[1:3] == ["-m", "venv"]:
            py = tmp_path / "isolated" / "venv" / "Scripts" / "python.exe"
            py.parent.mkdir(parents=True)
            py.touch()
    monkeypatch.setattr(manager, "_run_setup", fake_setup)
    monkeypatch.setattr(manager, "_spawn", lambda *args, **kwargs: child)
    manager._run()
    assert child.terminated, "Never leak orphan Codex workers after startup failure"
    assert '"failed"' in (tmp_path / "data" / "codex-worker-startup.json").read_text()


def test_native_lifecycle_is_nonblocking_and_stops_cleanly(monkeypatch):
    calls = []
    class FakeManager:
        def __init__(self, root, data):
            calls.append(("init", root, data))
        def start(self):
            calls.append(("start",))
        def stop(self):
            calls.append(("stop",))
    monkeypatch.setattr(native_codex, "native_enabled", lambda: True)
    monkeypatch.setattr(native_codex, "NativeCodexManager", FakeManager)
    with TestClient(main.app) as client:
        assert client.get("/api/health").status_code == 200
        assert ("start",) in calls
        assert ("stop",) not in calls
    assert ("stop",) in calls
    assert main._native_codex_manager is None
