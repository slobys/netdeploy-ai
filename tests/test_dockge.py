"""NetDeploy Dockge integration: immutable plan, safe port bind, read-only status.

No real VPS, Docker daemon, registry or SSH credentials involved.
"""
from __future__ import annotations

import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app import main
from app.catalog import CATALOG, build_plan
from app.dockge import IMAGE, VERSION, PORT, steps, STATUS, BINDING_GUARD, parse_status, local_access
from app.store import Store

AUTH = {"X-Admin-Token":"test-only-" + "a"*32}
FACTS = {
    "OS_ID":"debian","OS_VERSION":"13","ARCH":"x86_64","UID":"0","FREE_KB":"5000000",
    "DOCKER":"yes","COMPOSE":"yes","SS_AVAILABLE":"yes","SYSTEMD":"yes",
    "XUI_PRESENT":"no","SUI_PRESENT":"no","UDP_51820":"free",
    "DOCKGE_PRESENT":"no","DOCKGE_TCP_5001":"free",
}
HOST={"name":"Dockge test","hostname":"203.0.113.22","username":"root","port":22}


def test_official_release_recipe_and_local_port():
    assert VERSION=="1.5.0" and IMAGE=="louislam/dockge:1.5.0"
    assert PORT==5001
    assert CATALOG["dockge"]["deployment"]=="install"
    assert CATALOG["dockge"]["risk"]=="高"
    assert CATALOG["dockge"]["category"]=="容器"
    plan=build_plan("dockge",FACTS)
    assert plan["eligible"] and plan["executable"] and len(plan["steps"])==4
    assert plan["options"]=={}
    scripts="\n".join(stage["script"] for stage in plan["steps"])
    assert "louislam/dockge:1.5.0" in scripts
    assert "docker compose" in scripts
    assert "docker pull louislam/dockge:1.5.0" in scripts
    assert '127.0.0.1:5001:5001/tcp' in scripts
    assert "/var/run/docker.sock:/var/run/docker.sock" in scripts
    assert "/opt/stacks:/opt/stacks" in scripts
    assert "DOCKGE_ENABLE_CONSOLE: \"false\"" in scripts
    assert "DOCKGE_STACKS_DIR: /opt/stacks" in scripts
    assert "docker compose -f /opt/netdeploy/dockge/compose.yaml config -q" in scripts
    assert "docker compose -f /opt/netdeploy/dockge/compose.yaml up -d --no-build" in scripts
    assert "DOCKGE_LOCAL_READY" in scripts
    assert "DOCKGE_EXISTS" in scripts and "DOCKGE_PORT_BUSY" in scripts
    # Refuse an upstream Dockge running under a nonstandard container name.
    assert "docker ps -a --format" in steps()[0]["script"]
    assert "(^|/)louislam/dockge(:|@)" in steps()[0]["script"]
    assert "(^|/)louislam/dockge(:|@)" in STATUS
    assert "DOCKGE_PORT_UNVERIFIED" in scripts
    assert "1200000" in steps()[0]["script"] and "DOCKGE_DISK_LOW" in scripts
    assert "docker compose -f /opt/netdeploy/dockge/compose.yaml stop" in scripts
    assert not any(x in scripts for x in ("curl | bash","curl -k","--insecure","docker system prune","ufw disable","0.0.0.0:5001:5001","docker compose down","docker rm -f","docker volume rm"))
    assert not "DOCKGE_PANEL_PASSWORD" in scripts


@pytest.mark.parametrize("bad", [
    {"DOCKER":"no"}, {"DOCKER":"unknown"}, {"COMPOSE":"no"},
    {"DOCKGE_PRESENT":"yes"}, {"DOCKGE_PRESENT":"unknown"}, {"DOCKGE_PRESENT":None},
    {"DOCKGE_TCP_5001":"busy"}, {"DOCKGE_TCP_5001":"unknown"},
    {"SS_AVAILABLE":"no"}, {"OS_ID":"alpine"}, {"UID":"1000"},
    {"ARCH":"mips64"}, {"FREE_KB":"350000"}, {"FREE_KB":"900000"},
])
def test_dockge_incompatible_host_fails_closed(bad):
    plan=build_plan("dockge",{**FACTS,**bad})
    assert not plan["eligible"] and not plan["executable"]
    assert plan["steps"]==[] and plan["issues"]


def test_no_custom_unreviewed_install_options():
    for options in ({"port":5002},{"shell":"id"},{"panel_port":22},{"access_mode":"https"},{"env":{"DOCKGE_ENABLE_CONSOLE":"true"}}):
        with pytest.raises(ValueError):
            build_plan("dockge",FACTS,options)


