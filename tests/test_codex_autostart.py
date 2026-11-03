"""QuickStart must auto-bootstrap Codex while keeping the main VPS app independent.

Windows-specific behavior is verified further by the PowerShell 5.1 parser in CI.
These tests do not start a Docker daemon, contact Codex, or read user credentials.
"""
import json
import os
import re
import time
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main


ROOT = Path(__file__).resolve().parents[1]
ADMIN = {"X-Admin-Token": os.environ["NETDEPLOY_ADMIN_TOKEN"]}


def _script(path):
    return (ROOT / path).read_text(encoding="utf-8-sig")


def test_windows_start_is_nonblocking_and_automatic():
    starter = _script("scripts/Start-Windows.ps1")
    quickstart = _script("scripts/QuickStart-Windows.ps1")
    worker = _script("scripts/Enable-Codex-Windows.ps1")
    assert "Start-NetDeploy.bat" in quickstart
    assert "scripts\\Enable-Codex-Windows.ps1" in starter
    assert "Start-Process -FilePath 'powershell.exe'" in starter
    assert "-Auto" in starter and "NETDEPLOY_CODEX_AUTO_START" in starter
    assert starter.index("Start-Process -FilePath 'powershell.exe'") < starter.index("uvicorn app.main:app")
    assert "NETDEPLOY_WORKER_TOKEN=$workerToken" in starter
    assert "$env:NETDEPLOY_CODEX_WORKER_URL = 'http://127.0.0.1:8788'" in starter
    assert "NETDEPLOY_ADMIN_TOKEN" in starter
    assert "NETDEPLOY_LOCAL_AUTO_LOGIN = '1'" in starter
    assert "if ($autoCodex" in starter
    assert "elseif (-not $dockerAvailable)" in starter

    assert "param([switch]$Auto)" in worker
    assert "function Start-DockerDesktopBackground" in worker
    assert "desktop start --detach" in worker, "Use supported background CLI"
    assert "Start-Process -FilePath $desktop" not in worker, (
        "QuickStart must never directly open Docker Desktop.exe"
    )
    assert "WaitForExit(15000)" in worker, "CLI startup attempt must be bounded"
    assert "WaitForExit(3500)" in worker, "Docker readiness probes must be bounded"
    assert "WaitForExit(420000)" in worker, "First-time Compose build must be bounded"
    assert "'--no-deps'" in worker, "Never start a second NetDeploy API container"
    assert "NETDEPLOY_WORKER_TOKEN" in worker
    assert "codex-worker-build.sha256" in worker, "Avoid rebuilding on each launch"
    assert "if ($needsBuild)" in worker
    assert "codex-worker-startup.json" in worker
    assert "Write-CodexStartupState 'ready'" in worker
    assert "Local\\NetDeployCodexWorkerStartup" in worker
    # Do not trust the default context before Docker Desktop starts. Explicitly
    # validate the localhost endpoint AND the running server's OSType=linux.
    assert "Docker 当前不是 Windows 本机 Linux 引擎" not in worker
    assert "@('desktop-linux', 'default')" in worker
    assert "Get-LocalDockerContexts" in worker
    assert "Find-RunningLocalLinuxContext" in worker
    assert "Get-DockerServerOs" in worker
    assert 'info --format "{{.OSType}}"' in worker
    assert worker.count("$dockerContext = Find-RunningLocalLinuxContext $dockerExe") >= 2, (
        "Recheck contexts after cold Docker Desktop boot"
    )
    assert worker.index("if (-not (Start-DockerDesktopBackground $dockerExe))") > worker.index(
        "$dockerContext = Find-RunningLocalLinuxContext $dockerExe"
    )
    assert "if (-not (Start-DockerDesktopBackground $dockerExe))" in worker
    assert "Open Docker Dashboard when Docker Desktop starts" in worker

    assert "$composeArgs = @('--context', $dockerContext, 'compose'" in worker
    assert "docker context use" not in worker.lower(), "Do not mutate user Docker defaults"
    assert "Remove-Item Env:DOCKER_HOST" in worker
    assert "Remove-Item Env:DOCKER_CONTEXT" in worker
    assert "http://127.0.0.1:8788/account/status" in worker
    assert "if ($Auto)" in worker
    assert "exit 1" in worker, "Manual startup should still report failures"


