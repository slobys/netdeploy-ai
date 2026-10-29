"""S-UI official v1.6.6 fixed-release integration and security contracts.

Only inspect immutable shell plans and use fake executor responses.
Never connect to GitHub releases, a certificate authority or any VPS.
"""
from __future__ import annotations

import re
import os
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app import main
from app.catalog import build_plan
from app.s_ui import (
    VERSION, ARTIFACTS, steps, parse_status, parse_access,
    PORT, SUB_PORT, RESULT_FILE, LOCAL_LISTENER_GUARD, STATUS, ACCESS,
)
from app.store import Store

HEAD={"X-Admin-Token":"test-only-"+"a"*32}
FACTS={
    "OS_ID":"ubuntu","OS_VERSION":"26.10","ARCH":"x86_64",
    "UID":"0","FREE_KB":"5000000","SYSTEMD":"yes","SS_AVAILABLE":"yes",
    "SUI_PRESENT":"no","XUI_PRESENT":"no","DOCKER":"no","COMPOSE":"no",
    "UDP_51820":"free",
}
HOST={"name":"VPS","hostname":"45.32.35.195","username":"root","port":22}


def test_release_digest_and_frozen_install_steps():
    assert VERSION=="v1.6.6"
    assert len(ARTIFACTS)==3
    assert ARTIFACTS["x86_64"][1]=="6abe5756cdc1c95dfbcc2042d6f3239b230f91946f11ab0e23eaa78b42ab37e5"
    assert ARTIFACTS["aarch64"][1]=="d5b644dc138ee59ea7825c6e323e3757ea400147e930757df208a4f126a78aea"
    for arch in ("x86_64","aarch64"):
        plan=build_plan("s-ui",dict(FACTS,ARCH=arch))
        assert plan["executable"] and len(plan["steps"])==5
        assert plan["options"]=={"access_mode":"local"}
        script="\n".join(x["script"] for x in plan["steps"])
        assert "https://github.com/alireza0/s-ui/releases/download/v1.6.6/" in script
        assert f"s-ui-linux-{ARTIFACTS[arch][0]}.tar.gz" in script
        assert ARTIFACTS[arch][1] in script
        assert "sha256sum -c -" in script
        assert "sui migrate" in script  # explanation only: fresh DB should not call it\n        assert "/usr/local/s-ui/sui migrate >/dev/null" not in script\n        assert "test ! -e /usr/local/s-ui/db/s-ui.db" in script
        assert "/usr/local/s-ui/sui admin -username" in script
        assert "/usr/local/s-ui/sui setting -port 2095" in script
        assert '"webListen", "127.0.0.1"' in script
        assert '"subListen", "127.0.0.1"' in script
        assert "systemctl start s-ui" in script
        assert "SUI_LOCAL_READY" in script
        assert "tarfile.open" in script and "SUI_ARCHIVE_UNSAFE" in script
        assert "member.isdir() or member.isfile()" in script
        assert "member.mode & 0o111" in script
        assert "ufw allow" not in script
        assert "ufw disable" not in script
        assert "curl -k" not in script and "--insecure" not in script
        assert "curl | bash" not in script
        assert "latest" not in script.lower()
        assert "__ARCH__" not in script and "__DIGEST__" not in script


@pytest.mark.skipif(sys.platform=="win32" or not shutil.which("bash"),
                    reason="Generated remote scripts are Linux bash")
@pytest.mark.parametrize("arch",["x86_64","aarch64"])
def test_shell_scripts_parse_as_bash(arch):
    for step in steps(arch):
        run=subprocess.run(["bash","-n"],input=step["script"],capture_output=True,text=True)
        assert run.returncode==0,(step["label"],run.stderr)


@pytest.mark.parametrize("changed",[
    {"SUI_PRESENT":"yes"}, {"SUI_PRESENT":"unknown"},
    {"SUI_PRESENT":None}, {"OS_ID":"alpine"}, {"ARCH":"armv7l"},
    {"UID":"1000"}, {"SYSTEMD":"no"}, {"SS_AVAILABLE":"no"},
    {"FREE_KB":"599999"},
])
def test_fail_closed_if_not_verified_compatible(changed):
    plan=build_plan("s-ui",dict(FACTS,**changed))
    assert not plan["executable"]
    assert plan["steps"]==[]
    assert plan["issues"]


def test_sui_forbids_custom_arguments_or_unpinned_arch():
    with pytest.raises(ValueError):
        build_plan("s-ui",FACTS,{"panel_port":3333})
    with pytest.raises(ValueError):
        steps("mips64")


@pytest.mark.skipif(sys.platform=="win32" or not shutil.which("bash"),
                    reason="Local binding verification is a Linux bash script")
@pytest.mark.parametrize("web,sub,accepted", [
    (["127.0.0.1:2095"], ["127.0.0.1:2096"], True),
    (["0.0.0.0:2095"], ["127.0.0.1:2096"], False),
    (["127.0.0.1:2095", "0.0.0.0:2095"], ["127.0.0.1:2096"], False),
    (["127.0.0.1:2095"], ["[::]:2096"], False),
    (["127.0.0.1:2095"], [], False),
])
def test_sui_local_listener_guard_rejects_public_or_missing_socket(tmp_path, web, sub, accepted):
    bindir=tmp_path/"bin"
    bindir.mkdir()
    fake_ss=bindir/"ss"
    fake_ss.write_text(r"""#!/bin/sh
case "$2" in
  "sport = :2095") printf '%s\n' "$MOCK_WEB";;
  "sport = :2096") printf '%s\n' "$MOCK_SUB";;
  *) exit 91;;
esac
""", encoding="utf-8")
    fake_ss.chmod(0o755)
    def records(addresses):
        return "\n".join(f"LISTEN 0 128 {addr} 0.0.0.0:*" for addr in addresses)
    env={**os.environ, "PATH":str(bindir)+os.pathsep+os.environ.get("PATH",""),
         "MOCK_WEB":records(web), "MOCK_SUB":records(sub)}
    run=subprocess.run(["bash","-se"],input="set -eu\n"+LOCAL_LISTENER_GUARD+"\nsui_local_listeners_only\n",
                       text=True,capture_output=True,env=env,timeout=5)
    assert (run.returncode==0) is accepted,run.stderr
    for script in (steps("x86_64")[-1]["script"], STATUS, ACCESS):
        assert "sui_local_listeners_only" in script
        assert "2095 2096" in script


