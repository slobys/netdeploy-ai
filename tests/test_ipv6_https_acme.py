"""Offline IPv6 ACME/HTTPS contracts for 3X-UI and S-UI.

No VPS, DNS, CA, cloud firewall or login credentials are contacted. Real IPv6
public issuance and reachability still require independent cloud-VPS testing.
"""
from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

from app.catalog import build_plan
from app.https_upgrade import (
    https_access_script, https_steps, https_url, identify, tls_family,
)
from app.main import tls_options
from app.s_ui import ACCESS, STATUS, parse_access
from app.sui_https import https_steps as sui_https_steps
from app.xui_existing import public_access_script, status_script

V6 = "2606:4700:4700::1111"
DOMAIN = "panel.example.com"
FACTS = {
    "OS_ID": "debian", "OS_VERSION": "12", "ARCH": "x86_64",
    "UID": "0", "SYSTEMD": "yes", "SS_AVAILABLE": "yes",
    "FREE_KB": "4000000", "XUI_PRESENT": "no", "SUI_PRESENT": "no",
}


@pytest.mark.parametrize("identity,expected", [
    (V6, ("ip", V6)),
    ("2606:4700:4700:0000:0000:0000:0000:1111", ("ip", V6)),
    (DOMAIN, ("domain", DOMAIN)),
])
def test_ipv6_tls_identity_and_https_authority(identity, expected):
    assert identify(identity) == expected
    expected_url = ("https://[" + V6 + "]:24443/SecretPath"
                    if expected[0] == "ip" else "https://panel.example.com:24443/SecretPath")
    assert https_url(identity, 24443, "SecretPath") == expected_url


@pytest.mark.parametrize("identity", [
    "::", "::1", "fe80::1", "fe80::1%eth0", "fd12:3456::1",
    "ff02::1", "::ffff:8.8.8.8", "2001:db8::1", "[2606:4700:4700::1111]",
    "2606:4700:4700::1111;id",
])
def test_ipv6_tls_identity_rejects_nonpublic_or_injection(identity):
    with pytest.raises(ValueError):
        identify(identity)


@pytest.mark.parametrize("factory,port", [
    (lambda identity, kw: https_steps(identity, 24443, **kw), 24443),
    (lambda identity, kw: sui_https_steps(identity, **kw), 2095),
])
@pytest.mark.parametrize("identity,options", [
    (V6, {}),
    (DOMAIN, {"ssh_ipv6": V6}),
])
def test_ipv6_acme_script_has_pinned_address_dns_and_valid_shortlived_renewal(
    factory, port, identity, options,
):
    stages = factory(identity, options)
    assert len(stages) == 4
    pre, install, issue, activate = (stage["script"] for stage in stages)
    # Same immutable identity is used to verify the VPS's assigned IPv6 and
    # all AAAA records, then issue the certificate and check TLS on ::1.
    assert "IPV6_GUARD" in pre
    assert "socket.getaddrinfo" in pre
    assert '["ip", "-o", "-6", "addr", "show", "scope", "global"]' in pre
    assert "ND_UFW_IPV6_DISABLED" in pre
    assert "ufw allow 80/tcp" in pre
    assert "getent ahostsv4" not in pre
    assert "api.ipify.org" not in pre
    assert "IPV6=yes" in pre or "IPV6=" in pre
    assert "--http-01-address ::" in issue
    assert "--standalone" in issue
    assert "--connect-to '::[::1]:" in activate
    assert "curl -6 -g" in activate
    assert "ufw allow " + str(port) + "/tcp" in activate
    assert "https://" in activate
    assert "SUI_IPV6_PUBLIC_HTTPS_FAILED" in activate or "ND_IPV6_PUBLIC_HTTPS_FAILED" in activate
    assert "127.0.0.1" in activate, "rollback must retain loopback"
    assert " --insecure " not in issue + activate and " -k " not in issue + activate
    assert "__TLS_" not in pre + issue + activate
    assert "__IPV6_" not in pre + issue + activate
    if identity == V6:
        assert '--ip-address "' + V6 + '"' in issue
        assert "--preferred-profile shortlived" in issue
        assert "netdeploy-certbot-renew.timer" in install + issue + activate
        assert "/etc/netdeploy/letsencrypt/live/" + V6 in issue + activate
    else:
        assert "panel.example.com" in pre
        assert V6 in pre
        assert '-d "' + DOMAIN + '"' in issue
        assert "--resolve '" + DOMAIN + ":" + str(port) + ":[" + V6 + "]'" in activate
        assert "certbot.timer" in issue + activate
    if port == 2095:
        assert '("webListen", "::")' in activate
        assert "SUI_TLS_FAMILY=6" in activate
        assert "ufw allow 2096/tcp" not in activate
        assert "SUI_IPV6_PUBLIC_HTTPS_FAILED" in activate
        assert "SUI_TLS_FAMILY=6" not in pre
    else:
        assert '"$panel_cli" setting -listenIP ::' in activate
        assert "netdeploy_public_socket" in activate
        assert "ND_IPV6_PUBLIC_HTTPS_FAILED" in activate


