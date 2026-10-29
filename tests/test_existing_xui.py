"""Existing 3X-UI must be a read-only workspace, never a zero-step install.

All tests use fake SSH responses. Nothing contacts a real VPS or certificate CA.
"""
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app import main
from app.xui_existing import (
    parse_status, status_script, public_access_script, direct_url,
)

TOKEN = "test-only-" + "a" * 32
HEAD = {"X-Admin-Token": TOKEN}
FACTS = {
    "OS_ID": "ubuntu", "OS_VERSION": "26.10", "ARCH": "x86_64",
    "UID": "0", "FREE_KB": "8000000", "DOCKER": "no", "COMPOSE": "no",
    "SYSTEMD": "yes", "SS_AVAILABLE": "yes", "UDP_51820": "free",
    "XUI_PRESENT": "yes",
}
MANAGED_LOCAL = (
    "XUI_EXISTS=yes\nXUI_SERVICE=active\nXUI_MANAGED=yes\n"
    "XUI_PORT=24443\nXUI_LISTENER=local\n"
)
MANAGED_HTTPS = MANAGED_LOCAL.replace("XUI_LISTENER=local", "XUI_LISTENER=https")
UNMANAGED = "XUI_EXISTS=yes\nXUI_SERVICE=active\nXUI_MANAGED=no\n"
CREDENTIALS = (
    "XUI_USERNAME=InitialAdmin99\nXUI_PASSWORD=InitialPassword88\n"
    "XUI_PANEL_PORT=24443\nXUI_WEB_BASE_PATH=SecretRoute123\n"
)


@pytest.mark.parametrize("text,expected", [
    ("XUI_EXISTS=no\n", {"installed": False, "port": None}),
    (UNMANAGED, {"installed": True, "managed": False, "port": None}),
    (MANAGED_LOCAL, {"installed": True, "managed": True, "access_mode": "local", "port": 24443}),
    (MANAGED_HTTPS, {"installed": True, "managed": True, "access_mode": "https", "port": 24443}),
])
def test_safe_read_only_status_parsing(text, expected):
    status = parse_status(text)
    for key, value in expected.items():
        assert status[key] == value


@pytest.mark.parametrize("bad", [
    "XUI_EXISTS=yes\nXUI_MANAGED=yes\n",
    MANAGED_LOCAL.replace("XUI_PORT=24443", "XUI_PORT=$(id)"),
    MANAGED_LOCAL.replace("XUI_PORT=24443", "XUI_PORT=65536"),
    MANAGED_LOCAL.replace("XUI_LISTENER=local", "XUI_LISTENER=unknown_but_public"),
    MANAGED_LOCAL + "XUI_PASSWORD=EXPOSED\n",
    MANAGED_LOCAL + "XUI_PORT=22\n",
    "COMMAND OUTPUT THAT IS NOT PARSEABLE",
])
def test_status_parser_rejects_injected_or_incomplete_values(bad):
    with pytest.raises(ValueError):
        parse_status(bad)


@pytest.mark.skipif(sys.platform=="win32" or shutil.which("bash") is None,
                    reason="Target remote scripts are Linux bash")
