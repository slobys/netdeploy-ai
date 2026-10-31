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
from app.dockge import IMAGE, VERSION, SOURCE_SHA, SOURCE_REPO, PORT, steps, STATUS, BINDING_GUARD, parse_status, local_access
from app.store import Store

AUTH = {"X-Admin-Token":"test-only-" + "a"*32}
FACTS = {
    "OS_ID":"debian","OS_VERSION":"13","ARCH":"x86_64","UID":"0","FREE_KB":"5000000",
    "DOCKER":"yes","COMPOSE":"yes","GIT_AVAILABLE":"yes","SS_AVAILABLE":"yes","SYSTEMD":"yes",
    "XUI_PRESENT":"no","SUI_PRESENT":"no","UDP_51820":"free",
    "DOCKGE_PRESENT":"no","DOCKGE_TCP_5001":"free",
}
HOST={"name":"Dockge test","hostname":"8.8.8.8","username":"root","port":22}


def test_reviewed_fork_source_recipe_and_local_port():
    assert VERSION=="1.5.0-apps.1" and IMAGE=="netdeploy/dockge-apps:66aec693a974"
    assert SOURCE_REPO=="https://github.com/slobys/dockge-apps.git"
    assert SOURCE_SHA=="66aec693a974bd980f632f643586deab16932531"
    assert PORT==5001
    assert CATALOG["dockge"]["deployment"]=="install"
    assert CATALOG["dockge"]["risk"]=="高"
    assert CATALOG["dockge"]["category"]=="容器"
    plan=build_plan("dockge",FACTS)
    assert plan["eligible"] and plan["executable"] and len(plan["steps"])==4
    assert plan["options"]=={}
    scripts="\n".join(stage["script"] for stage in plan["steps"])
    assert "netdeploy/dockge-apps:66aec693a974" in scripts
    assert "https://github.com/slobys/dockge-apps.git" in scripts
    assert "git -C \"$tmp\" -c protocol.version=2 fetch -q --depth 1 origin 66aec693a974bd980f632f643586deab16932531" in scripts
    assert "DOCKGE_SOURCE_REVISION_MISMATCH" in scripts
    assert "docker/Dockerfile.apps" in scripts
    assert "docker compose -f \"$root/compose.yaml\" build --pull" in scripts
    assert "louislam/dockge:1.5.0" not in scripts
    assert "docker compose" in scripts
    assert "docker pull louislam/dockge:1.5.0" not in scripts
    assert "docker compose" in scripts
    assert '127.0.0.1:5001:5001/tcp' in scripts
    assert "/var/run/docker.sock:/var/run/docker.sock" in scripts
    assert "/opt/stacks:/opt/stacks" in scripts
    assert "DOCKGE_ENABLE_CONSOLE: \"false\"" in scripts
    assert "DOCKGE_APPS_BUILD_READY" in scripts
    assert "App Center includes Nginx Proxy Manager, IT-Tools and MyIP" in scripts
    assert "DOCKGE_STACKS_DIR: /opt/stacks" in scripts
    assert 'docker compose -f "$root/compose.yaml" config -q' in scripts
    assert 'docker compose -f "$root/compose.yaml" up -d --no-build' in scripts
    assert "DOCKGE_APPS_READY" in scripts
    assert "DOCKGE_EXISTS" in scripts and "DOCKGE_PORT_BUSY" in scripts
    assert "netdeploy-dockge-apps" in scripts
    # Refuse an upstream Dockge running under a nonstandard container name.
    assert "docker ps -a --format" in steps()[0]["script"]
    assert "(louislam/dockge|dockge-apps|netdeploy/dockge-apps)" in steps()[0]["script"]
    assert "(louislam/dockge|dockge-apps|netdeploy/dockge-apps)" in STATUS
    assert "DOCKGE_PORT_UNVERIFIED" in scripts
    assert "3000000" in steps()[0]["script"] and "DOCKGE_DISK_LOW" in scripts
    assert 'docker compose -f "$root/compose.yaml" stop' in scripts
    assert not any(x in scripts for x in ("curl | bash","curl -k","--insecure","docker system prune","ufw disable","0.0.0.0:5001:5001","docker compose down","docker rm -f","docker volume rm"))
    assert not "DOCKGE_PANEL_PASSWORD" in scripts


