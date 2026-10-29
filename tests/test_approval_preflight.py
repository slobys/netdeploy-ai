"""Approval-time SSH preflight must ignore benign disk drift but fail closed."""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import main

TOKEN = "test-only-" + "a" * 32
HEAD = {"X-Admin-Token": TOKEN}
SAFE = {
    "OS_ID": "ubuntu", "OS_VERSION": "26.10", "ARCH": "x86_64", "UID": "0",
    "FREE_KB": "49943920", "DOCKER": "no", "COMPOSE": "no",
    "SYSTEMD": "yes", "UDP_51820": "free", "XUI_PRESENT": "no",
    "SS_AVAILABLE": "yes",
}


@pytest.fixture()
def approval_case(monkeypatch):
    snapshot = {"current": dict(SAFE)}
    started = []

    class FakeExecutor:
        def preflight(self, host):
            return dict(snapshot["current"])

        def credential_ready(self, host):
            return True

    def fake_enqueue(job, host, confirmation):
        assert confirmation == f'DEPLOY {job["project"]} TO {host["hostname"]}'
        started.append((job, host))

    monkeypatch.setattr(main, "executor", FakeExecutor())
    monkeypatch.setattr(main.runner, "enqueue", fake_enqueue)
    client = TestClient(main.app)
    created = client.post("/api/hosts", headers=HEAD, json={
        "name": "approval-test", "hostname": "192.0.2.80",
        "port": 22, "username": "root",
    })
    assert created.status_code == 200
    host_id = created.json()["id"]
    assert client.post(f"/api/hosts/{host_id}/preflight", headers=HEAD).status_code == 200
    plan = client.post("/api/jobs", headers=HEAD, json={
        "host_id": host_id, "project": "3x-ui", "panel_port": 24443
    })
    assert plan.status_code == 200, plan.text
    job = plan.json()
    assert job["plan"]["executable"]
    assert job["plan"]["preflight_baseline"]["XUI_PRESENT"] == "no"
    assert "FREE_KB" not in job["plan"]["preflight_baseline"]

    def approve():
        return client.post(f"/api/jobs/{job['id']}/approve", headers=HEAD, json={
            "confirmation": "DEPLOY 3x-ui TO 192.0.2.80"
        })

    return client, snapshot, started, job, host_id, approve


@pytest.mark.parametrize("new_free", [
    "49943919", "49944000", "600000",
])
def test_safe_free_space_variation_does_not_block_approval(approval_case, new_free):
    client, snapshot, started, job, host_id, approve = approval_case
    snapshot["current"]["FREE_KB"] = new_free
    res = approve()
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "queued"
    assert len(started) == 1
    assert started[0][0]["id"] == job["id"]
    assert client.get("/api/hosts", headers=HEAD).json()[0]["facts"]["FREE_KB"] == new_free


@pytest.mark.parametrize("new_free", ["599999", "0", "unknown", ""])
def test_insufficient_or_unknown_free_space_stops_approval(approval_case, new_free):
    client, snapshot, started, job, host_id, approve = approval_case
    snapshot["current"]["FREE_KB"] = new_free
    res = approve()
    assert res.status_code == 409, res.text
    assert "空间" in res.text
    assert started == []
    assert main.store.job(job["id"])["status"] == "planned"
    assert main.store.host(host_id)["facts"]["FREE_KB"] == new_free


@pytest.mark.parametrize("key,value", [
    ("XUI_PRESENT", "yes"),
    ("SS_AVAILABLE", "no"),
    ("UID", "1000"),
    ("OS_ID", "alpine"),
    ("OS_VERSION", "27.04"),
    ("ARCH", "mips"),
    ("SYSTEMD", "no"),
    ("DOCKER", "yes"),  # Conservative: even other observed changes need a new plan.
])
def test_material_preflight_change_rejects_approval(approval_case, key, value):
    client, snapshot, started, job, host_id, approve = approval_case
    snapshot["current"][key] = value
    res = approve()
    assert res.status_code == 409, res.text
    assert key in res.text
    assert "重新生成" in res.text
    assert started == []
    assert main.store.job(job["id"])["status"] == "planned"
    assert main.store.host(host_id)["facts"][key] == value


@pytest.mark.parametrize("mode", ["missing", "added"])
def test_missing_or_newly_reported_safety_fact_fails_closed(approval_case, mode):
    client, snapshot, started, job, host_id, approve = approval_case
    if mode == "missing":
        snapshot["current"].pop("XUI_PRESENT")
        key = "XUI_PRESENT"
    else:
        snapshot["current"]["NEW_SECURITY_CHECK"] = None
        key = "NEW_SECURITY_CHECK"
    response = approve()
    assert response.status_code == 409
    assert key in response.text
    assert started == []


def test_refreshed_host_record_cannot_bypass_original_plan_snapshot(approval_case):
    client, snapshot, started, job, host_id, approve = approval_case
    snapshot["current"]["XUI_PRESENT"] = "yes"
    refreshed = client.post(f"/api/hosts/{host_id}/preflight", headers=HEAD)
    assert refreshed.status_code == 200
    assert refreshed.json()["facts"]["XUI_PRESENT"] == "yes"
    assert approve().status_code == 409
    assert started == []


def test_missing_legacy_plan_snapshot_requires_regeneration(approval_case):
    client, snapshot, started, job, host_id, approve = approval_case
    with sqlite3.connect(main.store.path) as connection:
        data = job["plan"]
        data.pop("preflight_baseline")
        connection.execute("UPDATE jobs SET plan_json = ? WHERE id = ?",
                           (json.dumps(data), job["id"]))
    res = approve()
    assert res.status_code == 409
    assert "旧版部署计划" in res.text
    assert started == []
