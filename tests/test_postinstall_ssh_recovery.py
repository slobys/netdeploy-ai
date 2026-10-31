"""Post-install SSH disconnect recovery tests; no real SSH, VPS or Docker used."""
from __future__ import annotations

import sys
import threading
import types

import pytest

from app.catalog import build_plan
from app.executor import SSHConfig, SSHError, SSHExecutor
from app.store import Store
from app.tasks import JobRunner


def _password_executor(monkeypatch, tmp_path, connect_error_sequence):
    calls = {"connect": 0, "scripts": [], "hostkeys": 0, "policies": 0, "closed": 0}
    class SSHException(Exception):
        pass
    class BadHostKeyException(SSHException):
        pass
    class AuthenticationException(SSHException):
        pass
    class FakeChannel:
        def exec_command(self, command):
            assert command == 'bash -se'
        def sendall(self, data):
            calls["scripts"].append(data)
        def shutdown_write(self):
            pass
        def recv_ready(self):
            return False
        def recv_stderr_ready(self):
            return False
        def exit_status_ready(self):
            return True
        def recv_exit_status(self):
            return 0
    class FakeTransport:
        def is_active(self):
            return True
        def open_session(self, timeout):
            return FakeChannel()
    class FakeClient:
        def load_host_keys(self, filename):
            assert filename == str(known)
            calls["hostkeys"] += 1
        def set_missing_host_key_policy(self, value):
            assert value == "RejectPolicy"
            calls["policies"] += 1
        def connect(self, **kwargs):
            assert kwargs["password"] == "secret-for-test"
            assert kwargs["allow_agent"] is False
            assert kwargs["look_for_keys"] is False
            calls["connect"] += 1
            n = calls["connect"] - 1
            if n < len(connect_error_sequence) and connect_error_sequence[n] is not None:
                error_type, message = connect_error_sequence[n]
                raise error_type(message)
        def get_transport(self):
            return FakeTransport()
        def close(self):
            calls["closed"] += 1
    monkeypatch.setitem(sys.modules, "paramiko", types.SimpleNamespace(
        SSHClient=FakeClient, RejectPolicy=lambda: "RejectPolicy",
        SSHException=SSHException, BadHostKeyException=BadHostKeyException,
        AuthenticationException=AuthenticationException,
    ))
    # Avoid test delays while preserving connection retry logic and its limits.
    monkeypatch.setattr("app.executor.time.sleep", lambda _: None)
    known = tmp_path / "known_hosts"
    known.write_text("example.com ssh-ed25519 AAAA\n", encoding="utf-8")
    executor = SSHExecutor(SSHConfig(str(tmp_path / "unused"), str(known)))
    executor.set_password(2, "secret-for-test")
    host = {"id": 2, "hostname": "example.com", "port": 22,
            "username": "root", "auth_mode": "password"}
    return executor, host, calls, {
        "handshake": SSHException,
        "badkey": BadHostKeyException,
        "auth": AuthenticationException,
    }


def test_transient_ssh_handshake_reconnects_without_repeating_remote_script(monkeypatch, tmp_path):
    # Fake errors supplied in sequence with a mutable list after classes exist.
    executor, host, calls, errs = _password_executor(monkeypatch, tmp_path, [])
    sequence = [(errs["handshake"], "Error reading SSH protocol banner"),
                (errs["handshake"], "unexpected packet")]
    # Reconfigure the client for the sequence without affecting the known-hosts checks.
    calls["connect"] = 0
    client_class = sys.modules["paramiko"].SSHClient
    original = client_class.connect
    def flaky_connect(self, **kwargs):
        original(self, **kwargs)
        if calls["connect"] <= len(sequence):
            cls, msg = sequence[calls["connect"] - 1]
            raise cls(msg)
    monkeypatch.setattr(client_class, "connect", flaky_connect)
    assert executor.run(host, "echo verification-only") == ""
    assert calls["connect"] == 3
    assert calls["scripts"] == [b"echo verification-only"]
    assert calls["hostkeys"] == 3
    assert calls["policies"] == 3
    assert calls["closed"] == 3