def test_readonly_status_parser_returns_no_credentials():
    yes=parse_status("SUI_INSTALLED=yes\nSUI_SERVICE=active\nSUI_MANAGED=yes\nSUI_ACCESS=local\n")
    assert yes=={"installed":True,"service":"active","managed":True,"access_mode":"local","port":2095}
    no=parse_status("SUI_INSTALLED=no\n")
    assert no["installed"] is False
    assert "password" not in repr(yes).lower()
    with pytest.raises(ValueError):
        parse_status("garbage")


def test_access_parser_rejects_unexpected_credentials():
    value="SUI_PANEL_PORT=2095\nSUI_USERNAME=nd_123456789abc\nSUI_PASSWORD="+("a"*48)+"\nSUI_WEB_BASE_PATH="+("f"*24)+"\n"
    parsed=parse_access(value,dict(HOST))
    assert parsed["local_url"]=="http://127.0.0.1:2095/"+("f"*24)+"/"
    assert parsed["ssh_tunnel"]=="ssh -N -p 22 -L 2095:127.0.0.1:2095 root@45.32.35.195"
    assert parsed["password"]=="a"*48
    with pytest.raises(ValueError):
        parse_access(value.replace("nd_123456789abc","admin"),HOST)
    with pytest.raises(ValueError):
        parse_access(value.replace("2095","2096"),HOST)
    with pytest.raises(ValueError):
        parse_access(value+"SUI_USERNAME=admin\n",HOST)
    with pytest.raises(ValueError):
        parse_access(value.replace("SUI_PASSWORD="+"a"*48,"SUI_PASSWORD=admin"),HOST)


@pytest.fixture
def sui_api(monkeypatch,tmp_path):
    db=Store(str(tmp_path/"db.sqlite"))
    h=db.add_host(HOST)
    class Fake:
        def __init__(self):self.commands=[];self.status="SUI_INSTALLED=no\n"
        def credential_ready(self,host):return True
        def preflight(self,host):return dict(FACTS)
        def run(self,host,script,timeout=25):
            self.commands.append(script)
            if "SUI_INSTALLED=" in script:return self.status
            return "SUI_PANEL_PORT=2095\nSUI_USERNAME=nd_123456789abc\nSUI_PASSWORD="+("a"*48)+"\nSUI_WEB_BASE_PATH="+("f"*24)+"\n"
    fake=Fake()
    monkeypatch.setattr(main,"store",db)
    monkeypatch.setattr(main,"executor",fake)
    return TestClient(main.app),db,h,fake


def test_install_plan_created_then_explicit_approval_not_automatic(sui_api):
    client,db,h,ssh=sui_api
    r=client.post("/api/jobs",headers=HEAD,json={"host_id":h["id"],"project":"s-ui"})
    assert r.status_code==200,r.text
    job=r.json()
    assert job["status"]=="planned" and job["plan"]["executable"] is True
    assert len(job["plan"]["steps"])==9
    assert job["plan"]["options"]["tls_identity"]=="45.32.35.195"
    assert job["plan"]["options"]["certificate_type"]=="ip"
    assert all("a"*48 not in x["script"] for x in job["plan"]["steps"])
    assert db.job(job["id"])["status"]=="planned"


def test_existing_sui_detected_and_overwrite_blocked(sui_api):
    client,db,h,ssh=sui_api
    ssh.status="SUI_INSTALLED=yes\nSUI_SERVICE=active\nSUI_MANAGED=yes\nSUI_ACCESS=local\n"
    preflight=client.post(f"/api/hosts/{h['id']}/preflight",headers=HEAD)
    assert preflight.status_code==200
    assert preflight.json()["facts"]["SUI_PRESENT"]=="no"  # fake preflight fixture
    # Now model an independent observed install on the same SSH host.
    ssh.preflight=lambda _host:{**FACTS,"SUI_PRESENT":"yes"}
    res=client.post("/api/jobs",headers=HEAD,json={"host_id":h["id"],"project":"s-ui"})
    assert res.status_code==409
    assert "已安装" in res.text or "禁止覆盖" in res.text
    status=client.get(f"/api/hosts/{h['id']}/s-ui",headers=HEAD)
    assert status.status_code==200
    assert status.json()["managed"] is True
    assert not any("SUI_PASSWORD=" in x for x in ssh.commands)


def test_sui_access_explicit_auth_and_no_secret_in_status(sui_api):
    client,db,h,ssh=sui_api
    ssh.status="SUI_INSTALLED=yes\nSUI_SERVICE=active\nSUI_MANAGED=yes\nSUI_ACCESS=local\n"
    url=f"/api/hosts/{h['id']}/s-ui/access"
    assert client.get(url).status_code==401
    status=client.get(f"/api/hosts/{h['id']}/s-ui",headers=HEAD)
    assert status.status_code==200
    assert "password" not in status.text.lower()
    access=client.get(url,headers=HEAD)
    assert access.status_code==200,access.text
    assert access.json()["username"]=="nd_123456789abc"
    assert access.json()["access_mode"]=="local"
    assert access.headers["cache-control"]=="no-store"
