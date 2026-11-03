"""QuickStart must auto-bootstrap Codex while keeping the main VPS app independent.

Windows-specific behavior is verified further by the PowerShell 5.1 parser in CI.
These tests do not start a Docker daemon, contact Codex, or read user credentials.
"""
import json
import os
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
    assert "Start-Process -FilePath $desktop" in worker
    assert "WaitForExit(3500)" in worker, "Docker readiness probes must be bounded"
    assert "WaitForExit(420000)" in worker, "First-time Compose build must be bounded"
    assert "'--no-deps'" in worker, "Never start a second NetDeploy API container"
    assert "NETDEPLOY_WORKER_TOKEN" in worker
    assert "codex-worker-build.sha256" in worker, "Avoid rebuilding on each launch"
    assert "if ($needsBuild)" in worker
    assert "codex-worker-startup.json" in worker
    assert "Write-CodexStartupState 'ready'" in worker
    assert "Local\\NetDeployCodexWorkerStartup" in worker
    assert "Docker 当前不是 Windows 本机 Linux 引擎" in worker
    assert "DOCKER_HOST" in worker, "Do not write ChatGPT sessions to remote Docker"
    assert "http://127.0.0.1:8788/account/status" in worker
    assert "if ($Auto)" in worker
    assert "exit 1" in worker, "Manual startup should still report failures"


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