def test_status_parser_only_reports_verified_local_access():
    assert parse_status("DOCKGE_INSTALLED=no\n")=={
        "installed":False,"managed":False,"service":"absent","access_mode":"unavailable","port":5001
    }
    good="DOCKGE_INSTALLED=yes\nDOCKGE_MANAGED=yes\nDOCKGE_RUNNING=yes\nDOCKGE_ACCESS=local\n"
    result=parse_status(good)
    assert result=={"installed":True,"managed":True,"service":"active","access_mode":"local","port":5001}
    for body in (
        good.replace("DOCKGE_MANAGED=yes","DOCKGE_MANAGED=no"),
        good.replace("DOCKGE_RUNNING=yes","DOCKGE_RUNNING=no"),
        good.replace("DOCKGE_ACCESS=local","DOCKGE_ACCESS=unverified"),
    ):
        assert parse_status(body)["access_mode"]=="unverified"
    for bad in ("", "DOCKGE_INSTALLED=maybe\n", "DOCKGE_INSTALLED=yes\n",
                good+"DOCKGE_MANAGED=yes\n",good.replace("DOCKGE_RUNNING=yes","DOCKGE_RUNNING=$(id)")):
        with pytest.raises(ValueError):
            parse_status(bad)
    assert "DOCKGE_ACCESS=local" in STATUS
    assert "dockge_local_only" in STATUS
    assert 'HostIp":"127.0.0.1"' in BINDING_GUARD
    assert "docker container inspect" in STATUS


def test_access_contains_no_generated_admin_credentials():
    result=local_access(HOST)
    assert result["local_url"]=="http://127.0.0.1:5001/"
    assert result["ssh_tunnel"]=="ssh -N -p 22 -L 5001:127.0.0.1:5001 root@203.0.113.22"
    assert result["access_mode"]=="local"
    assert result["first_run_setup"] is True
    assert not any(k in result for k in ("password","username","token","secret"))
    with pytest.raises(ValueError):
        local_access({**HOST,"hostname":"example.com;curl http://attacker.invalid"})


@pytest.mark.skipif(sys.platform=="win32" or not shutil.which("bash"),reason="Linux bash only")
def test_all_dockge_scripts_are_syntactically_valid():
    for stage in steps():
        r=subprocess.run(["bash","-n"],input=stage["script"],capture_output=True,text=True)
        assert r.returncode==0,(stage["label"],r.stderr)
    r=subprocess.run(["bash","-n"],input=STATUS,capture_output=True,text=True)
    assert r.returncode==0,r.stderr



@pytest.mark.skipif(sys.platform=="win32" or not shutil.which("bash"),reason="Linux Bash port guard")
@pytest.mark.parametrize("bindings,image_name,expected", [
    ('{"5001/tcp":[{"HostIp":"127.0.0.1","HostPort":"5001"}]}','louislam/dockge:1.5.0',True),
    ('{"5001/tcp":[{"HostIp":"0.0.0.0","HostPort":"5001"}]}','louislam/dockge:1.5.0',False),
    ('{"5001/tcp":[{"HostIp":"::","HostPort":"5001"}]}','louislam/dockge:1.5.0',False),
    ('{"5001/tcp":[{"HostIp":"127.0.0.1","HostPort":"5001"}],"8080/tcp":[{"HostIp":"0.0.0.0","HostPort":"8080"}]}','louislam/dockge:1.5.0',False),
    ('{"5001/tcp":[{"HostIp":"127.0.0.1","HostPort":"5002"}]}','louislam/dockge:1.5.0',False),
    ('{"5001/tcp":[{"HostIp":"127.0.0.1","HostPort":"5001"}]}','louislam/dockge:nightly',False),
    ('{}','louislam/dockge:1.5.0',False),
])
def test_real_shell_port_guard_rejects_unexpected_public_bindings(tmp_path,bindings,image_name,expected):
    import os
    fake=tmp_path/"fakebin"
    fake.mkdir()
    docker=fake/"docker"
    docker.write_text("""#!/bin/sh
case "$*" in
  *PortBindings*) printf '%s\\n' "$MOCK_BINDINGS" ;;
  *Config.Image*) printf '%s\\n' "$MOCK_IMAGE" ;;
  *) exit 99 ;;
esac
""",encoding="utf-8")
    docker.chmod(0o755)
    env={**os.environ, "PATH":str(fake)+os.pathsep+os.environ.get("PATH",""),
         "MOCK_BINDINGS":bindings, "MOCK_IMAGE":image_name}
    run=subprocess.run(["bash","-se"],input=BINDING_GUARD+"\ndockge_local_only\n",
                       capture_output=True,text=True,env=env,timeout=5)
    assert (run.returncode==0) == expected,(run.stderr,bindings)

