"""Codex account integration: isolated device login, admin-only proxy, no API fallback."""
import importlib
import json
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
        ("post", "/api/codex/command"),
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


def test_panel_command_shares_only_summary_and_maps_an_allowed_target(monkeypatch):
    monkeypatch.setattr(main.store, "hosts", lambda: [
        {"id": 7, "name": "东京", "hostname": "private.example", "facts": {"SECRET": "hidden"}}
    ])
    monkeypatch.setattr(main.store, "jobs", lambda: [
        {"id": "test-job", "host_id": 7, "project": "s-ui", "status": "failed",
         "logs": "private logs", "plan": {"script": "private script"}}
    ])

    def interpret(data):
        assert data["prompt"] == "打开东京的 S-UI 部署向导"
        assert data["hosts"] == [{"id": 7, "name": "东京"}]
        assert data["jobs"] == [
            {"id": "test-job", "host_id": 7, "project": "s-ui", "status": "failed"}
        ]
        assert "deploy:s-ui-https" not in data["actions"]
        return {"action": "deploy:s-ui", "host_id": 7, "message": "请先检查部署选项"}

    monkeypatch.setattr(main, "interpret_panel_command", interpret)
    client = TestClient(main.app)
    response = client.post("/api/codex/command", headers=ADMIN,
                           json={"prompt": " 打开东京的 S-UI 部署向导 "})
    assert response.status_code == 200
    assert response.json() == {
        "message": "请先检查部署选项",
        "action": {"type": "deployment", "project": "s-ui", "host_id": 7},
    }
    assert client.post("/api/codex/command", headers=ADMIN,
                       json={"prompt": "   "}).status_code == 422


@pytest.mark.parametrize(("action", "host_id"), [
    ("approve", None), ("job:missing", None), ("deploy:s-ui-https", 1),
    ("plan:s-ui-https", 1),
    ("deploy:s-ui", 99), ("deploy:s-ui", None), ("deploy:s-ui", True),
    ("hosts", 1),
])
def test_panel_command_rejects_unauthorized_or_invalid_actions(monkeypatch, action, host_id):
    monkeypatch.setattr(main.store, "hosts", lambda: [{"id": 1, "name": "测试"}])
    monkeypatch.setattr(main.store, "jobs", lambda: [])
    monkeypatch.setattr(main, "interpret_panel_command", lambda _: {
        "action": action, "host_id": host_id, "message": "无效操作",
    })
    response = TestClient(main.app).post("/api/codex/command", headers=ADMIN,
                                         json={"prompt": "打开面板"})
    assert response.status_code == 502


def test_codex_creates_a_real_draft_then_requires_separate_approval(monkeypatch, tmp_path):
    store = main.Store(str(tmp_path / "plans.db"))
    host = store.add_host({"name": "东京 VPS", "hostname": "192.0.2.80", "port": 22, "username": "root"})
    facts = {
        "OS_ID": "ubuntu", "OS_VERSION": "24.04", "ARCH": "x86_64", "UID": "0",
        "FREE_KB": "49943920", "SYSTEMD": "yes", "XUI_PRESENT": "no", "SS_AVAILABLE": "yes",
    }
    checked = []
    started = []

    def preflight(target):
        checked.append(target["id"])
        return facts.copy()

    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main.executor, "credential_ready", lambda target: True)
    monkeypatch.setattr(main.executor, "preflight", preflight)
    monkeypatch.setattr(main.runner, "enqueue", lambda *args: started.append(args))
    monkeypatch.setattr(main, "interpret_panel_command", lambda _: {
        "action": "plan:3x-ui", "host_id": host["id"], "message": "准备方案",
    })
    client = TestClient(main.app)
    response = client.post("/api/codex/command", headers=ADMIN,
                           json={"prompt": "为东京 VPS 生成 3X-UI 部署方案"})
    assert response.status_code == 200, response.text
    job = response.json()["job"]
    assert response.json()["action"] == {"type": "job", "id": job["id"]}
    assert store.job(job["id"]) == job
    assert job["status"] == "planned"
    assert job["approved_at"] is None
    assert job["plan"]["executable"]
    assert job["plan"]["options"] == {"panel_port": 24443}
    assert job["plan"]["preflight_baseline"]["XUI_PRESENT"] == "no"
    assert checked == [host["id"]]
    assert started == []

    path = f"/api/jobs/{job['id']}/approve"
    assert client.post(path, headers=ADMIN, json={}).status_code == 409
    assert started == []
    assert client.post(path, headers=ADMIN, json={"confirmed_risk": True}).json()["status"] == "queued"
    assert len(started) == 1


