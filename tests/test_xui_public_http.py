"""Public-HTTP 3X-UI + NPM fallback: no fake URLs, no unapproved VPS actions."""
from __future__ import annotations

import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app import main
from app.catalog import CATALOG, build_plan
from app.three_x_ui import deployment_steps
from app.xui_existing import (parse_status, public_http_access_script,
                              public_http_url, status_script)
from app.xui_public_http import http_upgrade_steps
from app.store import Store


AUTH = {"X-Admin-Token": "test-only-" + "a" * 32}
FACTS = {
    "OS_ID": "debian", "OS_VERSION": "13", "UID": "0", "ARCH": "x86_64",
    "SYSTEMD": "yes", "SS_AVAILABLE": "yes", "XUI_PRESENT": "no",
    "FREE_KB": "3000000",
}
HTTP_STATUS = (
    "XUI_EXISTS=yes\nXUI_SERVICE=active\nXUI_MANAGED=yes\n"
    "XUI_PORT=8443\nXUI_LISTENER=http\n"
)
LOCAL_STATUS = HTTP_STATUS.replace("XUI_LISTENER=http", "XUI_LISTENER=local")
CREDS = ("XUI_USERNAME=testadmin123\nXUI_PASSWORD=testpassword123\n"
         "XUI_PANEL_PORT=8443\nXUI_WEB_BASE_PATH=PanelAbc123\n")


def test_npm_new_install_actually_binds_public_http_and_stays_off_tcp80():
    a = build_plan("3x-ui", FACTS, {"panel_port": 8443, "access_mode": "npm"})
    assert a["executable"] and len(a["steps"]) == 5
    scripts = "\n".join(x["script"] for x in a["steps"])
    assert "bind_local=\"n\"" in a["steps"][2]["script"]
    assert "bind_local=\"y\"" not in a["steps"][2]["script"]
    assert "netdeploy_public_socket 8443" in a["steps"][4]["script"]
    assert "ufw allow 8443/tcp" in a["steps"][4]["script"]
    assert "ufw allow 80/tcp" not in scripts
    assert "certbot certonly" not in scripts
    assert "netdeploy-certbot-renew" not in scripts
    assert "XUI_PANEL_PORT=8443" in scripts
    assert a["npm_proxy"]["port"] == 8443
    assert "明文" in " ".join(a["warnings"])
    assert "SSL" in " ".join(a["warnings"])


def test_local_and_tls_install_recipe_remain_distinct():
    local = deployment_steps(8443)
    public = deployment_steps(8443, True)
    assert "bind_local=\"y\"" in local[2]["script"]
    assert "ufw allow 8443/tcp" not in "\n".join(s["script"] for s in local)
    assert "ufw allow 8443/tcp" in public[-1]["script"]
    assert len(local) == len(public) == 5
    with pytest.raises(ValueError):
        deployment_steps(8443, "true")


def test_verified_http_status_has_no_secrets_and_requires_socket_probe():
    result = parse_status(HTTP_STATUS)
    assert result["access_mode"] == "http"
    assert result["port"] == 8443 and result["managed"] is True
    assert "XUI_LISTENER=http" in status_script("8.8.8.8")
    assert "netdeploy_public_socket" in status_script("8.8.8.8")
    script = public_http_access_script(8443)
    assert "netdeploy_public_socket 8443" in script
    assert "http://127.0.0.1:8443/$path" in script
    assert "USERNAME|PASSWORD" in script
    assert public_http_url("8.8.8.8", 8443, "PanelAbc123") == (
        "http://8.8.8.8:8443/PanelAbc123"
    )
    for host in ("127.0.0.1", "192.168.1.1", "203.0.113.2", "example.com"):
        with pytest.raises(ValueError):
            public_http_url(host, 8443, "PanelAbc123")
    with pytest.raises(ValueError):
        public_http_url("8.8.8.8", 8443, "../../bad")


