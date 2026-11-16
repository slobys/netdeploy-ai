"""Installed Windows entry point. Uses only the bundled Python runtime."""
from __future__ import annotations

import argparse
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser


def request(url: str, token: str = "", *, method: str = "GET") -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    headers = {"X-Admin-Token": token} if token else {}
    with opener.open(urllib.request.Request(url, headers=headers, method=method), timeout=3) as response:
        return json.load(response)


def settings(home: Path) -> dict:
    path = home / "settings.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if any(not isinstance(data.get(key), str) or len(data[key]) < 24
               for key in ("admin_token", "worker_token")):
            raise RuntimeError("本机配置损坏，请保留数据并联系项目维护者。")
        return data
    data = {"admin_token": secrets.token_urlsafe(40), "worker_token": secrets.token_urlsafe(40)}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    temporary.replace(path)
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path)
    parser.add_argument("--port", type=int, default=int(os.environ.get("NETDEPLOY_DESKTOP_PORT", "8787")))
    parser.add_argument("--worker-port", type=int, default=int(os.environ.get("NETDEPLOY_DESKTOP_WORKER_PORT", "8789")))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or not 1 <= args.worker_port <= 65535 or args.port == args.worker_port:
        raise RuntimeError("本机端口配置无效。")
    default_home = os.environ.get("NETDEPLOY_DESKTOP_HOME")
    home = (args.home or (Path(default_home) if default_home else
                         Path(os.environ["LOCALAPPDATA"]) / "NetDeployAI" / "desktop")).resolve()
    home.mkdir(parents=True, exist_ok=True)
    url = f"http://127.0.0.1:{args.port}"
    if args.stop:
        try:
            config = json.loads((home / "settings.json").read_text(encoding="utf-8"))
            request(url + "/api/desktop/stop", config["admin_token"], method="POST")
        except (ConnectionError, urllib.error.URLError) as exc:
            if isinstance(exc, urllib.error.HTTPError):
                raise RuntimeError("请先完成正在执行的部署任务，再退出或更新程序。") from exc
            return 0
        except FileNotFoundError:
            return 0
        for _ in range(100):
            try:
                request(url + "/api/health")
            except (OSError, ValueError):
                return 0
            time.sleep(.1)
        raise RuntimeError("面板仍在关闭，请稍后重试。")

    # A second click opens the existing NetDeploy. Never start a second store or worker.
    try:
        health = request(url + "/api/health")
        if health.get("ok") is True and health.get("security") == "local-only":
            if not args.no_browser:
                webbrowser.open(url)
            return 0
        raise RuntimeError(f"本机 {args.port} 端口已被其他程序占用。")
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        pass

    import msvcrt
    lock = (home / "desktop.lock").open("a+b")
    lock.seek(0)
    lock.write(b"0")
    lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        # The first process may still be binding its listener.
        for _ in range(100):
            try:
                health = request(url + "/api/health")
                if health.get("ok") is True and health.get("security") == "local-only":
                    if not args.no_browser:
                        webbrowser.open(url)
                    return 0
            except (OSError, ValueError):
                pass
            time.sleep(.1)
        raise RuntimeError("NetDeploy 正在启动，请稍后再次打开。")

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", args.port))
        listener.listen(128)
        config = settings(home)
        root = Path(__file__).resolve().parents[1]
        os.environ["PATH"] = str(root / "ssh") + os.pathsep + os.environ.get("PATH", "")
        os.environ.update({
            "NETDEPLOY_ADMIN_TOKEN": config["admin_token"],
            "NETDEPLOY_DATA": str(home / "data"),
            "NETDEPLOY_LOCAL_AUTO_LOGIN": "1",
            "NETDEPLOY_LOCAL_PORT": str(args.port),
            "NETDEPLOY_SSH_KEY_FILE": str(home / "ssh_key"),
            "NETDEPLOY_WORKER_TOKEN": config["worker_token"],
            "NETDEPLOY_CODEX_WORKER_URL": f"http://127.0.0.1:{args.worker_port}",
            "NETDEPLOY_CODEX_NATIVE_AUTO_START": "1",
            "NETDEPLOY_CODEX_LOCAL_ROOT": str(home / "codex-native"),
            "NETDEPLOY_CODEX_WORKER_PORT": str(args.worker_port),
        })
        os.chdir(home)
        log = home / "logs"
        log.mkdir(exist_ok=True)
        stream = (log / "desktop.log").open("a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = stream
        handler = RotatingFileHandler(log / "server.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8")
        logging.basicConfig(level=logging.INFO, handlers=[handler])

        import uvicorn
        from fastapi import Depends, HTTPException
        from app.main import app, authorized, store

        server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=args.port, workers=1,
            access_log=False, log_config=None,
        ))

        @app.post("/api/desktop/stop", dependencies=[Depends(authorized)])
        def stop():
            if any(job["status"] in {"queued", "running"} for job in store.jobs()):
                raise HTTPException(409, "请等待部署任务结束后再退出。")
            server.should_exit = True
            return {"ok": True}

        def open_when_ready():
            for _ in range(100):
                if server.started:
                    webbrowser.open(url)
                    return
                time.sleep(.1)

        if not args.no_browser:
            threading.Thread(target=open_when_ready, daemon=True).start()
        server.run(sockets=[listener])
        return 0
    finally:
        listener.close()
        lock.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        if "--quiet" not in sys.argv:
            ctypes.windll.user32.MessageBoxW(None, str(exc), "NetDeploy AI", 0x10)
        raise SystemExit(1)
