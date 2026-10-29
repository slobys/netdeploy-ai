"""Pure safety tests: no real VPS, certificate authority or system vault is used."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.catalog import build_plan
from app.executor import SSHConfig, SSHExecutor
from app.https_upgrade import identify, https_access_script, https_steps, https_url
from app.os_keyring import WindowsCredentialVault

HEAD = {"X-Admin-Token": "test-only-" + "a"*32}
BASE = {"OS_ID":"ubuntu","OS_VERSION":"26.10","ARCH":"x86_64",
        "UID":"0","FREE_KB":"2800000","DOCKER":"no","COMPOSE":"no",
        "SYSTEMD":"yes","SS_AVAILABLE":"yes","XUI_PRESENT":"no","UDP_51820":"free"}


@pytest.mark.parametrize("value,expected", [
    ("8.8.8.8", ("ip","8.8.8.8")),
    ("Panel.EXAMPLE.com", ("domain","panel.example.com")),
    ("panel.example.com.", ("domain","panel.example.com")),
])
def test_tls_identity_public_ip_or_domain(value, expected):
    assert identify(value) == expected


@pytest.mark.parametrize("bad", ["127.0.0.1","192.168.1.10","10.0.0.1",
    "169.254.1.1","localhost","bad;touch /tmp/a","evil.local",
    "example.com$(id)","", "2001:db8::1"])
def test_tls_identity_rejects_private_or_shell_meta(bad):
    with pytest.raises((ValueError, AttributeError)):
        identify(bad)


@pytest.mark.parametrize("host,expected_mode", [("8.8.8.8","ip"),
                                                    ("panel.example.com","domain")])
def test_https_workflow_is_approved_only_after_local_panel_and_cert(host,expected_mode):
    new = build_plan("3x-ui", dict(BASE), {
        "panel_port":24443,"access_mode":"https","tls_identity":host
    })
    assert new["executable"]
    assert len(new["steps"]) == 9
    assert new["options"]["certificate_type"] == expected_mode
    scripts = "\n".join(step["script"] for step in new["steps"][5:])
    assert "certbot certonly" in scripts
    assert "certbot.timer" in scripts
    assert "openssl x509" in scripts
    assert "systemctl restart x-ui" in scripts
    assert "0.0.0.0" in scripts
    assert "x-ui setting -listenIP 127.0.0.1" in scripts
    assert "https://" in scripts
    assert "--preferred-profile shortlived" in scripts if expected_mode == "ip" else "-d \"panel.example.com\"" in scripts
    assert "__IDENTITY__" not in scripts and "__ISSUE_CMD__" not in scripts
    assert "trap restore_local_listener EXIT" in scripts
    assert "systemctl is-active certbot.timer" in scripts
    assert scripts.index("test -s \"/etc/letsencrypt/live") < scripts.index("x-ui setting -listenIP 0.0.0.0")

    current = dict(BASE, XUI_PRESENT="yes")
    upgrade = build_plan("3x-ui-https", current, {
        "panel_port":24443,"tls_identity":host,"source_job_id":"a"*16
    })
    assert upgrade["executable"]
    assert len(upgrade["steps"]) == 4
    assert all("install-v3" not in x["script"] for x in upgrade["steps"])


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                    reason="Linux remote shell syntax test")
def test_https_shell_syntax():
    for step in https_steps("panel.example.com",24443) + https_steps("8.8.8.8",24443):
        proc = subprocess.run(["bash","-n"],input=step["script"],text=True,capture_output=True)
        assert proc.returncode == 0, (step["label"],proc.stderr)
    proc = subprocess.run(["bash","-n"], input=https_access_script("8.8.8.8",24443),
                          text=True,capture_output=True)
    assert proc.returncode == 0


def test_https_url_strict():
    assert https_url("panel.example.com",24443,"routeABC") == "https://panel.example.com:24443/routeABC"
    with pytest.raises(ValueError):https_url("panel.example.com",24443,"../admin")


def test_vault_survives_restart_without_storing_secret_on_disk(tmp_path):
    class FakeWindowsVault:
        available=True
        memory={}
        def set(self,id,password): self.memory[id] = password
        def get(self,id): return self.memory.get(id)
        def delete(self,id): self.memory.pop(id,None)

    vault=FakeWindowsVault()
    known=tmp_path/"known_hosts"
    ex=SSHExecutor(SSHConfig(str(tmp_path/"key"),str(known)))
    ex.vault=vault
    ex.set_password(9,"NotInSQLite!342",remember=True)
    assert ex.password_remembered(9)
    fresh=SSHExecutor(SSHConfig(str(tmp_path/"key"),str(known)))
    fresh.vault=vault
    assert fresh.credential_ready({"id":9,"auth_mode":"password"})
    assert fresh._password(9) == "NotInSQLite!342"
    assert not (tmp_path/"known_hosts").exists()
    fresh.set_password(9,"TemporaryNewPwd",remember=False)
    assert not fresh.password_remembered(9)
    newer=SSHExecutor(SSHConfig(str(tmp_path/"key"),str(known)))
    newer.vault=vault
    assert not newer.credential_ready({"id":9,"auth_mode":"password"})


def test_https_existing_upgrade_api_and_secret_omission(monkeypatch):
    facts=dict(BASE)
    class FakeSSH:
        vault=type("Vault",(),{"available":False})()
        def credential_ready(self,host):return True
        def preflight(self,host):return dict(facts)
        def password_remembered(self,id):return False
        def run(self,host,script,timeout=30):
            assert "certbot.timer" in script
            assert "checkhost" in script
            return ("XUI_USERNAME=UserAdmin88\nXUI_PASSWORD=VerySecretPwd123\n"
                    "XUI_PANEL_PORT=24443\nXUI_WEB_BASE_PATH=SecretRoute123\n")
    fake=FakeSSH()
    monkeypatch.setattr(main,"executor",fake)
    monkeypatch.setattr(main.runner,"executor",fake)
    c=TestClient(main.app)
    host=c.post("/api/hosts",headers=HEAD,json={
        "hostname":"panel.example.com","port":22,"username":"root","name":"mock-ssl-vps"
    }).json()
    assert host["id"]
    source=c.post("/api/jobs",headers=HEAD,json={"host_id":host["id"],
                      "project":"3x-ui","panel_port":24443}).json()
    assert len(source["plan"]["steps"]) == 5
    main.store.set_status(source["id"],"completed")
    facts["XUI_PRESENT"]="yes"
    assert c.post("/api/jobs",headers=HEAD,json={"host_id":host["id"],
                   "project":"3x-ui-https"}).status_code==422
    upgrade=c.post("/api/jobs",headers=HEAD,json={"host_id":host["id"],
                  "project":"3x-ui-https","source_job_id":source["id"]})
    assert upgrade.status_code==200,upgrade.text
    task=upgrade.json()
    assert task["plan"]["executable"]
    assert task["plan"]["options"]["tls_identity"]=="panel.example.com"
    assert len(task["plan"]["steps"])==4
    main.store.set_status(task["id"],"completed")
    assert c.get(f"/api/jobs/{source['id']}/access").status_code==401
    access=c.get(f"/api/jobs/{source['id']}/access",headers=HEAD)
    assert access.status_code==200,access.text
    assert access.json()["direct_url"]=="https://panel.example.com:24443/SecretRoute123"
    assert access.headers["cache-control"]=="no-store"
    for obj in [c.get("/api/jobs",headers=HEAD).text,c.get("/api/hosts",headers=HEAD).text,
                Path(main.store.path).read_bytes().decode("utf8","ignore")]:
        assert "VerySecretPwd123" not in obj


def test_https_existing_panel_partial_initial_install_is_upgradeable(monkeypatch):
    facts=dict(BASE)
    class SSHStub:
        vault=type("Vault",(),{"available":False})()
        def credential_ready(self,h):return True
        def preflight(self,h):return dict(facts)
        def password_remembered(self,id):return False
    fake=SSHStub()
    monkeypatch.setattr(main,"executor",fake)
    c=TestClient(main.app)
    host=c.post("/api/hosts",headers=HEAD,json={
        "hostname":"8.8.8.8","username":"root","port":22,"name":"insecure-test-only"
    }).json()
    source=c.post("/api/jobs",headers=HEAD,json={
        "host_id":host["id"],"project":"3x-ui","access_mode":"https"
    }).json()
    assert source["plan"]["executable"]
    assert len(source["plan"]["steps"])==9
    main.store.set_status(source["id"],"partial")
    facts["XUI_PRESENT"]="yes"
    plan=c.post("/api/jobs",headers=HEAD,json={
        "host_id":host["id"],"project":"3x-ui-https","source_job_id":source["id"]
    })
    assert plan.status_code==200,plan.text
    assert plan.json()["plan"]["executable"]
    assert len(plan.json()["plan"]["steps"])==4


def test_vault_backend_fail_closed_on_linux(tmp_path, monkeypatch):
    from app import os_keyring
    monkeypatch.setattr(os_keyring.sys,"platform","linux")
    v=WindowsCredentialVault(str(tmp_path))
    assert not v.available
    assert v.get(1) is None
    with pytest.raises(os_keyring.VaultUnavailable):
        v.set(1,"pw")


def test_frontend_has_independent_copy_buttons():
    js=(Path(__file__).resolve().parents[1]/"app"/"static"/"app.js").read_text()
    for action in ("copy-xui-url","copy-xui-username","copy-xui-password","xui-upgrade"):
        assert action in js