def test_ipv6_plan_creation_and_invalid_cross_family_pins_fail_closed():
    ip_plan = build_plan("3x-ui", FACTS, {
        "panel_port": 24443, "access_mode": "https",
        **tls_options({"hostname": V6, "tls_domain": None}),
    })
    assert ip_plan["executable"] and len(ip_plan["steps"]) == 9
    assert ip_plan["options"]["certificate_type"] == "ip"
    dns_plan = build_plan("s-ui", FACTS, {
        "access_mode": "https",
        **tls_options({"hostname": V6, "tls_domain": DOMAIN}),
    })
    assert dns_plan["executable"] and len(dns_plan["steps"]) == 9
    assert dns_plan["options"]["ssh_ipv6"] == V6
    recovery = build_plan("3x-ui-https", dict(FACTS, XUI_PRESENT="yes"), {
        "panel_port": 24443, "tls_identity": DOMAIN, "ssh_ipv6": V6,
    })
    assert recovery["executable"] and len(recovery["steps"]) == 4
    sui_recovery = build_plan("s-ui-https", dict(FACTS, SUI_PRESENT="yes"), {
        "tls_identity": DOMAIN, "ssh_ipv6": V6,
    })
    assert sui_recovery["executable"] and len(sui_recovery["steps"]) == 4
    for kwargs in (
        {"ssh_ipv6": "::1"},
        {"ssh_ipv6": V6, "ssh_ipv4": "8.8.8.8"},
        {"ssh_ipv4": V6},
        {"ssh_ipv6": "8.8.8.8"},
    ):
        with pytest.raises(ValueError):
            tls_family(DOMAIN, **kwargs)
    with pytest.raises(ValueError):
        build_plan("3x-ui", FACTS, {
            "panel_port": 24443, "access_mode": "npm", "ssh_ipv6": V6,
        })


def test_ipv6_status_and_credential_retrieval_do_not_disable_tls_verification():
    script = https_access_script(V6, 24443, ipv6=True)
    assert "curl -6 -g" in script
    assert "--connect-to '::[::1]:24443'" in script
    assert "https://[" + V6 + "]:24443/" in script
    other = https_access_script(DOMAIN, 24443, ipv6=True)
    assert "https://panel.example.com:24443/" in other
    assert "curl -6 -g" in public_access_script(DOMAIN, 24443, ipv6=True)
    status = status_script(DOMAIN, ipv6=True)
    assert "__TLS_FAMILY__" not in status
    assert 'tls_flags=\'-6 -g\'' in status
    assert "https://panel.example.com:" in status
    assert "SUI_TLS_FAMILY=" in STATUS
    assert 'tls_flags=\'-6 -g\'' in STATUS
    raw = (
        "SUI_PANEL_PORT=2095\n"
        "SUI_USERNAME=nd_123456789abc\n"
        "SUI_PASSWORD=" + "a" * 48 + "\n"
        "SUI_WEB_BASE_PATH=" + "f" * 24 + "\n"
        "SUI_ACCESS_MODE=https\n"
        "SUI_TLS_IDENTITY=" + V6 + "\n"
    )
    result = parse_access(raw, {"port": 22, "username": "root", "hostname": V6})
    assert result["direct_url"] == "https://[" + V6 + "]:2095/" + "f" * 24 + "/"


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"),
                    reason="Linux remote shell syntax")
def test_generated_ipv6_ip_and_dns_shell_stages_parse():
    cases = [
        https_steps(V6, 24443), https_steps(DOMAIN, 24443, ssh_ipv6=V6),
        sui_https_steps(V6), sui_https_steps(DOMAIN, ssh_ipv6=V6),
    ]
    for scripts in cases:
        for stage in scripts:
            run = subprocess.run(["bash", "-n"], input=stage["script"], text=True,
                                 capture_output=True, timeout=12)
            assert run.returncode == 0, (stage["label"], run.stderr)
    for script in (STATUS, ACCESS, https_access_script(V6, 24443)):
        run = subprocess.run(["bash", "-n"], input=script, text=True,
                             capture_output=True, timeout=12)
        assert run.returncode == 0, run.stderr
