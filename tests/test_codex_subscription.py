"""Codex account integration: isolated device login, admin-only proxy, no API fallback."""
import importlib
import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main


ADMIN = {"X-Admin-Token": os.environ["NETDEPLOY_ADMIN_TOKEN"]}
WORKER_TOKEN = "test-worker-token-" + "w" * 32
WORKER = {"X-Worker-Token": WORKER_TOKEN}


def test_codex_admin_routes_are_protected_and_use_worker_proxy(monkeypatch):
    client = TestClient(main.app)
    for method, path in [
        ("get", "/api/codex/status"),
        ("post", "/api/codex/connect"),
        ("post", "/api/codex/cancel"),
        ("post", "/api/codex/logout"),
    ]:
        assert getattr(client, method)(path).status_code == 401
    monkeypatch.setattr(main, "codex_status", lambda: {"available": True, "connected": False})
    monkeypatch.setattr(main, "codex_connect", lambda: {"pending": True, "user_code": "TEST"})
    monkeypatch.setattr(main, "codex_cancel", lambda: {"cancelled": True})
    monkeypatch.setattr(main, "codex_logout", lambda: {"connected": False})
    assert client.get("/api/codex/status", headers=ADMIN).json()["available"] is True
    assert client.post("/api/codex/connect", headers=ADMIN).json()["user_code"] == "TEST"
    assert client.post("/api/codex/cancel", headers=ADMIN).json()["cancelled"] is True
    assert client.post("/api/codex/logout", headers=ADMIN).json()["connected"] is False


def test_proxy_never_forwards_arbitrary_url_or_exposes_token(monkeypatch):
    from app import ai
    monkeypatch.setenv("NETDEPLOY_CODEX_WORKER_URL", "http://codex-worker:8788")
    monkeypatch.setenv("NETDEPLOY_WORKER_TOKEN", WORKER_TOKEN)
    calls = []
    options = []
    class FakeClient:
        def __init__(self, **kwargs):
            options.append(kwargs)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"connected": True, "access_token": "must-not-return",
                              "user_code": "ABC-123", "mode": "windows-native",
                              "verification_url": "https://auth.openai.com/codex/device"},
            )
    monkeypatch.setattr(ai.httpx, "Client", FakeClient)
    result = ai.codex_status()
    assert "access_token" not in result
    assert result["connected"] is True
    assert result["mode"] == "windows-native"
    assert calls[0][1] == "http://codex-worker:8788/account/status"
    assert calls[0][2]["headers"]["X-Worker-Token"] == WORKER_TOKEN
    assert options[0]["follow_redirects"] is False
    assert options[0]["trust_env"] is False, "Never proxy the worker auth token"
    with pytest.raises(KeyError):
        ai._worker_account_request("https://malicious.example")


class FakeHandle:
    verification_url = "https://auth.openai.com/codex/device"
    user_code = "ABCD-EFGH"
    login_id = "test-handle"
    def __init__(self, api):
        self.api = api
        self.done = threading.Event()
        self.cancelled = False
    def wait(self):
        self.done.wait(timeout=2)
        if self.cancelled:
            return SimpleNamespace(success=False)
        self.api.logged_in = True
        return SimpleNamespace(success=True)
    def cancel(self):
        self.cancelled = True
        self.done.set()


class FakeCodex:
    logged_in = False
    handle = None
    runs = []
    def __enter__(self): return self
    def __exit__(self, *_): self.close()
    def close(self): pass
    def account(self):
        return SimpleNamespace(account=SimpleNamespace(type="chatgpt" if self.logged_in else None))
    def login_chatgpt_device_code(self):
        self.handle = FakeHandle(FakeCodex)
        FakeCodex.handle = self.handle
        return self.handle
    def logout(self): FakeCodex.logged_in = False
    def thread_start(self, **kwargs):
        FakeCodex.runs.append(kwargs)
        return SimpleNamespace(run=lambda prompt: SimpleNamespace(final_response="只读排障建议"))


def _worker_client(monkeypatch):
    monkeypatch.setenv("NETDEPLOY_WORKER_TOKEN", WORKER_TOKEN)
    FakeCodex.logged_in = False
    FakeCodex.handle = None
    FakeCodex.runs = []
    fake_sdk = SimpleNamespace(
        Codex=FakeCodex,
        Sandbox=SimpleNamespace(read_only="read_only"),
        ApprovalMode=SimpleNamespace(deny_all="deny_all"),
    )
    monkeypatch.setitem(sys.modules, "openai_codex", fake_sdk)
    import app.ai_worker as worker
    importlib.reload(worker)
    return worker, TestClient(worker.app)


def test_worker_device_login_and_sandboxed_diagnosis(monkeypatch):
    worker, client = _worker_client(monkeypatch)
    assert client.get("/account/status").status_code == 401
    assert client.get("/health").status_code == 401
    assert client.get("/health", headers=WORKER).json() == {"ready": True, "mode": "docker"}
    assert client.post("/account/device-login").status_code == 401
    assert client.post("/diagnose").status_code == 401
    first = client.post("/account/device-login", headers=WORKER)
    assert first.status_code == 200
    assert first.json()["pending"] is True
    assert first.json()["user_code"] == "ABCD-EFGH"
    again = client.post("/account/device-login", headers=WORKER)
    assert again.json()["user_code"] == first.json()["user_code"]
    FakeCodex.handle.done.set()
    for _ in range(50):
        status = client.get("/account/status", headers=WORKER).json()
        if status.get("connected"): break
        time.sleep(.01)
    assert status["connected"] is True
    assert "access_token" not in status
    assert status["mode"] == "docker"
    request = {"project": "3x-ui", "status": "failed", "risk": "高",
               "issues": [], "warnings": [], "device": {"OS_ID": "debian"},
               "logs": "untrusted server log"}
    diagnosis = client.post("/diagnose", headers=WORKER, json=request)
    assert diagnosis.status_code == 200
    assert diagnosis.json()["message"] == "只读排障建议"
    assert FakeCodex.runs[-1] == {"sandbox": "read_only", "approval_mode": "deny_all"}
    assert client.post("/account/logout", headers=WORKER).json()["connected"] is False
    assert client.post("/diagnose", headers=WORKER, json=request).status_code == 409


def test_worker_cancel_and_rejects_untrusted_device_verification_url(monkeypatch):
    worker, client = _worker_client(monkeypatch)
    first = client.post("/account/device-login", headers=WORKER)
    assert first.status_code == 200
    assert client.post("/account/cancel", headers=WORKER).status_code == 200
    assert client.get("/account/status", headers=WORKER).json()["pending"] is False
    monkeypatch.setattr(FakeHandle, "verification_url", "javascript:alert(1)")
    try:
        assert client.post("/account/device-login", headers=WORKER).status_code == 503
    finally:
        monkeypatch.undo()
