"""Focused tests for pinned 3X-UI workflows and private credential retrieval."""
import re
import subprocess
import shutil
import sys

import pytest

from app.three_x_ui import ACCESS_SCRIPT, INSTALLER_SHA256, VERSION, deployment_steps, parse_access_result


def example_credentials(port=24443):
    return (f"XUI_USERNAME=Admin12345\n"
            f"XUI_PASSWORD=SafePass3456\n"
            f"XUI_PANEL_PORT={port}\n"
            f"XUI_WEB_BASE_PATH=AbCd12EfGh345\n")


def test_parse_verified_credentials():
    result = parse_access_result(example_credentials(), 24443)
    assert result["username"] == "Admin12345"
    assert result["password"] == "SafePass3456"
    assert result["local_url"] == "http://127.0.0.1:24443/AbCd12EfGh345"
    assert result["port"] == 24443


@pytest.mark.parametrize("raw", [
    "",
    "XUI_USERNAME=root\n",
    example_credentials(2222),
    example_credentials() + "XUI_PASSWORD=bad\n",
    example_credentials() + "XUI_API_TOKEN=do-not-expose\n",
    example_credentials().replace("Admin12345", "admin<script>"),
    example_credentials().replace("SafePass3456", "$(cat /root/.ssh/id_rsa)"),
    example_credentials().replace("AbCd12EfGh345", "hello/../../admin"),
    example_credentials().replace("XUI_PANEL_PORT=24443", "XUI_PANEL_PORT=00024443"),
])
def test_parse_access_fails_closed(raw):
    with pytest.raises(ValueError):
        parse_access_result(raw, 24443)


def test_installer_fixed_version_and_sha256_are_embedded():
    scripts = deployment_steps(24443)
    assert len(scripts) == 5
    assert re.fullmatch(r"[0-9a-f]{64}", INSTALLER_SHA256)
    assert VERSION in scripts[2]["script"]
    assert INSTALLER_SHA256 in scripts[2]["script"]
    assert "sha256sum -c -" in scripts[2]["script"]
    assert "bind_local=\"y\"" in scripts[2]["script"]
    assert "XUI_PANEL_PORT=24443" in scripts[3]["script"]
    assert "systemctl stop x-ui" in scripts[3]["script"]
    assert "127.0.0.1:24443" in scripts[-1]["script"]
    assert "XUI_PASSWORD" not in "\n".join(step["script"] for step in scripts)
    assert "XUI_API_TOKEN" not in "\n".join(step["script"] for step in scripts)
    assert "password" not in ACCESS_SCRIPT.lower().split("grep")[0]


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None, reason="Linux target bash required")
def test_generated_remote_scripts_are_bash_syntax_valid():
    for step in deployment_steps(24443):
        result = subprocess.run(["bash", "-n"], input=step["script"],
                                capture_output=True, text=True, check=False)
        assert result.returncode == 0, (step["label"], result.stderr)