def test_docker_context_endpoint_allowlist_is_strict():
    worker = _script("scripts/Enable-Codex-Windows.ps1")
    match = re.search(r"if \(\$endpoint -match '([^']+)'\)", worker)
    assert match, "The Docker endpoint must be checked before using a context"
    pattern = re.compile(match.group(1))
    for endpoint in (
        "npipe:////./pipe/dockerDesktopLinuxEngine",
        "npipe:////./pipe/docker_engine",
        "npipe://./pipe/docker_engine",
    ):
        assert pattern.fullmatch(endpoint), endpoint
    for endpoint in (
        "ssh://root@remote-vps",
        "tcp://10.1.2.3:2375",
        "tcp://127.0.0.1:2375",
        "unix:///var/run/docker.sock",
        "npipe:////other-host/pipe/docker_engine",
        "npipe:////./pipe/dockerDesktopWindowsEngine",
        "npipe:////./pipe/custom-engine",
        "npipe:////./pipe/docker_engine/extra",
    ):
        assert not pattern.fullmatch(endpoint), endpoint


def test_codex_worker_is_local_optional_and_restartable():
    compose = _script("compose.yaml")
    win = _script("compose.ai-windows.yaml")
    worker_section = compose.split("\n  codex-worker:", 1)[1].split("\nvolumes:", 1)[0]
    assert "restart: unless-stopped" in worker_section
    assert 'profiles: ["ai"]' in worker_section
    assert "codex-auth:/home/agent/.codex" in worker_section
    assert "NETDEPLOY_ADMIN_TOKEN" not in worker_section
    assert "NETDEPLOY_SSH_KEY_FILE" not in worker_section
    assert "docker.sock" not in worker_section.lower().replace("# no external port, no ssh key mount, no database, no docker socket.", "")
    assert '127.0.0.1:8788:8788' in win
    assert '0.0.0.0:8788' not in win


def test_codex_startup_progress_is_private_and_expires(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "codex_status", lambda: {
        "available": False, "connected": False, "pending": False
    })
    client = TestClient(main.app)
    assert client.get("/api/codex/status").status_code == 401
    assert "startup_state" not in client.get("/api/codex/status", headers=ADMIN).json()
    status_file = tmp_path / "codex-worker-startup.json"
    status_file.write_text(json.dumps({
        "state": "starting", "message": "正在后台启动 Docker",
        "epoch": time.time()
    }), encoding="utf-8")
    running = client.get("/api/codex/status", headers=ADMIN).json()
    assert running["startup_state"] == "starting"
    assert "Docker" in running["startup_message"]
    monkeypatch.setattr(main, "codex_status", lambda: {
        "available": True, "connected": True, "auth_type": "chatgpt"
    })
    connected = client.get("/api/codex/status", headers=ADMIN).json()
    assert connected["connected"] is True
    assert "startup_state" not in connected, "Live worker state is authoritative"

    monkeypatch.setattr(main, "codex_status", lambda: {
        "available": False, "connected": False
    })
    status_file.write_text(json.dumps({
        "state": "failed", "message": "旧错误", "epoch": time.time() - 1000
    }), encoding="utf-8")
    assert "startup_state" not in client.get("/api/codex/status", headers=ADMIN).json()
    status_file.write_text("{broken json", encoding="utf-8")
    assert "startup_state" not in client.get("/api/codex/status", headers=ADMIN).json()


def test_windows_documentation_explains_one_click_and_first_auth():
    readme = _script("README.md")
    assert "QuickStart-NetDeploy.bat" in readme
    assert "不必再运行" in readme
    assert "Docker Desktop" in readme
    assert "NETDEPLOY_CODEX_AUTO_START=0" in readme
    assert "只有首次连接账号或登录失效时才需要重新授权" in readme
    assert "docker desktop start --detach" in readme
    assert "Open Docker Dashboard when Docker Desktop starts" in readme
    assert "后台引擎" in readme
