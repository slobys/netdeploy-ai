"""No-ACME NPM HTTPS termination mode for 3X-UI and S-UI.

Tests never connect to a VPS, Docker daemon, CA or external network.
"""
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app import main
from app.catalog import build_plan
from app.store import Store


FACTS = {
    "OS_ID": "debian", "OS_VERSION": "13", "UID": "0", "ARCH": "x86_64",
    "SYSTEMD": "yes", "SS_AVAILABLE": "yes", "XUI_PRESENT": "no",
    "SUI_PRESENT": "no", "FREE_KB": "3000000",
}
AUTH = {"X-Admin-Token": "test-only-" + "a" * 32}


@pytest.mark.parametrize("project,options,port", [
    ("3x-ui", {"panel_port": 24443, "access_mode": "npm"}, 24443),
    ("3x-ui", {"panel_port": 32555, "access_mode": "npm"}, 32555),
    ("s-ui", {"access_mode": "npm"}, 2095),
])
def test_npm_mode_installs_without_any_certbot_acme_or_tcp80(project, options, port):
    plan = build_plan(project, FACTS, options)
    assert plan["executable"] and plan["eligible"]
    assert len(plan["steps"]) == 5
    assert plan["options"]["access_mode"] == "npm"
    assert not set(plan["options"]) & {"tls_identity", "certificate_type", "ssh_ipv4"}
    assert plan["npm_proxy"] == {
        "scheme": "http", "host": "127.0.0.1",
        "port": port, "network_mode": "host", "websockets": project == "3x-ui",
    }
    scripts = "\n".join(s["script"] for s in plan["steps"])
    for forbidden in (
        "certbot certonly", "certbot.timer", "netdeploy-certbot-renew",
        "ACME 80", "ufw allow 80/tcp", "ufw allow "+str(port)+"/tcp",
        "--preferred-profile shortlived", "webCertFile", "webKeyFile",
        "netdeploy-xui-reload.sh", "netdeploy-sui-reload.sh",
    ):
        assert forbidden not in scripts
    assert f"127.0.0.1:{port}" in scripts
    assert '0.0.0.0:'+str(port) not in scripts
    assert "127.0.0.1" in "；".join(plan["warnings"])
    assert "network_mode: host" in "；".join(plan["warnings"])
    assert "NPM" in "；".join(plan["warnings"])
    assert "80" in "；".join(plan["warnings"])


@pytest.mark.parametrize("project,options", [
    ("3x-ui", {"panel_port": 24443, "access_mode": "npm", "tls_identity": "example.com"}),
    ("3x-ui", {"panel_port": 24443, "access_mode": "npm", "ssh_ipv4": "8.8.8.8"}),
    ("3x-ui", {"panel_port": 24443, "access_mode": "invalid"}),
    ("s-ui", {"access_mode": "npm", "tls_identity": "example.com"}),
    ("s-ui", {"access_mode": "npm", "certificate_type": "ip"}),
    ("s-ui", {"access_mode": "npm", "custom_script": "id"}),
])
def test_npm_mode_rejects_tls_options_and_unaudited_arguments(project, options):
    with pytest.raises(ValueError):
        build_plan(project, FACTS, options)


def test_existing_tls_and_secure_local_modes_unchanged():
    native_xui = build_plan("3x-ui", FACTS, {
        "panel_port": 24443, "access_mode": "https", "tls_identity": "8.8.8.8"})
    native_sui = build_plan("s-ui", FACTS, {
        "access_mode": "https", "tls_identity": "8.8.8.8"})
    local_xui = build_plan("3x-ui", FACTS, {"panel_port": 24443})
    local_sui = build_plan("s-ui", FACTS, {"access_mode": "local"})
    assert len(native_xui["steps"]) == len(native_sui["steps"]) == 9
    assert len(local_xui["steps"]) == len(local_sui["steps"]) == 5
    assert "npm_proxy" not in native_xui and "npm_proxy" not in native_sui
    assert "npm_proxy" not in local_xui and "npm_proxy" not in local_sui


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"),
                    reason="Linux Bash syntax test")
def test_npm_generated_install_scripts_parse():
    for project, options in [
        ("3x-ui", {"panel_port": 24443, "access_mode": "npm"}),
        ("s-ui", {"access_mode": "npm"}),
    ]:
        for step in build_plan(project, FACTS, options)["steps"]:
            proc = subprocess.run(["bash", "-n"], input=step["script"],
                                  text=True, capture_output=True)
            assert proc.returncode == 0, (step["label"], proc.stderr)


@pytest.fixture
def api(monkeypatch, tmp_path):
    db = Store(str(tmp_path/"npm-proxy.sqlite"))
    host = db.add_host({
        "name": "reverse-proxy-test", "hostname": "8.8.8.8",
        "username": "root", "port": 22,
    })
    class Fake:
        def __init__(self): self.commands = []
        def credential_ready(self, host): return True
        def preflight(self, host): return dict(FACTS)
        def run(self, host, script, timeout=25):
            self.commands.append(script)
            raise AssertionError("Planning must not run any installation commands")
    fake = Fake()
    monkeypatch.setattr(main, "store", db)
    monkeypatch.setattr(main, "executor", fake)
    return TestClient(main.app), db, host, fake


@pytest.mark.parametrize("project,other", [
    ("3x-ui", {"panel_port": 24443}), ("s-ui", {}),
])
def test_api_npm_mode_requires_no_domain_issues_no_cert_step_and_only_plans(api, project, other):
    client, db, host, fake = api
    result = client.post("/api/jobs", headers=AUTH,
                         json={"host_id": host["id"], "project": project,
                               "access_mode": "npm", **other})
    assert result.status_code == 200, result.text
    job = result.json()
    assert job["status"] == "planned"
    assert len(job["plan"]["steps"]) == 5
    assert job["plan"]["npm_proxy"]["host"] == "127.0.0.1"
    assert job["plan"]["options"]["access_mode"] == "npm"
    assert "tls_identity" not in job["plan"]["options"]
    assert not fake.commands
    assert db.job(job["id"])["status"] == "planned"


@pytest.mark.parametrize("project,other", [
    ("3x-ui", {"panel_port": 24443}),
    ("s-ui", {}),
])
def test_api_no_auto_approval_for_npm_install(api, project, other):
    client, db, host, _ = api
    r = client.post("/api/jobs", headers=AUTH,
                    json={"host_id": host["id"], "project": project,
                          "access_mode": "npm", **other})
    assert r.status_code == 200
    job = db.job(r.json()["id"])
    assert job["status"] == "planned"
    assert "Certbot" not in " ".join(st["label"] for st in job["plan"]["steps"])
