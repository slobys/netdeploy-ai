"""v0.3.4: controlled per-port firewall, APT lock waiting, and one-click approval.

No test invokes real UFW, APT, SSH or Let's Encrypt.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.catalog import build_plan
from app.firewall import PortRule, STATUS_SCRIPT, acme_ufw_script, allow_port_script
from app.https_upgrade import https_steps
from app.store import Store
from app.three_x_ui import deployment_steps

TOKEN = "test-only-" + "a"*32
HEAD = {"X-Admin-Token": TOKEN}
FACTS = {
    "OS_ID": "ubuntu", "OS_VERSION": "26.10", "ARCH": "x86_64",
    "UID": "0", "FREE_KB": "4800000",
    "DOCKER": "no", "COMPOSE": "no", "SYSTEMD": "yes",
    "SS_AVAILABLE": "yes", "XUI_PRESENT": "no", "UDP_51820": "free",
}


@pytest.mark.parametrize("port,proto", [(22,"tcp"),(80,"tcp"),(24443,"tcp"),(51820,"udp"),(65535,"udp")])
def test_port_allow_fixed_commands_are_strict_and_scoped(port,proto):
    command=allow_port_script(port,proto)
    assert f"ufw allow {port}/{proto}" in command
    assert "ufw disable" not in command
    assert "ufw reset" not in command
    assert "iptables -F" not in command
    assert "UFW_STATUS_UNKNOWN" in command


@pytest.mark.parametrize("port,proto", [("80","tcp"),(True,"tcp"),(-1,"tcp"),(0,"tcp"),
                                         (65536,"tcp"),(80,"both"),(80,"TCP"),(80,"tcp; id")])
def test_no_injection_or_bad_ports(port,proto):
    with pytest.raises(ValueError):
        allow_port_script(port,proto)


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                    reason="Target shell is Linux bash")
def test_firewall_and_install_scripts_bash_syntax():
    scripts=[STATUS_SCRIPT, allow_port_script(80,"tcp"), allow_port_script(51820,"udp"),
             acme_ufw_script()]
    scripts += [x["script"] for x in deployment_steps(24443)]
    scripts += [x["script"] for x in https_steps("45.32.35.195",24443)]
    for script in scripts:
        parsed=subprocess.run(["bash","-n"],input=script,text=True,capture_output=True)
        assert parsed.returncode == 0, parsed.stderr


def test_installer_skips_existing_dependencies_and_waits_for_apt_locks():
    initial=deployment_steps(24443)
    install=initial[1]
    assert "command -v curl" in install["script"]
    assert "test -s /etc/ssl/certs/ca-certificates.crt" in install["script"]
    assert "DPkg::Lock::Timeout=240" in install["script"]
    assert install["timeout"] > 240
    ip_cert=https_steps("45.32.35.195",24443)
    assert 'test -x "$client"' in ip_cert[1]["script"]
    assert "certbot==5.8.0" in ip_cert[1]["script"]
    assert "DPkg::Lock::Timeout=240" in ip_cert[1]["script"]
    assert ip_cert[1]["timeout"] > 240
    assert "kill -9" not in install["script"] + ip_cert[1]["script"]
    assert "rm -f /var/lib/dpkg/lock" not in install["script"] + ip_cert[1]["script"]
    domain_cert=https_steps("panel.example.com",24443)
    assert "command -v certbot" in domain_cert[1]["script"]
    assert "unattended-upgrades" in domain_cert[1]["script"]


def test_tls_workflow_opens_only_required_ufw_ports():
    stages=https_steps("45.32.35.195",24443)
    assert "ufw allow 80/tcp" in stages[0]["script"]
    assert "ufw allow 24443/tcp" in stages[3]["script"]
    assert "ufw allow 24443/tcp" not in stages[0]["script"]+stages[2]["script"]
    assert "openssl x509" in stages[2]["script"]
    assert "trap restore_local_listener EXIT" in stages[3]["script"]
    assert stages[3]["script"].index("ufw allow 24443/tcp") < stages[3]["script"].index("trap - EXIT")
    assert "ufw disable" not in "".join(x["script"] for x in stages)


def test_firewall_rest_api_one_click_only_for_authenticated_validated_port(monkeypatch,tmp_path):
    stored=Store(str(tmp_path/"netdeploy.db"))
    class FakeExecutor:
        def credential_ready(self,host):return True
        def preflight(self,host):return dict(FACTS)
        def run(self,host,script,timeout=30):
            assert "ufw" in script
            if "ufw allow" in script:
                assert "ufw allow 24443/tcp" in script
                return "UFW_ALLOWED: 24443/tcp (cloud security group must be checked separately)"
            return "FIREWALL=active\nStatus: active\n24443/tcp ALLOW Anywhere"
    executor=FakeExecutor()
    monkeypatch.setattr(main,"executor",executor)
    monkeypatch.setattr(main,"store",stored)
    client=TestClient(main.app)
    host=client.post("/api/hosts",headers=HEAD,json={
        "name":"xui","hostname":"192.0.2.99","username":"root","port":22
    }).json()
    root=f'/api/hosts/{host["id"]}/firewall'
    assert client.get(root).status_code==401
    status=client.get(root,headers=HEAD)
    assert status.status_code==200 and status.json()["status"]=="active"
    assert "云" in status.json()["cloud_notice"]
    assert client.post(root+"/allow",headers=HEAD,json={"port":24443,"protocol":"tcp"}).status_code==409
    for wrong in [{"port":"24443","protocol":"tcp","confirmation":True},
                  {"port":True,"protocol":"tcp","confirmation":True},
                  {"port":65536,"protocol":"tcp","confirmation":True},
                  {"port":24443,"protocol":"*","confirmation":True}]:
        assert client.post(root+"/allow",headers=HEAD,json=wrong).status_code==422
    done=client.post(root+"/allow",headers=HEAD,json={"port":24443,"protocol":"tcp","confirmation":True})
    assert done.status_code==200,done.text
    assert done.json()["port"]==24443
    assert "云" in done.json()["cloud_notice"]


def test_one_click_approval_keeps_strict_server_preflight_and_legacy_confirmation(monkeypatch,tmp_path):
    stored=Store(str(tmp_path/"netdeploy.db"))
    called=[]
    class FakeExecutor:
        def credential_ready(self,host):return True
        def preflight(self,host):return dict(FACTS)
    monkeypatch.setattr(main,"executor",FakeExecutor())
    monkeypatch.setattr(main,"store",stored)
    def enqueue(job,host,confirmation):
        assert confirmation==f'DEPLOY {job["project"]} TO {host["hostname"]}'
        called.append(job["id"])
    monkeypatch.setattr(main.runner,"enqueue",enqueue)
    client=TestClient(main.app)
    host=client.post("/api/hosts",headers=HEAD,json={"name":"vps","hostname":"192.0.2.98",
                                  "username":"root","port":22}).json()
    created=client.post("/api/jobs",headers=HEAD,json={"host_id":host["id"],
                      "project":"3x-ui","panel_port":24443}).json()
    job_id=created["id"]
    url=f"/api/jobs/{job_id}/approve"
    assert client.post(url,headers=HEAD,json={}).status_code==409
    assert client.post(url,headers=HEAD,json={"confirmed_risk":False}).status_code==409
    assert client.post(url,headers=HEAD,json={"confirmation":"wrong"}).status_code==409
    assert called==[]
    result=client.post(url,headers=HEAD,json={"confirmed_risk":True})
    assert result.status_code==200,result.text
    assert called==[job_id]



@pytest.mark.skipif(sys.platform=="win32" or shutil.which("bash") is None,
                    reason="This test executes isolated fake Linux commands")
@pytest.mark.parametrize("firewall_state,should_allow", [
    ("active",True),("inactive",False),("unexpected",False),
])
def test_fake_ufw_never_disables_firewall_or_opens_other_ports(
        tmp_path,firewall_state,should_allow):
    import os
    binpath=tmp_path/"bin"
    binpath.mkdir()
    (binpath/"id").write_text("#!/bin/sh\necho 0\n",encoding="utf-8")
    ufw=binpath/"ufw"
    ufw.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = status ]; then\n"
        "  echo \"Status: $UFW_FAKE_STATE\"\n"
        "elif [ \"$1\" = allow ]; then\n"
        "  printf '%s\\n' \"$*\" >> \"$UFW_FAKE_LOG\"\n"
        "else\n"
        "  exit 95\n"
        "fi\n",encoding="utf-8"
    )
    for f in [binpath/"id",ufw]:
        f.chmod(0o755)
    log=tmp_path/"ufw-actions.log"
    env=os.environ.copy()
    env["PATH"]=str(binpath)+os.pathsep+env.get("PATH","")
    env["UFW_FAKE_STATE"]=firewall_state
    env["UFW_FAKE_LOG"]=str(log)
    proc=subprocess.run(["bash","-se"],input=allow_port_script(24443,"tcp"),
                        text=True,capture_output=True,env=env,timeout=10)
    if firewall_state=="unexpected":
        assert proc.returncode==71
        assert "UFW_STATUS_UNKNOWN" in proc.stderr
    else:
        assert proc.returncode==0,proc.stderr
    if should_allow:
        assert log.read_text().strip()=="allow 24443/tcp comment NetDeploy approved port"
        assert "UFW_ALLOWED" in proc.stdout
    else:
        assert not log.exists()

def test_two_column_server_console_and_simple_plan_review():
    root=Path(__file__).resolve().parents[1]
    html=(root/"app"/"static"/"index.html").read_text(encoding="utf-8")
    js=(root/"app"/"static"/"app.js").read_text(encoding="utf-8")
    css=(root/"app"/"static"/"app-enhanced.css").read_text(encoding="utf-8")
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in css
    for label in ("安装软件","网络端口","SSH 安全","服务器设置"):
        assert label in js
    assert "function openHostConsole" in js
    assert "data-action=\"host-console\"" in js
    assert "data-action=\"host-tab\"" in js
    assert "server-allow-form" in js
    assert "data-action=\"host-check\"" in js
    assert "confirmed_risk:true" in js
    assert "请完整输入以下确认语句" not in js
    assert "plan-technical" in js
    assert "prefers-reduced-motion" in css
    assert 'ALPHA v0.3.21' in html
