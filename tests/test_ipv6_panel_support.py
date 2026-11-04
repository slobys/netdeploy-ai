"""IPv6 VPS support for pinned SSH and safe 3X-UI/S-UI deployment modes.

The audited Certbot automation was originally IPv4-only. For IPv6 hosts the
built-in HTTPS route is intentionally blocked until an IPv6 ACME+TLS end-to-end
review; local SSH tunnel and NPM reverse proxy modes remain available.
"""
import pytest
from fastapi import HTTPException

from app.executor import validate_host
from app.main import is_ipv6_ssh, normalize_ssh_address, normalize_tls_domain, tls_options
from app.xui_existing import public_http_access_script, public_http_url
from app.three_x_ui import deployment_steps
from app.catalog import build_plan

V6 = "2606:4700:4700::1111"
V6_EXPANDED = "2606:4700:4700:0000:0000:0000:0000:1111"
FACTS = {
    "OS_ID": "debian", "OS_VERSION": "12", "UID": "0", "ARCH": "x86_64",
    "SYSTEMD": "yes", "SS_AVAILABLE": "yes", "XUI_PRESENT": "no",
    "SUI_PRESENT": "no", "FREE_KB": "1000000",
}


def test_ipv6_global_ssh_and_canonical_hostname():
    validate_host(V6, "root", 22)
    validate_host(V6_EXPANDED, "root", 2222)
    validate_host("45.32.35.195", "root", 22)
    validate_host("server.example.com", "root", 22)
    assert is_ipv6_ssh(V6)
    assert not is_ipv6_ssh("server.example.com")
    assert normalize_ssh_address(V6_EXPANDED) == V6


@pytest.mark.parametrize("address", [
    "::1", "::", "fe80::1", "fe80::1%eth0", "fd12:3456::1",
    "ff02::1", "::ffff:8.8.8.8", "[2606:4700:4700::1111]",
    "2606:4700::1111;touch/tmp/bad", "2001:db8::1",
])
def test_ipv6_rejects_private_scoped_and_malformed_ssh(address):
    with pytest.raises(ValueError):
        validate_host(address, "root", 22)


def test_ipv6_domain_can_be_saved_but_internal_acme_does_not_produce_bad_plan():
    assert normalize_tls_domain("panel.example.com", V6) == "panel.example.com"
    with pytest.raises(HTTPException) as err:
        tls_options({"hostname": V6, "tls_domain": "panel.example.com"})
    assert err.value.status_code == 422
    assert "IPv6" in str(err.value.detail)
    with pytest.raises(HTTPException):
        tls_options({"hostname": V6, "tls_domain": None})


def test_ipv6_xui_http_direct_url_brackets_and_health_check():
    assert public_http_url(V6_EXPANDED, 24443, "PanelPath") == (
        "http://[2606:4700:4700::1111]:24443/PanelPath"
    )
    script = public_http_access_script(24443, V6)
    assert "curl -6" in script and f"[{V6}]" in script
    assert "XUI_IPV6_HTTP_ACCESS_FAILED" in script
    assert "__IPV6_HTTP_HEALTH__" not in script
    assert "curl -6" not in public_http_access_script(24443)
    with pytest.raises(ValueError):
        public_http_url("fd12::1", 24443, "PanelPath")


def test_ipv6_new_xui_public_mode_requires_real_ipv6_probe():
    steps = deployment_steps(24443, public_http=True, public_ipv6=V6)
    assert len(steps) == 5
    script = steps[-1]["script"]
    assert "curl -6" in script
    assert f"http://[{V6}]:24443" in script
    assert "XUI_IPV6_HTTP_FAILED" in script
    assert "ufw allow 24443/tcp" in script
    assert not any("curl -6" in x["script"] for x in deployment_steps(24443))
    with pytest.raises(ValueError):
        deployment_steps(24443, public_http=False, public_ipv6=V6)
    with pytest.raises(ValueError):
        deployment_steps(24443, public_http=True, public_ipv6="fe80::1")


def test_ipv6_catalog_allows_audited_modes_but_not_injected_fields():
    xui = build_plan("3x-ui", FACTS, {
        "panel_port": 24443, "access_mode": "npm", "public_ipv6": V6
    })
    assert xui["eligible"] and xui["executable"]
    assert xui["options"]["public_ipv6"] == V6
    assert "curl -6" in xui["steps"][-1]["script"]
    local = build_plan("3x-ui", FACTS, {"panel_port": 24443})
    assert local["eligible"] and local["executable"]
    assert "public_ipv6" not in local["options"]

    sui_local = build_plan("s-ui", FACTS, {"access_mode": "local"})
    assert sui_local["eligible"] and sui_local["executable"]
    sui_npm = build_plan("s-ui", FACTS, {"access_mode": "npm"})
    assert sui_npm["eligible"] and sui_npm["executable"]
    assert sui_npm["npm_proxy"]["host"] == "127.0.0.1"

    with pytest.raises(ValueError):
        build_plan("3x-ui", FACTS, {"panel_port": 24443, "public_ipv6": V6})
    with pytest.raises(ValueError):
        build_plan("3x-ui", FACTS, {
            "panel_port": 24443, "access_mode": "npm", "public_ipv6": "::1"
        })