@pytest.fixture
def dockge_api(monkeypatch,tmp_path):
    store=Store(str(tmp_path/"dockge.sqlite"))
    host=store.add_host(HOST)
    class Fake:
        def __init__(self):
            self.facts=dict(FACTS)
            self.status="DOCKGE_INSTALLED=no\n"
            self.seen=[]
        def credential_ready(self,host):return True
        def preflight(self,host):return dict(self.facts)
        def run(self,host,script,timeout=35):
            self.seen.append(script)
            if "DOCKGE_INSTALLED=" in script:
                return self.status
            raise AssertionError("unexpected remote command")
    fake=Fake()
    monkeypatch.setattr(main,"store",store)
    monkeypatch.setattr(main,"executor",fake)
    return TestClient(main.app),store,host,fake


def test_api_creates_approval_only_not_automatic_install(dockge_api):
    client,store,host,fake=dockge_api
    resp=client.post("/api/jobs",headers=AUTH,json={"host_id":host["id"],"project":"dockge"})
    assert resp.status_code==200,resp.text
    job=resp.json()
    assert job["status"]=="planned"
    assert job["plan"]["executable"] and len(job["plan"]["steps"])==4
    assert not fake.seen,"Creating a plan must not execute the Dockge install"
    assert store.job(job["id"])["status"]=="planned"
    assert client.post("/api/jobs",headers=AUTH,json={"host_id":host["id"],"project":"dockge","panel_port":5001}).status_code==422
    assert client.get(f"/api/hosts/{host['id']}/dockge").status_code==401


def test_existing_dockge_is_never_overwritten_and_status_has_no_credentials(dockge_api):
    client,store,host,fake=dockge_api
    fake.facts["DOCKGE_PRESENT"]="yes"
    fake.status="DOCKGE_INSTALLED=yes\nDOCKGE_MANAGED=yes\nDOCKGE_RUNNING=yes\nDOCKGE_ACCESS=local\n"
    create=client.post("/api/jobs",headers=AUTH,json={"host_id":host["id"],"project":"dockge"})
    assert create.status_code==409,create.text
    status=client.get(f"/api/hosts/{host['id']}/dockge",headers=AUTH)
    assert status.status_code==200
    assert status.json()["access_mode"]=="local"
    assert "password" not in status.text.lower()
    access=client.get(f"/api/hosts/{host['id']}/dockge/access",headers=AUTH)
    assert access.status_code==200,access.text
    assert access.json()["local_url"]=="http://127.0.0.1:5001/"
    assert "ssh_tunnel" in access.json()
    assert access.headers["cache-control"]=="no-store"


def test_access_rejected_if_dockge_unmanaged_or_public(dockge_api):
    client,store,host,fake=dockge_api
    url=f"/api/hosts/{host['id']}/dockge/access"
    assert client.get(url).status_code==401
    for status in (
        "DOCKGE_INSTALLED=no\n",
        "DOCKGE_INSTALLED=yes\nDOCKGE_MANAGED=no\nDOCKGE_RUNNING=yes\nDOCKGE_ACCESS=local\n",
        "DOCKGE_INSTALLED=yes\nDOCKGE_MANAGED=yes\nDOCKGE_RUNNING=yes\nDOCKGE_ACCESS=unverified\n",
        "DOCKGE_INSTALLED=yes\nDOCKGE_MANAGED=yes\nDOCKGE_RUNNING=no\nDOCKGE_ACCESS=local\n",
    ):
        fake.status=status
        resp=client.get(url,headers=AUTH)
        assert resp.status_code==409,resp.text


def test_no_docker_or_busy_port_prevents_reviewable_install(dockge_api):
    client,store,host,fake=dockge_api
    for change in ({"DOCKER":"no"},{"COMPOSE":"no"},{"DOCKGE_TCP_5001":"busy"}):
        fake.facts={**FACTS,**change}
        resp=client.post("/api/jobs",headers=AUTH,json={"host_id":host["id"],"project":"dockge"})
        assert resp.status_code==200,resp.text
        assert not resp.json()["plan"]["executable"]
        assert resp.json()["plan"]["steps"]==[]
        assert resp.json()["plan"]["issues"]
