"""Server lifecycle: safe deletion, editing and VPS reinstall key rotation.

Never connect to the user's VPS. All key scans are deterministic local mocks.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import paramiko
import pytest
from fastapi.testclient import TestClient

from app import main
from app.executor import SSHConfig, SSHError, SSHExecutor
from app.store import Store

HEAD = {"X-Admin-Token": "test-only-" + "a" * 32}
FACTS = {
    "OS_ID": "ubuntu", "OS_VERSION": "26.10", "ARCH": "x86_64",
    "UID": "0", "FREE_KB": "2500000", "DOCKER": "no", "COMPOSE": "no",
    "SYSTEMD": "yes", "SS_AVAILABLE": "yes", "XUI_PRESENT": "no",
    "UDP_51820": "free",
}


def scanned(host: dict, key) -> dict[str, str]:
    token = host["hostname"] if host["port"] == 22 else (
        f'[{host["hostname"]}]:{host["port"]}'
    )
    fp = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
    return {"fingerprint": fp, "key_type": key.get_name(),
            "key": f"{token} {key.get_name()} {key.get_base64()}"}


def fresh_environment(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "netdeploy.db"))
    ssh = SSHExecutor(SSHConfig(str(tmp_path / "key"), str(tmp_path / "known_hosts")))
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "executor", ssh)
    # No job execution is triggered; the API only uses the store for this flow.
    return store, ssh, TestClient(main.app)


def test_safe_host_reinstall_rotates_only_matching_endpoint_and_invalidates_plans(
    tmp_path, monkeypatch
):
    store, ssh, client = fresh_environment(tmp_path, monkeypatch)
    host = store.add_host({"name": "Tokyo VPS 1", "hostname": "203.0.113.88",
                           "port": 2222, "username": "root"})
    duplicate = store.add_host({"name": "Tokyo VPS backup", "hostname": "203.0.113.88",
                                "port": 2222, "username": "root"})
    other = store.add_host({"name": "Other VPS", "hostname": "203.0.113.88",
                            "port": 22, "username": "root"})
    old = paramiko.RSAKey.generate(1024)
    new = paramiko.RSAKey.generate(1024)
    unrelated = paramiko.RSAKey.generate(1024)
    monkeypatch.setattr(ssh, "scan_hostkey", lambda h: scanned(h, old if h["port"] == 2222 else unrelated))
    ssh.trust_hostkey(host, scanned(host, old)["fingerprint"])
    ssh.trust_hostkey(other, scanned(other, unrelated)["fingerprint"])
    baseline_other = ssh.pinned_hostkeys(other)
    old_file = (tmp_path / "known_hosts").read_text(encoding="utf-8")

    for h in (host, duplicate):
        store.save_facts(h["id"], FACTS)
    planned = store.new_job(host["id"], "3x-ui", {"trust_epoch": 0, "options": {"panel_port": 24443}})
    legacy = store.new_job(duplicate["id"], "3x-ui", {"options": {"panel_port": 24443}})
    store.set_status(legacy["id"], "completed")
    monkeypatch.setattr(ssh, "scan_hostkey", lambda h: scanned(h, new if h["port"] == 2222 else unrelated))

    scan_result = client.post(f'/api/hosts/{host["id"]}/fingerprint', headers=HEAD)
    assert scan_result.status_code == 200, scan_result.text
    info = scan_result.json()
    assert info["changed"] is True and info["shared_host_count"] == 2
    assert info["previous_fingerprints"][0]["fingerprint"] == scanned(host, old)["fingerprint"]

    body = {
        "fingerprint": scanned(host, new)["fingerprint"],
        "previous_fingerprints": [scanned(host, old)["fingerprint"]],
        "confirmed_out_of_band": True,
        "confirmation": f'REKEY {host["hostname"]}:{host["port"]}',
    }
    for change in ({"confirmed_out_of_band": False},
                   {"confirmation": "yes"},
                   {"fingerprint": "SHA256:" + "Z"*43},
                   {"previous_fingerprints": ["SHA256:" + "Z"*43]}):
        response = client.post(f'/api/hosts/{host["id"]}/rekey', headers=HEAD,
                               json={**body, **change})
        assert response.status_code in (409, 422), response.text
        assert (tmp_path / "known_hosts").read_text(encoding="utf-8") == old_file
        assert store.host(host["id"])["trust_epoch"] == 0

    # The browser generates the confirmation phrase after a verified click;
    # direct API clients must still supply the exact phrase. Nothing about
    # removing the textbox weakens the server's endpoint identity checks.
    without_phrase = {k: v for k, v in body.items() if k != "confirmation"}
    missing = client.post(f'/api/hosts/{host["id"]}/rekey',
                          headers=HEAD, json=without_phrase)
    assert missing.status_code == 422
    assert store.host(host["id"])["trust_epoch"] == 0

    changed = client.post(f'/api/hosts/{host["id"]}/rekey', headers=HEAD, json=body)
    assert changed.status_code == 200, changed.text
    assert changed.json()["affected_host_records"] == 2
    assert store.host(host["id"])["trust_epoch"] == 1
    assert store.host(duplicate["id"])["trust_epoch"] == 1
    assert store.host(other["id"])["trust_epoch"] == 0
    assert store.host(host["id"])["facts"] is None
    assert store.host(duplicate["id"])["facts"] is None
    assert store.job(planned["id"])["status"] == "invalidated"
    assert store.job(legacy["id"])["status"] == "completed"
    assert ssh.pinned_hostkeys(other) == baseline_other
    assert ssh.pinned_hostkeys(host)[0]["fingerprint"] == scanned(host, new)["fingerprint"]
    backups = list(tmp_path.glob("known_hosts.backup-*"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == old_file
    assert client.post(f'/api/jobs/{planned["id"]}/approve', headers=HEAD,
                       json={"confirmation":"x"}).status_code == 409
    assert client.get(f'/api/jobs/{legacy["id"]}/access', headers=HEAD).status_code == 409
    assert client.post(f'/api/hosts/{host["id"]}/rekey', headers=HEAD,
                       json=body).status_code == 409


def test_no_rekey_when_a_shared_endpoint_is_running(tmp_path, monkeypatch):
    store, ssh, client = fresh_environment(tmp_path, monkeypatch)
    one = store.add_host({"name": "A", "hostname": "test.example.com",
                          "port": 22, "username":"root"})
    two = store.add_host({"name": "B", "hostname": "test.example.com",
                          "port": 22, "username":"root"})
    old = paramiko.RSAKey.generate(1024)
    new = paramiko.RSAKey.generate(1024)
    monkeypatch.setattr(ssh, "scan_hostkey", lambda h: scanned(h, old))
    ssh.trust_hostkey(one, scanned(one, old)["fingerprint"])
    job = store.new_job(two["id"], "sing-box", {"trust_epoch":0})
    store.set_status(job["id"], "running")
    monkeypatch.setattr(ssh, "scan_hostkey", lambda h: scanned(h, new))
    result = client.post(f'/api/hosts/{one["id"]}/rekey', headers=HEAD,
                         json={"fingerprint":scanned(one,new)["fingerprint"],
                               "previous_fingerprints":[scanned(one,old)["fingerprint"]],
                               "confirmed_out_of_band":True,
                               "confirmation":"REKEY test.example.com:22"})
    assert result.status_code == 409
    assert ssh.pinned_hostkeys(one)[0]["fingerprint"] == scanned(one, old)["fingerprint"]
    assert store.host(one["id"])["trust_epoch"] == 0


def test_edit_and_delete_hosts_with_local_history_not_remote(tmp_path, monkeypatch):
    store, ssh, client = fresh_environment(tmp_path, monkeypatch)
    one = store.add_host({"name":"Staging","hostname":"example.test",
                          "username":"root","port":2222,"auth_mode":"password"})
    two = store.add_host({"name":"Duplicate","hostname":"example.test",
                          "username":"root","port":2222})
    ssh.set_password(one["id"],"LOCAL-TEST-PASSWORD")
    source = store.new_job(one["id"], "3x-ui", {"trust_epoch":0,"options":{"panel_port":24443}})
    rows = client.get("/api/hosts", headers=HEAD).json()
    assert any(x["id"] == one["id"] and x["job_count"] == 1 for x in rows)

    rename = client.put(f'/api/hosts/{one["id"]}', headers=HEAD, json={
        "name":"Staging renamed","hostname":one["hostname"],
        "username":one["username"],"port":one["port"]})
    assert rename.status_code == 200, rename.text
    assert rename.json()["name"] == "Staging renamed"
    assert rename.json()["credential_ready"] is True

    blocked_edit = client.put(f'/api/hosts/{one["id"]}', headers=HEAD, json={
        "name":"Staging changed IP","hostname":"another.example.com",
        "username":"root","port":2222})
    assert blocked_edit.status_code == 409

    route = f'/api/hosts/{one["id"]}'
    assert client.request("DELETE", route, json={
        "confirmation":f'DELETE VPS {one["id"]}', "delete_local_history":True}).status_code == 401
    assert client.request("DELETE", route, headers=HEAD, json={
        "confirmation":"incorrect","delete_local_history":True}).status_code == 409
    assert client.request("DELETE", route, headers=HEAD, json={
        "confirmation":f'DELETE VPS {one["id"]}', "delete_local_history":False}).status_code == 409
    removed = client.request("DELETE", route, headers=HEAD, json={
        "confirmation":f'DELETE VPS {one["id"]}', "delete_local_history":True})
    assert removed.status_code == 200, removed.text
    assert removed.json()["deleted_jobs"] == 1
    assert removed.json()["hostkey_retained"] is True
    assert store.job(source["id"]) is None
    assert store.host(one["id"]) is None
    assert store.host(two["id"]) is not None
    assert ssh.credential_ready({"id":one["id"],"auth_mode":"password"}) is False

    # Connection edits are permitted for records without jobs.
    edited = client.put(f'/api/hosts/{two["id"]}', headers=HEAD, json={
        "name":"New endpoint","hostname":"new.example.com",
        "username":"root","port":2200})
    assert edited.status_code == 200, edited.text
    assert edited.json()["trust_epoch"] == 1




def test_rekey_of_shared_known_hosts_line_preserves_other_alias(tmp_path, monkeypatch):
    from app.executor import SSHExecutor
    node_a = {"hostname":"node-a.example.com","username":"root","port":22}
    node_b = {"hostname":"node-b.example.com","username":"root","port":22}
    old_key = paramiko.RSAKey.generate(1024)
    new_key = paramiko.RSAKey.generate(1024)
    path = tmp_path / "known_hosts"
    path.write_text(
        f"node-a.example.com,node-b.example.com ssh-rsa {old_key.get_base64()}\n",
        encoding="utf-8"
    )
    executor = SSHExecutor(SSHConfig(str(tmp_path / "key"), str(path)))
    expected = scanned(node_a, old_key)["fingerprint"]
    assert executor.pinned_hostkeys(node_a)[0]["fingerprint"] == expected
    assert executor.pinned_hostkeys(node_b)[0]["fingerprint"] == expected
    monkeypatch.setattr(executor, "scan_hostkey", lambda host: scanned(host, new_key))
    updated = executor.rekey_host(node_a, scanned(node_a,new_key)["fingerprint"], [expected])
    assert updated["replaced"] is True
    assert executor.pinned_hostkeys(node_a)[0]["fingerprint"] == scanned(node_a,new_key)["fingerprint"]
    assert executor.pinned_hostkeys(node_b)[0]["fingerprint"] == expected
    original_lines = path.read_text(encoding="utf-8").splitlines()
    assert len(original_lines) == 2
    assert original_lines[0].startswith("node-b.example.com ")
    assert original_lines[1].startswith("node-a.example.com ")


def test_rekey_atomic_replace_failure_keeps_old_key(tmp_path, monkeypatch):
    from app import executor as module
    host = {"hostname":"some.example.com","username":"root","port":22}
    old_key = paramiko.RSAKey.generate(1024)
    new_key = paramiko.RSAKey.generate(1024)
    executor = SSHExecutor(SSHConfig(str(tmp_path / "key"), str(tmp_path / "known_hosts")))
    monkeypatch.setattr(executor, "scan_hostkey", lambda h: scanned(h, old_key))
    executor.trust_hostkey(host, scanned(host, old_key)["fingerprint"])
    original = (tmp_path / "known_hosts").read_bytes()
    monkeypatch.setattr(executor, "scan_hostkey", lambda h: scanned(h, new_key))
    with monkeypatch.context() as ctx:
        ctx.setattr(module.os, "replace", lambda src,dst: (_ for _ in ()).throw(OSError("test replacement failure")))
        with pytest.raises(SSHError, match="写入"):
            executor.rekey_host(host, scanned(host, new_key)["fingerprint"],
                               [scanned(host, old_key)["fingerprint"]])
    assert (tmp_path / "known_hosts").read_bytes() == original

def test_ui_prioritizes_servers_and_respects_reduced_motion():
    root = Path(__file__).resolve().parents[1]
    html = (root/"app"/"static"/"index.html").read_text(encoding="utf-8")
    js = (root/"app"/"static"/"app.js").read_text(encoding="utf-8")
    css = (root/"app"/"static"/"app-enhanced.css").read_text(encoding="utf-8")
    assert html.index('id="hosts-section"') < html.index('id="projects-section"')
    assert 'data-action="add-host"' in html.split('<section class="hero"')[0]
    for control in ("edit-host", "delete-host", "fingerprint",
                    "preflight", "prepare-rekey", "rekey-form"):
        assert control in js
    assert "prefers-reduced-motion" in css
    assert ".project:hover" in css
    assert ".btn.is-loading" in css
    assert "aria-live" in js
