"""Regression tests for wildcard TCP socket addresses from Linux ss / Go.

These run only local fake ss commands. No VPS, certificates or sockets opened.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.listening import PUBLIC_SOCKET_CHECK
from app.https_upgrade import https_steps, https_access_script
from app.xui_existing import public_access_script, status_script


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                    reason="Generated listener check executes on Linux bash")
@pytest.mark.parametrize(("addresses", "expected"), [
    ("0.0.0.0:8443", True),
    ("*:8443", True),
    ("[::]:8443", True),
    (":::8443", True),
    ("127.0.0.1:8443", False),
    ("[::1]:8443", False),
    ("45.32.35.195:8443", False),
    ("*:84430", False),
    ("0.0.0.0:844", False),
    ("", False),
    ("127.0.0.1:8443\n*:8443", True),
    ("*:84430\n127.0.0.1:8443", False),
])
def test_wildcard_socket_candidates_exact_port_and_no_loopback_only(tmp_path, addresses, expected):
    mock = tmp_path / "bin"
    mock.mkdir()
    ss = mock / "ss"
    ss.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$FAKE_SOCKET_LINES\" | while IFS= read -r addr; do\n"
        "  [ -n \"$addr\" ] && printf 'LISTEN 0 128 %s *:*\\n' \"$addr\"\n"
        "done\n", encoding="utf-8",
    )
    ss.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(mock) + os.pathsep + env.get("PATH", "")
    env["FAKE_SOCKET_LINES"] = addresses
    script = ("set -eu\n" + PUBLIC_SOCKET_CHECK +
              "\nnetdeploy_public_socket 8443\n")
    result = subprocess.run(["bash", "-se"], input=script, text=True,
                            capture_output=True, check=False, timeout=6, env=env)
    assert (result.returncode == 0) == expected, (addresses, result.stderr)
    assert not result.stdout


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                    reason="Generated listener check executes on Linux bash")
def test_socket_check_rejects_invalid_port_without_running_ss(tmp_path):
    mock = tmp_path / "bin"
    mock.mkdir()
    ss = mock / "ss"
    called = tmp_path / "called"
    ss.write_text("#!/bin/sh\ntouch \"$FAKE_SS_CALLED\"\n", encoding="utf-8")
    ss.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(mock) + os.pathsep + env.get("PATH", "")
    env["FAKE_SS_CALLED"] = str(called)
    for port in ("", "8443;id", "true", "8443.0"):
        script = "set -eu\n" + PUBLIC_SOCKET_CHECK + (
            "\nnetdeploy_public_socket \"$USER_SUPPLIED\"\n"
        )
        env["USER_SUPPLIED"] = port
        result = subprocess.run(["bash", "-se"], input=script, text=True,
                                capture_output=True, check=False, timeout=6, env=env)
        assert result.returncode != 0
        assert not called.exists()


@pytest.mark.parametrize("identity", ["45.32.35.195", "panel.example.com"])
def test_https_and_read_only_scripts_use_shared_socket_check(identity):
    upgrade = https_steps(identity, 8443)
    activation = upgrade[-1]["script"]
    access = https_access_script(identity, 8443)
    status = status_script(identity)
    existing_access = public_access_script(identity, 8443)
    for script in (activation, access, status, existing_access):
        assert "netdeploy_public_socket" in script
        assert "0.0.0.0:" in script and "[::]:" in script
        assert "__PUBLIC_SOCKET_CHECK__" not in script
        # These scripts must still verify identity over TLS to IPv4 loopback
        # before treating a wildcard (including IPv6 dual-stack) as public.
        assert "--connect-to" in script
        assert "curl --insecure" not in script and "curl -k" not in script
    assert "netdeploy_public_socket 8443" in activation
    assert "netdeploy_public_socket 8443" in access
    assert 'netdeploy_public_socket "$port"' in status
    assert "netdeploy_public_socket 8443" in existing_access
    assert "XUI_LISTENER_LOCAL_ONLY" in activation
    assert "XUI_LISTENER_MISSING" in activation
    assert "XUI_HTTPS_VERIFIED" in activation
    assert "trap restore_local_listener EXIT" in activation


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                    reason="Generated SSH command syntax is Linux bash")
def test_all_public_socket_embedded_scripts_parse_as_bash():
    for identity in ("45.32.35.195", "panel.example.com"):
        scripts = [s["script"] for s in https_steps(identity, 8443)]
        scripts.extend([
            https_access_script(identity, 8443),
            status_script(identity),
            public_access_script(identity, 8443),
        ])
        for script in scripts:
            result = subprocess.run(["bash", "-n"], input=script, text=True,
                                    capture_output=True, check=False)
            assert result.returncode == 0, result.stderr