@pytest.mark.parametrize(("prompt", "duplicate"), [
    ("为大阪 VPS 生成 S-UI 部署方案", False),
    ("为东京 VPS 生成 3X-UI 部署方案", False),
    ("为东京 VPS 生成 S-UI 部署方案", True),
])
def test_codex_draft_requires_a_unique_named_target_and_matching_project(monkeypatch, prompt, duplicate):
    hosts = [{"id": 7, "name": "东京 VPS"}]
    if duplicate:
        hosts.append({"id": 8, "name": "东京 VPS"})
    monkeypatch.setattr(main.store, "hosts", lambda: hosts)
    monkeypatch.setattr(main.store, "jobs", lambda: [])
    monkeypatch.setattr(main, "interpret_panel_command", lambda _: {
        "action": "plan:s-ui", "host_id": 7, "message": "准备方案",
    })
    monkeypatch.setattr(main, "create_deployment_plan", lambda *_args, **_kwargs: pytest.fail("Unexpected plan"))
    response = TestClient(main.app).post("/api/codex/command", headers=ADMIN, json={"prompt": prompt})
    assert response.status_code == 422


def test_codex_discards_preflight_if_host_changed_during_plan_generation(monkeypatch, tmp_path):
    store = main.Store(str(tmp_path / "plans.db"))
    host = store.add_host({"name": "东京 VPS", "hostname": "192.0.2.80", "port": 22, "username": "root"})

    def preflight(target):
        store.update_host(target["id"], target["name"], "192.0.2.81", 22, "root")
        return {"XUI_PRESENT": "no"}

    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main.executor, "credential_ready", lambda target: True)
    monkeypatch.setattr(main.executor, "preflight", preflight)
    monkeypatch.setattr(main, "interpret_panel_command", lambda _: {
        "action": "plan:3x-ui", "host_id": host["id"], "message": "准备方案",
    })
    response = TestClient(main.app).post("/api/codex/command", headers=ADMIN,
                                         json={"prompt": "为东京 VPS 生成 3X-UI 部署方案"})
    assert response.status_code == 409
    assert store.jobs() == []
    assert store.host(host["id"])["facts"] is None


def test_panel_worker_requires_login_and_uses_structured_ephemeral_turn(monkeypatch):
    _, client = _worker_client(monkeypatch)
    data = {
        "prompt": "打开部署任务", "hosts": [], "jobs": [], "projects": {},
        "actions": ["none", "jobs"],
    }
    assert client.post("/panel-command", json=data).status_code == 401
    assert client.post("/panel-command", headers=WORKER, json=data).status_code == 409
    FakeCodex.logged_in = True

    def start(self, **kwargs):
        assert kwargs["ephemeral"] and kwargs["sandbox"] == "read_only"
        assert kwargs["approval_mode"] == "deny_all"
        assert kwargs["config"]["features"]["shell_tool"] is False
        assert kwargs["config"]["features"]["apps"] is False

        def run(prompt, *, output_schema):
            assert json.loads(prompt) == data
            assert output_schema["properties"]["action"]["enum"] == data["actions"]
            return SimpleNamespace(final_response='{"action":"jobs","host_id":null,"message":"打开任务列表"}')

        return SimpleNamespace(run=run)

    monkeypatch.setattr(FakeCodex, "thread_start", start)
    result = client.post("/panel-command", headers=WORKER, json=data)
    assert result.status_code == 200
    assert result.json()["action"] == "jobs"
