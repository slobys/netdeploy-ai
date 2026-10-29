"""v0.3.1: deletion, opt-in localhost session, and safe SSH diagnostics."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.executor import SSHConfig, SSHError, SSHExecutor

HEAD = {"X-Admin-Token": "test-only-" + "a" * 32}


def test_delete_requires_auth_confirmation_and_preserves_vps():
    host = main.store.add_host({"name": "delete-test", "hostname": "192.0.2.200",
                                "username": "root", "port": 22})
    source = main.store.new_job(host["id"], "3x-ui", {"options": {"panel_port": 24443}})
    child = main.store.new_job(host["id"], "3x-ui-https",
                               {"options": {"source_job_id": source["id"]}})
    client = TestClient(main.app)
    path = f'/api/jobs/{source["id"]}'
    body = {"confirmation": f'DELETE {source["id"]}'}
    assert client.request("DELETE", path, json=body).status_code == 401
    assert client.request("DELETE", path, headers=HEAD,
                         json={"confirmation":"REMOVE NOW"}).status_code == 409
    # Cannot delete parent before its HTTPS dependent task.
    blocked = client.request("DELETE", path, headers=HEAD, json=body)
    assert blocked.status_code == 409
    assert "HTTPS" in blocked.text

    done = client.request("DELETE", f'/api/jobs/{child["id"]}', headers=HEAD,
                         json={"confirmation": f'DELETE {child["id"]}'})
    assert done.status_code == 200
    assert done.json()["remote_unmodified"] is True
    assert main.store.job(child["id"]) is None
    result = client.request("DELETE", path, headers=HEAD, json=body)
    assert result.status_code == 200
    assert main.store.job(source["id"]) is None
    assert main.store.host(host["id"]) is not None
    assert client.request("DELETE", path, headers=HEAD, json=body).status_code == 404


@pytest.mark.parametrize("status", ["queued", "running"])
def test_active_jobs_cannot_be_deleted(status):
    host = main.store.add_host({"name": "keep-running", "hostname": "192.0.2.201",
                                "username": "root", "port": 22})
    job = main.store.new_job(host["id"], "sing-box", {})
    main.store.set_status(job["id"], status)
    c = TestClient(main.app)
    res = c.request("DELETE", f'/api/jobs/{job["id"]}', headers=HEAD,
                   json={"confirmation": f'DELETE {job["id"]}'})
    assert res.status_code == 409
    assert main.store.job(job["id"]) is not None


@pytest.mark.parametrize("enabled", [False, True])
def test_loopback_auto_login_is_opt_in(monkeypatch, enabled):
    monkeypatch.setattr(main, "LOCAL_AUTO_LOGIN", enabled)
    c = TestClient(main.app, base_url="http://127.0.0.1:8787",
                   client=("127.0.0.1", 45100))
    headers = {"X-NetDeploy-Local":"1", "Sec-Fetch-Site":"same-origin"}
    response = c.get("/api/local-session", headers=headers)
    assert response.status_code == (200 if enabled else 403)
    if enabled:
        token = response.json()["token"]
        assert token == main.ADMIN_TOKEN
        assert c.get("/api/hosts", headers={"X-Admin-Token": token}).status_code == 200
    assert c.get("/api/local-session").status_code == 403


def test_local_auto_login_rejects_remote_rebinding_and_cross_origin(monkeypatch):
    monkeypatch.setattr(main, "LOCAL_AUTO_LOGIN", True)
    headers = {"X-NetDeploy-Local": "1"}
    localhost = TestClient(main.app, base_url="http://127.0.0.1:8787",
                           client=("127.0.0.1", 40000))
    for more in [
        {"Host": "evil.test:8787"},
        {"Origin": "https://malicious.example"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ]:
        response = localhost.get("/api/local-session", headers={**headers, **more})
        assert response.status_code == 403
        assert main.ADMIN_TOKEN not in response.text

    remote = TestClient(main.app, base_url="http://127.0.0.1:8787",
                        client=("192.0.2.15", 31001))
    res = remote.get("/api/local-session", headers=headers)
    assert res.status_code == 403
    assert main.ADMIN_TOKEN not in res.text


@pytest.mark.parametrize("problem,message", [
    ("changed", "SSH_HOST_KEY_CHANGED"),
    ("unknown", "SSH_HOST_KEY_UNTRUSTED"),
    ("handshake", "SSH_HANDSHAKE_FAILED"),
    ("password", "SSH_AUTH_FAILED"),
    ("tcp", "SSH_CONNECTION_REFUSED"),
])
def test_password_ssh_failures_classified_without_leaking_secret(monkeypatch, tmp_path, problem, message):
    class SSHException(Exception):pass
    class BadHostKeyException(SSHException):pass
    class AuthenticationException(SSHException):pass
    class FakeClient:
        def load_host_keys(self,path):pass
        def set_missing_host_key_policy(self,policy):pass
        def connect(self,**kwargs):
            exceptions={
                "changed": BadHostKeyException("changed host key"),
                "unknown": SSHException("Server 'example.com' not found in known_hosts"),
                "handshake": SSHException("unexpected packet"),
                "password": AuthenticationException("invalid credentials"),
                "tcp": ConnectionRefusedError("refused"),
            }
            raise exceptions[problem]
        def close(self):pass
    monkeypatch.setitem(sys.modules, "paramiko", types.SimpleNamespace(
        SSHClient=FakeClient, RejectPolicy=lambda:None,
        AuthenticationException=AuthenticationException,
        BadHostKeyException=BadHostKeyException, SSHException=SSHException,
    ))
    known = tmp_path / "known_hosts"
    known.write_text("example.com ssh-ed25519 AAAA\n", encoding="utf-8")
    executor = SSHExecutor(SSHConfig(str(tmp_path/"missing"), str(known)))
    executor.set_password(4, "TEST-PRIVATE-PASS-456")
    with pytest.raises(SSHError) as e:
        executor.run({"id":4,"hostname":"example.com","port":22,
                      "username":"root","auth_mode":"password"}, "echo safe")
    assert message in str(e.value)
    assert "TEST-PRIVATE-PASS-456" not in str(e.value)


def test_bootstrap_scripts_are_in_repo_without_embedding_secrets():
    base = Path(__file__).resolve().parents[1]
    quick = (base/"scripts"/"QuickStart-Windows.ps1").read_text(encoding="utf-8-sig")
    starter = (base/"scripts"/"Start-Windows.ps1").read_text(encoding="utf-8-sig")
    js = (base/"app"/"static"/"app.js").read_text(encoding="utf-8")
    assert "Update-Windows.ps1" in quick and "Start-NetDeploy.bat" in quick
    assert "NETDEPLOY_LOCAL_AUTO_LOGIN = '1'" in starter
    assert "--host 127.0.0.1" in starter
    assert "tryLocalLogin" in js and "confirmDeleteJob" in js
    assert "git reset --hard" not in quick
    assert "ssh-keyscan" not in quick
