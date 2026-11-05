"""Windows QuickStart distinguishes reopening from an actual update."""
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_launcher_reuses_running_panel_before_the_update():
    launcher = (ROOT / "scripts" / "QuickStart-Windows.ps1").read_text(encoding="utf-8-sig")
    existing, update = launcher.split("$update = ", 1)
    assert "Get-NetDeployPanelVersion" in existing
    assert "$health.security -ceq 'local-only'" in existing
    assert "Start-Process $panelUrl\n        return" in existing
    assert "Update-Windows.ps1" in update


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Windows PowerShell")
def test_loopback_port_probe_releases_its_socket_and_detects_real_listeners():
    script = """
$ErrorActionPreference = 'Stop'
. ./scripts/Windows-Loopback.ps1
function Get-NetTCPConnection { throw 'CIM listener data must not be used' }
$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$listener.Start()
$port = $listener.LocalEndpoint.Port
try {
    if (Test-NetDeployPortAvailable -Port $port) { throw 'Accepted an active listener' }
} finally {
    $listener.Stop()
}
if (-not (Test-NetDeployPortAvailable -Port $port)) { throw 'Stopped listener left port blocked' }
if (-not (Test-NetDeployPortAvailable -Port $port)) { throw 'Probe leaked its socket' }
"""
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        cwd=ROOT,
        check=True,
        timeout=15,
    )


def test_current_version_is_consistent_between_server_frontend_and_docs():
    root = Path(__file__).resolve().parents[1]
    main = (root / "app" / "main.py").read_text(encoding="utf-8")
    html = (root / "app" / "static" / "index.html").read_text(encoding="utf-8")
    js = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'version="0.3.31"' in main
    assert '"version": "0.3.31"' in main
    assert "ALPHA v0.3.31" in html
    assert "const CLIENT_VERSION = '0.3.31'" in js
    assert "api('/health')" in js
    assert "版本不一致" in js
