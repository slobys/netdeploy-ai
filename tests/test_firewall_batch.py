"""Batch UFW port allow: complete validation, partial-result visibility, strict trust.

No test contacts a VPS, opens a firewall or invokes real ufw.
"""
import os
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app import main
from app.firewall import (
    FirewallPort, allow_ports_script, parse_firewall_batch_output,
)
from app.store import Store

HEAD={"X-Admin-Token":"test-only-"+"a"*32}


@pytest.fixture()
def batch_vps(tmp_path,monkeypatch):
    db=Store(str(tmp_path/"db.sqlite"))
    host=db.add_host({"name":"JP VPS","hostname":"203.0.113.10","username":"root","port":22})
    class SSH:
        def __init__(self):
            self.scripts=[]
            self.outcome="ND_FIREWALL=active\nND_RULE 80/tcp allowed\nND_RULE 8443/tcp allowed\n"
            self.connected=True
        def credential_ready(self,host): return self.connected
        def run(self,host,script,timeout=30):
            self.scripts.append((script,timeout))
            return self.outcome
    fake=SSH()
    monkeypatch.setattr(main,"store",db)
    monkeypatch.setattr(main,"executor",fake)
    client=TestClient(main.app)
    return client,db,host,fake


def rules():
    return [{"port":80,"protocol":"tcp"},{"port":8443,"protocol":"tcp"}]


def test_batch_one_request_with_validated_rules_and_sorted_results(batch_vps):
    client,db,host,ssh=batch_vps
    url=f"/api/hosts/{host['id']}/firewall/allow-batch"
    result=client.post(url,headers=HEAD,json={"rules":rules(),"confirmation":True})
    assert result.status_code==200,result.text
    result=result.json()
    assert result["ok"] is True
    assert result["mode"]=="active"
    assert (result["allowed"],result["failed"],result["skipped"])==(2,0,0)
    assert result["results"]==[{**x,"status":"allowed"} for x in rules()]
    assert len(ssh.scripts)==1
    script,timeout=ssh.scripts[0]
    assert script.index("ufw allow 80/tcp")<script.index("ufw allow 8443/tcp")
    assert "ufw reset" not in script
    assert "ufw disable" not in script
    assert timeout>=30


@pytest.mark.parametrize("data",[
    {"rules":[],"confirmation":True},
    {"rules":[{"port":"80","protocol":"tcp"}],"confirmation":True},
    {"rules":[{"port":80,"protocol":"xyz"}],"confirmation":True},
    {"rules":[{"port":0,"protocol":"tcp"}],"confirmation":True},
    {"rules":[{"port":65536,"protocol":"tcp"}],"confirmation":True},
    {"rules":[{"port":True,"protocol":"tcp"}],"confirmation":True},
    {"rules":[{"port":80,"protocol":"tcp"}]*21,"confirmation":True},
    {"rules":[{"port":80,"protocol":"tcp"}]*2,"confirmation":True},
])
def test_invalid_duplicate_or_oversized_batch_never_executes(batch_vps,data):
    client,db,host,ssh=batch_vps
    r=client.post(f"/api/hosts/{host['id']}/firewall/allow-batch",headers=HEAD,json=data)
    assert r.status_code==422,r.text
    assert ssh.scripts==[]


def test_batch_auth_confirmation_and_ssh_credentials(batch_vps):
    client,db,host,ssh=batch_vps
    uri=f"/api/hosts/{host['id']}/firewall/allow-batch"
    assert client.post(uri,json={"rules":rules(),"confirmation":True}).status_code==401
    assert client.post(uri,headers=HEAD,json={"rules":rules()}).status_code==409
    ssh.connected=False
    assert client.post(uri,headers=HEAD,json={"rules":rules(),"confirmation":True}).status_code==409
    assert not ssh.scripts


def test_running_job_blocks_ufw_batch(batch_vps):
    client,db,host,ssh=batch_vps
    job=db.new_job(host["id"],"sing-box",{"steps":[]})
    db.set_status(job["id"],"running")
    uri=f"/api/hosts/{host['id']}/firewall/allow-batch"
    response=client.post(uri,headers=HEAD,json={"rules":rules(),"confirmation":True})
    assert response.status_code==409
    assert ssh.scripts==[]


