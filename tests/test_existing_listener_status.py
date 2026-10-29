"""Execute *read-only* existing 3X-UI SSH scripts with a fake local system.

The status and credentials paths must agree with the activation script about
Go dual-stack / Linux ss wildcard formats. No network or remote VPS is used.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest

from app.xui_existing import status_script, public_access_script


@pytest.fixture
def fake_existing_panel(tmp_path):
    bindir = tmp_path / "fake-bin"
    bindir.mkdir()
    panel_dir = tmp_path / "xui"
    panel_dir.mkdir()
    install = panel_dir / "install-result.env"
    install.write_text(
        "XUI_PANEL_PORT=8443\n"
        "XUI_WEB_BASE_PATH=SecretRoute123\n"
        "XUI_USERNAME=InitialAdmin88\n"
        "XUI_PASSWORD=InitialPassword88\n", encoding="utf-8"
    )
    install.chmod(0o600)
    scripts = {
        "id": "#!/bin/sh\necho 0\n",
        "systemctl": "#!/bin/sh\n"
                     "if [ \"$1\" = is-active ]; then exit 0; fi\n"
                     "exit 1\n",
        "stat": "#!/bin/sh\n"
                "if [ \"$2\" = %a ]; then echo 600; exit 0; fi\n"
                "if [ \"$2\" = %u ]; then echo 0; exit 0; fi\n"
                "exit 1\n",
        "ss": "#!/bin/sh\n"
              "printf 'LISTEN 0 128 %s *:*\\n' \"$FAKE_SOCKET_ADDR\"\n",
        "curl": "#!/bin/sh\n"
                "echo \"$*\" >> \"$FAKE_CURL_LOG\"\n"
                "[ \"$FAKE_CURL_EXIT\" = 7 ] && exit 7\n"
                "echo 200\n",
    }
    for name, source in scripts.items():
        target = bindir / name
        target.write_text(source, encoding="utf-8")
        target.chmod(0o755)
    def run(script: str, address: str, curl_exit: int=0):
        script = script.replace("/etc/x-ui", str(panel_dir))
        script = script.replace("/usr/local/x-ui", str(tmp_path / "not-installed"))
        env = os.environ.copy()
        env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
        env["FAKE_SOCKET_ADDR"] = address
        env["FAKE_CURL_EXIT"] = str(curl_exit)
        env["FAKE_CURL_LOG"] = str(tmp_path / "curl-args.log")
        return subprocess.run(["bash", "-se"], input=script, text=True,
                              capture_output=True, check=False, timeout=6, env=env)
    return run


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                    reason="Target command syntax is Linux bash")
@pytest.mark.parametrize(("addr", "curl_exit", "mode"), [
    ("0.0.0.0:8443", 0, "https"),
    ("*:8443", 0, "https"),
    ("[::]:8443", 0, "https"),
    (":::8443", 0, "https"),
    ("127.0.0.1:8443", 0, "local"),
    ("[::]:8443", 7, "public_unverified"),
    ("*:84430", 0, "unknown"),
])
def test_existing_xui_readonly_status_with_real_ss_variants(
        fake_existing_panel, addr, curl_exit, mode):
    result = fake_existing_panel(status_script("45.32.35.195"), addr, curl_exit)
    assert result.returncode == 0, result.stderr
    assert f"XUI_LISTENER={mode}" in result.stdout
    assert "XUI_PORT=8443" in result.stdout
    assert "InitialPassword88" not in result.stdout
    assert "SecretRoute123" not in result.stdout


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                    reason="Target command syntax is Linux bash")
@pytest.mark.parametrize(("addr", "curl_exit", "allowed"), [
    ("0.0.0.0:8443", 0, True),
    ("*:8443", 0, True),
    ("[::]:8443", 0, True),
    ("127.0.0.1:8443", 0, False),
    ("[::]:8443", 7, False),
    ("*:84430", 0, False),
])
def test_existing_panel_credentials_only_after_public_tls_check(
        fake_existing_panel, addr, curl_exit, allowed):
    result = fake_existing_panel(public_access_script("45.32.35.195", 8443),
                                 addr, curl_exit)
    assert (result.returncode == 0) == allowed, result.stderr
    assert ("XUI_PASSWORD=InitialPassword88" in result.stdout) == allowed
    assert ("XUI_WEB_BASE_PATH=SecretRoute123" in result.stdout) == allowed