def test_existing_panel_scripts_are_valid_read_only_bash():
    for script in [
        status_script("45.32.35.195"),
        status_script("panel.example.com"),
        public_access_script("45.32.35.195", 24443),
        public_access_script("panel.example.com", 24443),
    ]:
        result = subprocess.run(["bash", "-n"], input=script, text=True,
                                capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        assert "ufw allow" not in script
        assert "apt-get" not in script
        assert "x-ui setting -listenIP" not in script
        assert "x-ui setting -reset" not in script
    status = status_script("panel.example.com")
    assert "XUI_PASSWORD=" not in status
    assert "XUI_USERNAME=" not in status
    assert "XUI_API_TOKEN=" not in status
    assert "install-result.env" in status
    assert "curl" in status


def test_status_host_identity_can_only_be_substituted_after_validation():
    payload = "example.com;touch /tmp/owned"
    script = status_script(payload)
    assert payload not in script
    with pytest.raises(ValueError):
        public_access_script(payload, 24443)


@pytest.fixture()
def mocked_vps(monkeypatch):
    from app.store import Store
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as td:
        db = Store(str(Path(td) / "panel.db"))
        observed = {"status": MANAGED_LOCAL, "access_calls": 0, "ssh_calls": 0}
        class FakeExecutor:
            def credential_ready(self,host):return True
            def password_remembered(self,id):return False
            def preflight(self,host):return dict(FACTS)
            def run(self,host,script,timeout=30):
                observed["ssh_calls"] += 1
                if "XUI_EXISTS=" in script:
                    assert "XUI_PASSWORD=" not in script
                    return observed["status"]
                if "install-result.env" in script:
                    observed["access_calls"] += 1
                    return CREDENTIALS
                raise AssertionError("Unexpected remote script")
        fake=FakeExecutor()
        monkeypatch.setattr(main,"store",db)
        monkeypatch.setattr(main,"executor",fake)
        monkeypatch.setattr(main.runner,"executor",fake)
        client=TestClient(main.app)
        host=client.post("/api/hosts",headers=HEAD,json={
            "name":"Tokyo VPS","hostname":"45.32.35.195",
            "username":"root","port":22,
        }).json()
        yield client, host, observed, db


def test_installed_panel_never_creates_an_unexecutable_approval_job(mocked_vps):
    client,host,observed,db=mocked_vps
    before=len(db.jobs())
    result=client.post("/api/jobs",headers=HEAD,json={
        "host_id":host["id"],"project":"3x-ui","panel_port":24443,"access_mode":"https",
    })
    assert result.status_code==409,result.text
    assert "已安装" in result.text
    assert len(db.jobs())==before
    assert observed["access_calls"]==0


def test_existing_panel_status_does_not_expose_password_but_explicit_access_does(mocked_vps):
    client,host,observed,db=mocked_vps
    route=f'/api/hosts/{host["id"]}/3x-ui'
    assert client.get(route).status_code==401
    info=client.get(route,headers=HEAD)
    assert info.status_code==200,info.text
    assert info.json()["installed"] is True
    assert info.json()["port"]==24443
    assert observed["access_calls"]==0
    assert "InitialPassword88" not in info.text
    assert "SecretRoute123" not in info.text
    assert "InitialPassword88" not in Path(db.path).read_bytes().decode("utf8","ignore")

    access=client.get(route+"/access",headers=HEAD)
    assert access.status_code==200,access.text
    assert access.json()["username"]=="InitialAdmin99"
    assert access.json()["password"]=="InitialPassword88"
    assert access.json()["access_mode"]=="local"
    assert access.json()["local_url"]=="http://127.0.0.1:24443/SecretRoute123"
    assert access.json()["initial_credentials_only"] is True
    assert access.json()["ssh_tunnel"]=="ssh -N -p 22 -L 24443:127.0.0.1:24443 root@45.32.35.195"
    assert access.headers["cache-control"]=="no-store"
    assert observed["access_calls"]==1
    assert "InitialPassword88" not in Path(db.path).read_bytes().decode("utf8","ignore")


def test_no_credential_recovery_without_trusted_root_only_file(mocked_vps):
    client,host,observed,db=mocked_vps
    observed["status"]=UNMANAGED
    route=f'/api/hosts/{host["id"]}/3x-ui'
    info=client.get(route,headers=HEAD)
    assert info.status_code==200
    assert info.json()["installed"] is True and info.json()["managed"] is False
    access=client.get(route+"/access",headers=HEAD)
    assert access.status_code==409
    assert "x-ui settings" in access.text
    assert observed["access_calls"]==0
    assert len(db.jobs())==0


def test_https_panel_direct_url_only_after_live_tls_verification(mocked_vps):
    client,host,observed,db=mocked_vps
    observed["status"]=MANAGED_HTTPS
    route=f'/api/hosts/{host["id"]}/3x-ui/access'
    access=client.get(route,headers=HEAD)
    assert access.status_code==200,access.text
    assert access.json()["direct_url"]=="https://45.32.35.195:24443/SecretRoute123"
    assert "ssh_tunnel" not in access.json()
    observed["status"]=MANAGED_LOCAL.replace("XUI_LISTENER=local","XUI_LISTENER=public_unverified")
    blocked=client.get(route,headers=HEAD)
    assert blocked.status_code==409
    assert observed["access_calls"]==1


def test_managed_local_panel_can_upgrade_https_without_original_job(mocked_vps):
    client,host,observed,db=mocked_vps
    job=client.post("/api/jobs",headers=HEAD,json={
        "host_id":host["id"],"project":"3x-ui-https"
    })
    assert job.status_code==200,job.text
    obj=job.json()
    assert obj["plan"]["executable"] is True
    assert len(obj["plan"]["steps"])==4
    assert "source_job_id" not in obj["plan"]["options"]
    assert obj["plan"]["options"]["panel_port"]==24443
    assert all("Official installer finished" not in x["script"] for x in obj["plan"]["steps"])
    observed["status"]=MANAGED_HTTPS
    blocked=client.post("/api/jobs",headers=HEAD,json={
        "host_id":host["id"],"project":"3x-ui-https"
    })
    assert blocked.status_code==409
