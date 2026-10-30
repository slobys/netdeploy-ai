"""Certbot diagnostics must be useful without leaking ACME challenge tokens.

All certificate commands run against a fake local binary; never call CA or
the user's VPS from this test suite.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.https_upgrade import https_steps
from app.certbot_runtime import IP_CERTBOT_BIN


@pytest.mark.parametrize("host,type_label,flag", [
    ("45.32.35.195", "IP", '--ip-address "45.32.35.195"'),
    ("panel.example.com", "域名", '-d "panel.example.com"'),
])
def test_tls_type_and_certbot_args_are_derived_from_host(host,type_label,flag):
    stages = https_steps(host, 24443)
    assert len(stages) == 4
    assert type_label in stages[0]["label"]
    assert flag in stages[2]["script"]
    if type_label == "IP":
        assert "--preferred-profile shortlived" in stages[2]["script"]
        assert '-d "45.32.35.195"' not in stages[2]["script"]
    else:
        assert "--ip-address" not in stages[2]["script"]
    assert "LE_HTTP01_UNREACHABLE" in stages[2]["script"]
    assert "LE_RATE_LIMIT" in stages[2]["script"]
    assert "LE_UNCLASSIFIED" in stages[2]["script"]
    assert "reuse_certificate" in stages[2]["script"]
    assert 'x-ui setting -listenIP 0.0.0.0' not in stages[2]["script"]
    assert '"$panel_cli" setting -listenIP 0.0.0.0' in stages[3]["script"]


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                    reason="Need Linux bash to run fake Certbot; never calls ACME")
@pytest.mark.parametrize("fake_error,expected_classification", [
    ("Detail: Timeout during connect (likely firewall problem)", "LE_HTTP01_UNREACHABLE"),
    ("Problem binding to port 80: Address already in use", "LE_PORT80_BUSY"),
    ("Detail: Invalid response from http://example.com/.well-known/acme-challenge/MY_SECRET_TOKEN",
     "LE_HTTP01_CHALLENGE_FAILED"),
    ("too many failed authorizations, rate limit exceeded", "LE_RATE_LIMIT"),
    ("Error creating new order: Profile default does not permit ip type identifiers",
     "LE_PROFILE_UNSUPPORTED"),
    ("certbot: error: unrecognized arguments: --ip-address", "CERTBOT_ARGS_INVALID"),
    ("ACME server error while registering an account", "LE_ACCOUNT_ERROR"),
    ("DNS problem: NXDOMAIN looking up A record", "LE_DNS_ERROR"),
    ("Unexpected failure with SECRET-ACCESS-TOKEN", "LE_UNCLASSIFIED"),
])
def test_failed_ip_issuance_emits_only_sanitized_actionable_error(tmp_path, fake_error, expected_classification):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    certbot = bindir / "certbot"
    certbot.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$FAKE_CERTBOT_ERROR\" >&2\n"
        "exit 1\n",
        encoding="utf-8",
    )
    certbot.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    env["FAKE_CERTBOT_ERROR"] = fake_error
    script = https_steps("45.32.35.195", 24443)[2]["script"]
    # IP mode deliberately calls the isolated absolute Certbot path, not PATH.
    # Redirect only that exact executable into the fake local binary.
    script = script.replace(IP_CERTBOT_BIN, str(certbot))
    result = subprocess.run(["bash", "-se"], input=script, text=True,
                            capture_output=True, timeout=10, env=env, check=False)
    assert result.returncode == 34, result.stderr
    assert expected_classification in result.stderr, result.stderr
    assert "SECRET-ACCESS-TOKEN" not in result.stderr
    assert "MY_SECRET_TOKEN" not in result.stderr
    assert "/var/log/letsencrypt/letsencrypt.log" in result.stderr or expected_classification != "LE_UNCLASSIFIED"
    assert "was not opened to public HTTP" in result.stderr


def test_web_panel_has_no_certificate_mode_selection():
    js = (Path(__file__).resolve().parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'name="access_mode"' not in js
    assert "payload.access_mode='https'" in js
    assert "showExistingXui(id,status)" in js
    assert "修复后重新生成证书方案" in js