@pytest.mark.parametrize("bad", [
    {"DOCKER":"no"}, {"DOCKER":"unknown"}, {"COMPOSE":"no"},
    {"DOCKGE_PRESENT":"yes"}, {"DOCKGE_PRESENT":"unknown"}, {"DOCKGE_PRESENT":None},
    {"DOCKGE_TCP_5001":"busy"}, {"DOCKGE_TCP_5001":"unknown"},
    {"SS_AVAILABLE":"no"}, {"OS_ID":"alpine"}, {"UID":"1000"},
    {"ARCH":"mips64"}, {"FREE_KB":"350000"}, {"FREE_KB":"900000"}, {"FREE_KB":"2700000"},
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
    assert "dockge_access_settings" in BINDING_GUARD
    assert "dockge_bind=127.0.0.1" in BINDING_GUARD
    assert "docker container inspect" in STATUS


def test_access_contains_no_generated_admin_credentials():
    result=local_access(HOST)
    assert result["local_url"]=="http://127.0.0.1:5001/"
    assert result["ssh_tunnel"]=="ssh -N -p 22 -L 5001:127.0.0.1:5001 root@8.8.8.8"
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
    ('{"5001/tcp":[{"HostIp":"127.0.0.1","HostPort":"5001"}]}','netdeploy/dockge-apps:66aec693a974',True),
    ('{"5001/tcp":[{"HostIp":"0.0.0.0","HostPort":"5001"}]}','netdeploy/dockge-apps:66aec693a974',False),
    ('{"5001/tcp":[{"HostIp":"::","HostPort":"5001"}]}','netdeploy/dockge-apps:66aec693a974',False),
    ('{"5001/tcp":[{"HostIp":"127.0.0.1","HostPort":"5001"}],"8080/tcp":[{"HostIp":"0.0.0.0","HostPort":"8080"}]}','netdeploy/dockge-apps:66aec693a974',False),
    ('{"5001/tcp":[{"HostIp":"127.0.0.1","HostPort":"5002"}]}','netdeploy/dockge-apps:66aec693a974',False),
    ('{"5001/tcp":[{"HostIp":"127.0.0.1","HostPort":"5001"}]}','louislam/dockge:1.5.0',False),
    ('{}','netdeploy/dockge-apps:66aec693a974',False),
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
    assert client.post("/api/jobs",headers=AUTH,json={"host_id":host["id"],"project":"dockge","panel_port":5001}).status_code==200
    assert client.get(f"/api/hosts/{host['id']}/dockge").status_code==401



def test_api_generates_single_approval_docker_and_dockge_plan(dockge_api):
    client, store, host, fake = dockge_api
    fake.facts = {**FACTS, "DOCKER":"no", "COMPOSE":"no",
                  "DOCKER_SETUP":"clean", "GIT_AVAILABLE":"no", "FREE_KB":"6500000"}
    response = client.post("/api/jobs", headers=AUTH, json={
        "host_id":host["id"], "project":"dockge"})
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "planned"
    assert job["plan"]["executable"]
    assert len(job["plan"]["steps"]) == 8
    assert "Docker Engine" in job["plan"]["steps"][2]["label"]
    assert "Dockge" in job["plan"]["steps"][4]["label"]
    assert not fake.seen, "Plan creation must never install Docker before approval"
    assert store.job(job["id"])["status"] == "planned"


def test_api_rejects_unsafe_existing_docker_without_touching_it(dockge_api):
    client, store, host, fake = dockge_api
    fake.facts = {**FACTS, "DOCKER":"no", "COMPOSE":"no", "DOCKER_SETUP":"blocked"}
    response = client.post("/api/jobs", headers=AUTH, json={
        "host_id":host["id"], "project":"dockge"})
    assert response.status_code == 200, response.text
    plan = response.json()["plan"]
    assert not plan["executable"]
    assert plan["steps"] == []
    assert "不完整" in "；".join(plan["issues"])
    assert not fake.seen

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
    for change in ({"DOCKER":"no"},{"COMPOSE":"no"}):
        fake.facts={**FACTS,**change}
        resp=client.post("/api/jobs",headers=AUTH,json={"host_id":host["id"],"project":"dockge"})
        assert resp.status_code==200,resp.text
        assert not resp.json()["plan"]["executable"]
        assert resp.json()["plan"]["steps"]==[]
        assert resp.json()["plan"]["issues"]

def test_optional_port_is_random_custom_and_rejects_public_without_consent(dockge_api):
    client, store, host, fake = dockge_api
    auto = client.post("/api/jobs", headers=AUTH,
                       json={"host_id":host["id"],"project":"dockge"})
    assert auto.status_code == 200, auto.text
    port = auto.json()["plan"]["options"]["panel_port"]
    assert 20000 <= port <= 59999
    assert port != host["port"]
    assert f"127.0.0.1:{port}:5001/tcp" in auto.json()["plan"]["steps"][2]["script"]

    custom = client.post("/api/jobs", headers=AUTH,
                         json={"host_id":host["id"],"project":"dockge","panel_port":31828,
                               "access_mode":"public","confirm_public":True})
    assert custom.status_code == 200, custom.text
    plan = custom.json()["plan"]
    assert plan["options"]["panel_port"] == 31828
    assert plan["options"]["access_mode"] == "public"
    assert '0.0.0.0:31828:5001/tcp' in plan["steps"][2]["script"]
    assert "DOCKGE_HOST_PORT=31828" in plan["steps"][2]["script"]
    assert "DOCKGE_BIND=0.0.0.0" in plan["steps"][2]["script"]
    assert "sport = :31828" in plan["steps"][0]["script"]
    assert "DOCKGE_APPS_READY" in plan["steps"][3]["script"]
    denied = client.post("/api/jobs",headers=AUTH,json={
        "host_id":host["id"],"project":"dockge","access_mode":"public"})
    assert denied.status_code == 422
    conflict = client.post("/api/jobs",headers=AUTH,json={
        "host_id":host["id"],"project":"dockge","panel_port":22})
    assert conflict.status_code == 422


def test_existing_managed_dockge_access_reconfiguration(dockge_api):
    client, store, host, fake = dockge_api
    fake.facts["DOCKGE_PRESENT"] = "yes"
    fake.status = ("DOCKGE_INSTALLED=yes\nDOCKGE_MANAGED=yes\n"
                   "DOCKGE_RUNNING=yes\nDOCKGE_PORT=5001\nDOCKGE_ACCESS=local\n")
    resp = client.post("/api/jobs",headers=AUTH,json={
        "host_id":host["id"],"project":"dockge-access","panel_port":45800,
        "access_mode":"public","confirm_public":True})
    assert resp.status_code == 200, resp.text
    plan = resp.json()["plan"]
    assert len(plan["steps"]) == 2
    assert "0.0.0.0:45800:5001/tcp" in plan["steps"][1]["script"]
    assert "restore" in plan["steps"][1]["script"]
    assert store.job(resp.json()["id"])["status"] == "planned"
    assert len(fake.seen) == 1, "Access task must only verify status during plan creation"
    bad = client.post("/api/jobs",headers=AUTH,json={
        "host_id":host["id"],"project":"dockge-access","access_mode":"public"})
    assert bad.status_code == 422



@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                    reason="Linux Bash syntax cannot be tested using the Windows WSL stub")
def test_remote_access_change_uses_reviewed_shell_and_rollback():
    from app.dockge import reconfigure_steps, BINDING_GUARD
    tasks = reconfigure_steps(37123, "public")
    assert len(tasks) == 2
    check, change = (x["script"] for x in tasks)
    assert "dockge_local_only" in check
    assert "sport = :37123" in check
    assert '0.0.0.0:37123:5001/tcp' in change
    assert 'trap restore EXIT' in change
    assert 'cp -p "$backup_compose"' in change
    assert 'docker compose -f "$root/compose.yaml" up -d --no-build' in change
    assert "docker system prune" not in change
    assert "docker compose down" not in change
    assert "__NEW_PORT__" not in check + change
    for stage in tasks:
        result = subprocess.run(["bash", "-n"], input=stage["script"],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

def test_remote_public_port_is_reported_as_direct_ipv4():
    from app.dockge import parse_status, local_access
    raw = "DOCKGE_INSTALLED=yes\nDOCKGE_MANAGED=yes\nDOCKGE_RUNNING=yes\nDOCKGE_PORT=44222\nDOCKGE_ACCESS=public\n"
    status = parse_status(raw)
    assert status["port"] == 44222
    assert status["access_mode"] == "public"
    url = local_access({**HOST, "hostname":"8.8.8.8"}, status)
    assert url["direct_url"] == "http://8.8.8.8:44222/"
    assert url["ssh_tunnel"] == "ssh -N -p 22 -L 44222:127.0.0.1:44222 root@8.8.8.8"