def test_existing_http_promotion_is_two_approved_stages_and_can_roll_back():
    assert CATALOG["3x-ui-http"]["internal"]
    plan = build_plan("3x-ui-http", dict(FACTS, XUI_PRESENT="yes"),
                      {"panel_port": 8443})
    assert plan["executable"] and len(plan["steps"]) == 2
    assert plan["options"] == {"panel_port": 8443}
    assert "XUI_PANEL_PORT=8443" in plan["steps"][0]["script"]
    assert "netdeploy_public_socket 8443" in plan["steps"][1]["script"]
    assert "ufw allow 8443/tcp" in plan["steps"][1]["script"]
    assert 'setting -listenIP 0.0.0.0' in plan["steps"][1]["script"]
    assert 'setting -listenIP 127.0.0.1' in plan["steps"][1]["script"]
    assert "trap rollback EXIT" in plan["steps"][1]["script"]
    assert "certbot" not in "\n".join(x["script"] for x in plan["steps"]).lower()
    assert "ufw allow 80/tcp" not in "\n".join(x["script"] for x in plan["steps"])
    for bad in ({}, {"panel_port":8443, "source_job_id":"x"},
                {"panel_port":8443, "tls_identity":"example.com"}):
        with pytest.raises(ValueError):
            build_plan("3x-ui-http", dict(FACTS, XUI_PRESENT="yes"), bad)


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                    reason="Linux Bash generated scripts")
def test_public_and_local_http_scripts_have_valid_bash_syntax():
    scripts = [*deployment_steps(8443, True), *http_upgrade_steps(8443)]
    for index, step in enumerate(scripts):
        p = subprocess.run(["bash", "-n"], input=step["script"],
                           text=True, capture_output=True)
        assert p.returncode == 0, (index, p.stderr)
    for script in (public_http_access_script(8443), status_script("8.8.8.8")):
        p = subprocess.run(["bash", "-n"], input=script,
                           text=True, capture_output=True)
        assert p.returncode == 0, p.stderr


@pytest.fixture
def api(monkeypatch, tmp_path):
    db = Store(str(tmp_path / "xui-public-http.sqlite"))
    host = db.add_host({"name":"test-vps", "hostname":"8.8.8.8",
                        "username":"root", "port":22})
    class FakeExecutor:
        def __init__(self):
            self.facts = dict(FACTS, XUI_PRESENT="yes")
            self.status = LOCAL_STATUS
            self.seen = []
        def credential_ready(self, host):
            return True
        def preflight(self, host):
            return dict(self.facts)
        def run(self, host, script, timeout=26):
            self.seen.append(script)
            if "XUI_LISTENER=" in script:
                return self.status
            if "USERNAME|PASSWORD" in script:
                return CREDS
            raise AssertionError("Read-only planning cannot run unreviewed shell")
    fake = FakeExecutor()
    monkeypatch.setattr(main, "store", db)
    monkeypatch.setattr(main, "executor", fake)
    return TestClient(main.app), db, host, fake


def test_already_installed_xui_promote_plan_requires_separate_approval(api):
    client, db, host, fake = api
    result = client.post("/api/jobs", headers=AUTH,
                         json={"host_id":host["id"], "project":"3x-ui-http"})
    assert result.status_code == 200, result.text
    job = db.job(result.json()["id"])
    assert job["status"] == "planned"
    assert len(job["plan"]["steps"]) == 2
    assert len(fake.seen) == 1
    phrase = main.runner.approval_text(job, db.host(host["id"]))
    denied = client.post(f"/api/jobs/{job['id']}/approve", headers=AUTH,
                         json={"confirmed_risk":False,"confirmation":phrase})
    assert denied.status_code == 409
    assert "明文" in denied.json()["detail"]
    assert db.job(job["id"])["status"] == "planned"


def test_public_access_only_after_verified_http_listener(api):
    client, db, host, fake = api
    url=f"/api/hosts/{host['id']}/3x-ui/access"
    for listener in ("local","public_unverified","unknown"):
        fake.status = HTTP_STATUS.replace("XUI_LISTENER=http",
                                          f"XUI_LISTENER={listener}")
        if listener == "local":
            result = client.get(url, headers=AUTH)
            assert result.status_code == 200, result.text
            assert "direct_url" not in result.json()
            assert "ssh_tunnel" in result.json()
        else:
            result = client.get(url, headers=AUTH)
            assert result.status_code == 409
    fake.status = HTTP_STATUS
    result = client.get(url, headers=AUTH)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["direct_url"] == "http://8.8.8.8:8443/PanelAbc123"
    assert body["access_mode"] == "http"
    assert "ssh_tunnel" not in body
    assert body["username"] == "testadmin123"
    assert body["password"] == "testpassword123"
