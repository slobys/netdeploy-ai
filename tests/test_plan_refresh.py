"""Detect previously generated fixed-script plans after a source update.

Never auto-approve or silently rewrite a previously reviewed plan.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import main
from app.catalog import build_plan
from app.store import Store

HEAD = {"X-Admin-Token": "test-only-" + "a"*32}
FACTS = {
    "OS_ID": "ubuntu", "OS_VERSION": "26.10", "ARCH": "x86_64",
    "UID": "0", "FREE_KB": "2500000", "DOCKER": "no", "COMPOSE": "no",
    "SYSTEMD": "yes", "SS_AVAILABLE": "yes", "XUI_PRESENT": "yes",
    "UDP_51820": "free",
}


def test_api_marks_stale_https_approval_before_user_clicks(tmp_path, monkeypatch):
    db = Store(str(tmp_path / "db.sqlite"))
    monkeypatch.setattr(main, "store", db)
    host = db.add_host({
        "name": "Test VPS", "hostname": "45.32.35.195",
        "port": 22, "username": "root",
    })
    db.save_facts(host["id"], FACTS)
    plan = build_plan("3x-ui-https", FACTS, {
        "panel_port": 24443, "tls_identity": "45.32.35.195",
    })
    assert plan["executable"] and len(plan["steps"]) == 4
    plan.update(hostname=host["hostname"], host_id=host["id"], trust_epoch=0)
    current = db.new_job(host["id"], "3x-ui-https", plan)

    # A real historical plan from before the pinned binary fix stored a
    # different script, despite having exactly the same IP and port.
    old_plan = build_plan("3x-ui-https", FACTS, {
        "panel_port": 24443, "tls_identity": "45.32.35.195",
    })
    old_plan["steps"][3]["script"] = old_plan["steps"][3]["script"].replace(
        '"$panel_cli" cert -webCert', 'x-ui cert -webCert'
    )
    old_plan.update(hostname=host["hostname"], host_id=host["id"], trust_epoch=0)
    old = db.new_job(host["id"], "3x-ui-https", old_plan)

    client = TestClient(main.app)
    listed = client.get("/api/jobs", headers=HEAD)
    assert listed.status_code == 200
    by_id = {record["id"]: record for record in listed.json()}
    assert by_id[current["id"]]["needs_refresh"] is False
    assert by_id[old["id"]]["needs_refresh"] is True
    single = client.get(f'/api/jobs/{old["id"]}', headers=HEAD)
    assert single.status_code == 200
    assert single.json()["needs_refresh"] is True
    # Never alter an unapproved plan in storage. User must regenerate and
    # review the new fixed script; old commands remain auditable.
    assert db.job(old["id"])["plan"]["steps"][-1]["script"] == old_plan["steps"][-1]["script"]
    assert db.job(old["id"])["status"] == "planned"
