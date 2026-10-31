"""Windows quick-start must never mistake an already-running old version
for a successfully updated local service.
"""
from pathlib import Path


def test_launcher_refuses_stale_running_panel_without_opening_old_browser():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "QuickStart-Windows.ps1").read_text(encoding="utf-8-sig")
    assert "Invoke-RestMethod -Uri 'http://127.0.0.1:8787/api/health'" in launcher
    assert "$health.version" in launcher
    assert "Start-Process 'http://127.0.0.1:8787'" not in launcher
    assert "if ($health.ok -and $health.version)" in launcher
    # The error must be thrown OUTSIDE the health probe try/catch; otherwise
    # it gets silently swallowed and the user only sees generic port conflict.
    existing = launcher.split("if ($runningVersion) {", 1)[1].split(
        "throw '本机 8787 端口", 1
    )[0]
    assert launcher.index('if ($runningVersion) {') > launcher.index("} catch {")

    assert "throw" in existing
    assert "Ctrl+C" in existing
    assert "exit 0" not in existing
    assert "仍在运行的面板版本" in existing
    assert "不会更新或重新启动" in existing
    assert "git" in launcher
    assert "Update-Windows.ps1" in launcher


def test_current_version_is_consistent_between_server_frontend_and_docs():
    root = Path(__file__).resolve().parents[1]
    main = (root / "app" / "main.py").read_text(encoding="utf-8")
    html = (root / "app" / "static" / "index.html").read_text(encoding="utf-8")
    js = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'version="0.3.28"' in main
    assert '"version": "0.3.28"' in main
    assert "ALPHA v0.3.28" in html
    assert "const CLIENT_VERSION = '0.3.28'" in js
    assert "api('/health')" in js
    assert "版本不一致" in js
