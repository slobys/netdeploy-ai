"""v0.3.7 safety regressions: local HTTPS health, UFW toggle and panel ports.

Never connects to a VPS, CA or network appliance.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.firewall import firewall_toggle_script, FirewallToggle
from app.https_upgrade import https_steps, https_access_script
from app.xui_existing import status_script, public_access_script
from app.store import Store

HEAD = {"X-Admin-Token": "test-only-" + "a"*32}


@pytest.mark.parametrize("host", ["45.32.35.195", "panel.example.com"])
def test_https_probes_loopback_but_verify_original_identity(host):
    script = https_steps(host, 34567)[3]["script"]
    connect = f"--connect-to '{host}:34567:127.0.0.1:34567'"
    assert connect in script
    assert "https://" + host + ":34567/$web_path" in script
    assert "--noproxy '*'" in script
    assert "--proto '=https'" in script
    assert 'curl --insecure' not in script and 'curl -k ' not in script
    assert 'XUI_LISTENER_MISSING' in script
    assert 'XUI_SERVICE_FAILED' in script
    assert 'XUI_TLS_IDENTITY_FAILED' in script
    assert "XUI_LOCAL_TLS_CONNECT_FAILED" in script
    assert script.index("listener_ready=no") < script.index("tls_ready=no")
    assert "trap restore_local_listener EXIT" in script
    assert script.index("ufw allow 34567/tcp") < script.index("trap - EXIT")
    access = https_access_script(host, 34567)
    assert connect in access and "https://" + host + ":34567/$web_path" in access
    assert "--connect-to" in status_script(host)
    assert "--connect-to" in public_access_script(host, 34567)


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                    reason="Generated SSH command language is Linux bash")
def test_https_and_firewall_scripts_are_valid_bash():
    scripts = [firewall_toggle_script("enable", 2222),
               firewall_toggle_script("disable", 2222)]
    for identity in ("45.32.35.195", "panel.example.com"):
        scripts += [s["script"] for s in https_steps(identity, 34567)]
        scripts += [https_access_script(identity, 34567)]
    for script in scripts:
        proc = subprocess.run(["bash", "-n"], input=script, text=True,
                              capture_output=True)
        assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("mode,port", [
    ("enable", 2222), ("disable", 22), ("enable", 65535),
])
def test_manual_firewall_switch_is_scoped_and_preserves_ssh(mode, port):
    script = firewall_toggle_script(mode, port)
    assert 'ufw reset' not in script and 'iptables -F' not in script
    assert 'ufw delete' not in script
    assert 'cloud' in script or mode == "enable"
    if mode == "enable":
        assert f"ufw allow {port}/tcp" in script
        assert script.index(f"ufw allow {port}/tcp") < script.index("ufw --force enable")
    else:
        assert "ufw --force disable" in script
        assert "UFW_DISABLED" in script
        assert "ufw --force enable" not in script


@pytest.mark.parametrize("mode,port", [
    ("close", 22), ("enable", "22"), ("disable", True),
    ("disable", -1), ("enable", 65536),
])
def test_firewall_switch_rejects_invalid_input(mode, port):
    with pytest.raises(ValueError):
        firewall_toggle_script(mode, port)


def test_toggle_api_requires_auth_and_explicit_risk_and_stops_when_busy(
    tmp_path, monkeypatch
):
    store = Store(str(tmp_path / "db.sqlite"))
    calls = []

    class FakeSSH:
        def credential_ready(self, host): return True
        def run(self, host, script, timeout=35):
            calls.append(script)
            if "UFW_DISABLED" in script: return "UFW_DISABLED: entire VPS host firewall is inactive"
            if "UFW_ENABLED" in script: return "UFW_ENABLED: host firewall is active"
            if "FIREWALL=active" in script: return "FIREWALL=inactive"
            return "unknown"
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "executor", FakeSSH())
    c = TestClient(main.app)
    host = store.add_host({"name":"staging","hostname":"203.0.113.123",
                           "port":2222,"username":"root"})
    url = f'/api/hosts/{host["id"]}/firewall/toggle'
    body = {"mode":"disable","confirmed_risk":True}
    assert c.post(url,json=body).status_code == 401
    assert c.post(url,headers=HEAD,json={"mode":"disable"}).status_code == 409
    assert c.post(url,headers=HEAD,json={"mode":"bad","confirmed_risk":True}).status_code == 422
    assert calls == []

    running = store.new_job(host["id"], "sing-box", {"steps": []})
    store.set_status(running["id"], "running")
    assert c.post(url,headers=HEAD,json=body).status_code == 422
    assert calls == []
    store.set_status(running["id"], "failed")
    result = c.post(url,headers=HEAD,json=body)
    assert result.status_code == 200,result.text
    assert result.json()["mode"] == "inactive"
    assert "ufw --force disable" in calls[0]
    assert "ufw allow 2222/tcp" not in calls[0]


def test_frontend_high_frequency_actions_are_visible():
    js = (Path(__file__).resolve().parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
    for phrase in [
        "xui-custom-port-form", "生成安装与 HTTPS 方案",
        "host-card-delete", "关闭 VPS 本机防火墙", "重新启用 UFW",
        "apply-ufw-toggle", "data-current-status", "installed-xui",
    ]:
        assert phrase in js
    assert "if(before!==active.status" in js
    assert "createHostPlan(id,'3x-ui',port,true,String(new FormData(form).get('tls_strategy')||'https'))" in js