@pytest.mark.parametrize("kind,detail,expected", [
    ("badkey", "wrong key", "SSH_HOST_KEY_CHANGED"),
    ("auth", "bad password", "SSH_AUTH_FAILED"),
    ("handshake", "Incompatible ssh peer (no matching kex)", "SSH_ALGORITHM_MISMATCH"),
])
def test_permanent_ssh_error_is_not_retried(monkeypatch, tmp_path, kind, detail, expected):
    executor, host, calls, exceptions = _password_executor(monkeypatch, tmp_path, [])
    cls = exceptions[kind]
    client_class = sys.modules["paramiko"].SSHClient
    original = client_class.connect
    def fail_connect(self, **kwargs):
        original(self, **kwargs)
        raise cls(detail)
    monkeypatch.setattr(client_class, "connect", fail_connect)
    with pytest.raises(SSHError, match=expected):
        executor.run(host, "echo should-never-run")
    assert calls["connect"] == 1
    assert calls["scripts"] == []


def test_repeated_ssh_handshake_failure_never_executes_script(monkeypatch, tmp_path):
    executor, host, calls, errors = _password_executor(monkeypatch, tmp_path, [])
    client_class = sys.modules["paramiko"].SSHClient
    original = client_class.connect
    def always_fails(self, **kwargs):
        original(self, **kwargs)
        raise errors["handshake"]("Error reading SSH protocol banner")
    monkeypatch.setattr(client_class, "connect", always_fails)
    with pytest.raises(SSHError, match="SSH_HANDSHAKE_FAILED"):
        executor.run(host, "echo should-never-run")
    assert calls["connect"] == 3
    assert calls["scripts"] == []
    assert calls["hostkeys"] == 3


FACTS = {
    "OS_ID": "debian", "OS_VERSION": "13", "ARCH": "x86_64",
    "UID": "0", "SYSTEMD": "yes", "SS_AVAILABLE": "yes",
    "FREE_KB": "3000000", "XUI_PRESENT": "no",
}


@pytest.mark.parametrize("error,expected", [
    ("SSH_HANDSHAKE_FAILED：SSH 协议握手失败", "partial"),
    ("SSH_CONNECT_TIMEOUT：SSH 连接超时", "partial"),
    ("SSH_HOST_KEY_CHANGED：主机密钥不可信", "failed"),
    ("退出代码 20：公网 HTTP 监听验收失败", "failed"),
])
def test_runner_preserves_post_installer_state_without_reinstall(tmp_path, error, expected):
    db = Store(str(tmp_path / "app.sqlite"))
    host = db.add_host({"name": "test VPS", "hostname": "8.8.8.8",
                        "username": "root", "port": 22})
    db.save_facts(host["id"], FACTS)
    current = db.host(host["id"])
    plan = build_plan("3x-ui", FACTS, {"panel_port": 8443, "access_mode": "npm"})
    plan["trust_epoch"] = current["trust_epoch"]
    job = db.new_job(host["id"], "3x-ui", plan)

    class FakeExecutor:
        def __init__(self):
            self.scripts = []
        def run(self, host, script, timeout):
            self.scripts.append(script)
            if len(self.scripts) == 5:
                raise SSHError(error)
            if len(self.scripts) == 4:
                return "Official installer finished; sensitive credentials kept on VPS only"
            return "precheck passed"
    fake = FakeExecutor()
    runner = JobRunner(db, fake)
    lock = threading.Lock()
    lock.acquire()
    runner._run(job["id"], current, lock)
    updated = db.job(job["id"])
    assert updated["status"] == expected
    assert len(fake.scripts) == 5
    assert fake.scripts.count(plan["steps"][3]["script"]) == 1
    assert "Official installer finished" in updated["logs"]
    if expected == "partial":
        assert "只读检查现有面板" in updated["logs"]
        assert "验收尚未完成" in updated["logs"]
        assert error.split("：")[0] in updated["error"]
    else:
        assert "失败：" in updated["logs"]
        assert "只读检查现有面板" not in updated["logs"]