def test_partial_failures_visible_and_never_report_full_success(batch_vps):
    client,db,host,ssh=batch_vps
    ssh.outcome="ND_FIREWALL=active\nND_RULE 80/tcp allowed\nND_RULE 8443/tcp failed\n"
    uri=f"/api/hosts/{host['id']}/firewall/allow-batch"
    result=client.post(uri,headers=HEAD,json={"rules":rules(),"confirmation":True})
    assert result.status_code==200
    body=result.json()
    assert body["ok"] is False
    assert body["partial"] is True
    assert (body["allowed"],body["failed"])==(1,1)
    assert body["results"][1]=={"port":8443,"protocol":"tcp","status":"failed"}


@pytest.mark.parametrize("mode",["inactive","unavailable"])
def test_ufw_disabled_does_not_claim_rules_are_applied(batch_vps,mode):
    client,db,host,ssh=batch_vps
    ssh.outcome=f"ND_FIREWALL={mode}\nND_RULE 80/tcp skipped\nND_RULE 8443/tcp skipped\n"
    uri=f"/api/hosts/{host['id']}/firewall/allow-batch"
    r=client.post(uri,headers=HEAD,json={"rules":rules(),"confirmation":True})
    assert r.status_code==200,r.text
    body=r.json()
    assert body["mode"]==mode and body["allowed"]==0 and body["skipped"]==2
    assert all(x["status"]=="skipped" for x in body["results"])


@pytest.mark.parametrize("raw",[
    "some arbitrary stdout",
    "ND_FIREWALL=active\nND_RULE 80/tcp allowed\n",
    "ND_FIREWALL=active\nND_RULE 80/tcp allowed\nND_RULE 8443/tcp allowed\nND_RULE 9999/tcp allowed\n",
    "ND_FIREWALL=active\nND_RULE 80/tcp allowed\nND_RULE 80/tcp allowed\n",
    "ND_FIREWALL=active\nND_RULE 80/tcp skipped\nND_RULE 8443/tcp skipped\n",
    "ND_FIREWALL=unavailable\nND_RULE 80/tcp allowed\nND_RULE 8443/tcp allowed\n",
])
def test_malformed_or_incomplete_remote_reply_fails_closed(batch_vps,raw):
    client,db,host,ssh=batch_vps
    ssh.outcome=raw
    r=client.post(f"/api/hosts/{host['id']}/firewall/allow-batch",headers=HEAD,
                  json={"rules":rules(),"confirmation":True})
    assert r.status_code==422,r.text


@pytest.mark.skipif(sys.platform=="win32" or not shutil.which("bash"),
                    reason="Remote actions use Linux bash, not Windows")
@pytest.mark.parametrize(("mode","failed","statuses"),[
    ("active",False,["allowed","allowed"]),
    ("active",True,["allowed","failed"]),
    ("inactive",False,["skipped","skipped"]),
    ("unavailable",False,["skipped","skipped"]),
])
def test_fixed_batch_bash_with_fake_ufw(tmp_path,mode,failed,statuses):
    bin=tmp_path/"bin";bin.mkdir()
    ufw=bin/"ufw"
    ufw.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = status ]; then echo \"Status: $FAKE_UFW_MODE\"; exit 0; fi\n"
        "if [ \"$1\" = allow ]; then\n"
        "  echo \"$2\" >> \"$FAKE_RULE_LOG\"\n"
        "  if [ \"$FAKE_FAIL_SECOND\" = yes ] && [ \"$2\" = 8443/tcp ]; then exit 1; fi\n"
        "fi\n"
        "exit 0\n"
    )
    ufw.chmod(0o755)
    myid=bin/"id"
    myid.write_text("#!/bin/sh\necho 0\n");myid.chmod(0o755)
    env=os.environ.copy()
    env["PATH"]=str(bin)+os.pathsep+env.get("PATH","")
    env["FAKE_UFW_MODE"]=mode
    env["FAKE_FAIL_SECOND"]="yes" if failed else "no"
    env["FAKE_RULE_LOG"]=str(tmp_path/"executed")
    if mode=="unavailable":
        ufw.unlink()
        # Use only our fake binaries in PATH, so command -v ufw is
        # deterministically false even on a host with UFW installed.
        env["PATH"]=str(bin)
    script=allow_ports_script([FirewallPort(port=80),FirewallPort(port=8443)])
    result=subprocess.run(["/bin/bash","-se"],input=script,text=True,capture_output=True,
                          check=False,env=env,timeout=5)
    assert result.returncode==0,result.stderr
    parsed=parse_firewall_batch_output(result.stdout,[FirewallPort(port=80),FirewallPort(port=8443)])
    assert [x["status"] for x in parsed["results"]]==statuses
    if mode=="active":
        assert (tmp_path/"executed").read_text().splitlines()==["80/tcp","8443/tcp"]
    else:
        assert not (tmp_path/"executed").exists()
