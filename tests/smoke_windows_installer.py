"""Exercise an installed bundle using fresh data and ports, never the user's panel."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import urllib.request


def wait_for(check, *, seconds=40):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (OSError, ValueError):
            pass
        time.sleep(.2)
    raise AssertionError("Installed application did not reach the expected state")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("installer", type=Path)
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="netdeploy-安装验证 "))
    install = root / "程序 安装"
    home = root / "用户数据"
    env = os.environ.copy()
    env.update({
        "NETDEPLOY_DESKTOP_HOME": str(home),
        "NETDEPLOY_DESKTOP_PORT": "18787",
        "NETDEPLOY_DESKTOP_WORKER_PORT": "18789",
        "PATH": str(Path(os.environ["SystemRoot"]) / "System32"),
    })
    for key in list(env):
        if key.startswith(("NETDEPLOY_ADMIN_", "NETDEPLOY_WORKER_", "PYTHON")):
            env.pop(key)
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    config = {}

    def api(path, *, data=None):
        headers = {"X-Admin-Token": config.get("admin_token", "")}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request("http://127.0.0.1:18787/api/" + path, headers=headers,
                                     data=json.dumps(data).encode() if data is not None else None)
        with client.open(req, timeout=5) as response:
            return json.load(response)

    def install_now():
        subprocess.run([str(args.installer.resolve()), "/VERYSILENT", "/SUPPRESSMSGBOXES",
                        "/NORESTART", "/NOICONS", "/TASKS=", f"/DIR={install}",
                        f"/LOG={root / 'setup.log'}"], env=env, check=True, timeout=180)

    def launch():
        subprocess.run([str(install / "NetDeployAI.exe"), "--no-browser", "--quiet"],
                       env=env, check=True, timeout=10)
        wait_for(lambda: api("health"))
        config.update(json.loads((home / "settings.json").read_text(encoding="utf-8")))

    def stop():
        subprocess.run([str(install / "NetDeployAI.exe"), "--stop", "--quiet"],
                       env=env, check=True, timeout=30)

    def verify_ui():
        subprocess.run([str(install / "NetDeployAI.exe"), "--ui-smoke", "--quiet"],
                       env=env, check=True, timeout=60)
        ui = json.loads((home / "desktop-ui-smoke.json").read_text(encoding="utf-8"))
        assert all(ui[key] is True for key in ("embedded", "authenticated", "popup", "openerCleared", "themeText",
                                               "activationPreservesState", "documentationExternal", "managementLinksExternal"))
        for key in ("display", "popupDisplay"):
            display = ui[key]
            assert display["perMonitorV2"] is True
            assert display["windowDpi"] >= 96
            assert abs(display["devicePixelRatio"] - display["windowDpi"] / 96) < .01
        return ui

    try:
        install_now()
        launch()
        assert api("health")["version"] == "0.3.37"
        assert len(api("catalog")) >= 7
        assert api("capabilities")["secure_password_storage"]
        assert api("hosts") == [] and api("jobs") == []
        session_request = urllib.request.Request("http://127.0.0.1:18787/api/local-session",
                                                headers={"X-NetDeploy-Local": "1"})
        with client.open(session_request) as response:
            assert json.load(response)["token"] == config["admin_token"]
        assert api("auth") == {"ok": True}
        ui = verify_ui()
        assert ui["windowState"] == "Maximized"
        print("Desktop DPI verified:", json.dumps({key: ui[key] for key in ("display", "popupDisplay")}))
        window_file = home / "window-main.json"
        placement = json.loads(window_file.read_text(encoding="utf-8"))
        assert placement["ShowCommand"] == 3
        ratio = ui["display"]["devicePixelRatio"]
        normal_bounds = {"Left": 50, "Top": 50, "Right": 50 + round(1000 * ratio),
                         "Bottom": 50 + round(700 * ratio)}
        placement.update(ShowCommand=1, NormalPosition=normal_bounds)
        window_file.write_text(json.dumps(placement), encoding="utf-8")
        assert verify_ui()["windowState"] == "Normal"
        assert verify_ui()["windowState"] == "Normal"
        assert json.loads(window_file.read_text(encoding="utf-8"))["NormalPosition"] == normal_bounds
        # A removed monitor or a damaged preference must not strand the client.
        placement["NormalPosition"] = {"Left": 60000, "Top": 60000, "Right": 61500, "Bottom": 61050}
        window_file.write_text(json.dumps(placement), encoding="utf-8")
        assert verify_ui()["windowState"] == "Normal"
        window_file.write_text("invalid preference", encoding="utf-8")
        assert verify_ui()["windowState"] == "Maximized"
        print("Window preferences verified: first maximize, size/position persistence, activation, off-screen recovery and external browser links.")

        def worker_ready():
            state = json.loads((home / "data" / "codex-worker-startup.json").read_text(encoding="utf-8"))
            if state["state"] == "failed":
                raise AssertionError(state["message"])
            return state["state"] == "ready"

        wait_for(worker_ready, seconds=55)
        worker_request = urllib.request.Request("http://127.0.0.1:18789/account/status",
                                                headers={"X-Worker-Token": config["worker_token"]})
        with client.open(worker_request, timeout=20) as response:
            account = json.load(response)
            assert account["available"] and not account["connected"]
        host = api("hosts", data={"name": "安装升级验证", "hostname": "8.8.4.4",
                                 "port": 22, "username": "root", "auth_mode": "key"})
        assert host["name"] == "安装升级验证"
        launch()
        original = config.copy()
        stop()
        with sqlite3.connect(home / "data" / "netdeploy.db") as database:
            database.execute("INSERT INTO jobs(id,host_id,project,plan_json,status,created_at,updated_at) "
                             "VALUES('installer-test',?,'hiddify','{}','planned','test','test')", (host["id"],))
        auth_marker = home / "codex-native" / "auth" / "preserve-test.txt"
        auth_marker.write_text("test-only")
        launch()
        with sqlite3.connect(home / "data" / "netdeploy.db") as database:
            database.execute("UPDATE jobs SET status='running' WHERE id='installer-test'")
        refused = subprocess.run([str(install / "NetDeployAI.exe"), "--stop", "--quiet"],
                                 env=env, timeout=30)
        assert refused.returncode != 0 and api("health")["ok"]
        with sqlite3.connect(home / "data" / "netdeploy.db") as database:
            database.execute("UPDATE jobs SET status='planned' WHERE id='installer-test'")
        desktop = subprocess.Popen([str(install / "NetDeployAI.exe"), "--quiet"], env=env)

        def client_visible():
            if desktop.poll() is not None:
                raise AssertionError("Desktop client exited before upgrade")
            # A user's production client may already have the same window title.
            # Wait for this test process to own a window before checking reuse.
            found = False
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_ssize_t)
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
            user32.EnumWindows.argtypes = [callback_type, ctypes.c_ssize_t]

            @callback_type
            def visit(window, _):
                nonlocal found
                owner = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
                if owner.value == desktop.pid and user32.IsWindowVisible(window):
                    found = True
                    return False
                return True

            user32.EnumWindows(visit, 0)
            return found

        wait_for(client_visible)
        subprocess.run([str(install / "NetDeployAI.exe"), "--quiet"], env=env, check=True, timeout=15)
        assert desktop.poll() is None
        install_now()
        desktop.wait(timeout=15)
        assert desktop.returncode == 0
        launch()
        assert config == original
        assert api("hosts")[0]["name"] == "安装升级验证"
        assert api("jobs")[0]["id"] == "installer-test"
        stop()
        subprocess.run([str(install / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                       env=env, check=True, timeout=90)
        assert not (install / "NetDeployAI.exe").exists()
        assert json.loads((home / "settings.json").read_text(encoding="utf-8")) == original
        assert auth_marker.read_text() == "test-only"
        with sqlite3.connect(home / "data" / "netdeploy.db") as database:
            assert database.execute("SELECT COUNT(*) FROM hosts").fetchone()[0] == 1
            assert database.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        print("Installer smoke passed: embedded client, authenticated child window, SDK, upgrade and data retention.")
    finally:
        if (install / "NetDeployAI.exe").exists():
            stop()
    print(f"Verification logs: {root}")


if __name__ == "__main__":
    main()
