"""Windows-native Codex sidecar lifecycle (no Docker or remote SSH access).

The sidecar is a separate Python process with its own venv, CODEX_HOME and an
empty working directory. It receives a filtered environment and *never* the
panel admin token, SSH credentials or application database path.

Process separation is not a Windows security boundary: the sidecar still runs
as the current Windows user. Codex's native sandbox and deny-all approvals
provide the model-execution boundary; this must not be advertised as having
the stronger separate-user/container OS isolation.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

import httpx

PORT = 8789
VENV_REQUIREMENTS = "requirements-codex-worker.txt"
ENV_SWITCH = "NETDEPLOY_CODEX_NATIVE_AUTO_START"


def native_enabled() -> bool:
    return (
        sys.platform == "win32"
        and os.environ.get(ENV_SWITCH) == "1"
        and os.environ.get("NETDEPLOY_CODEX_AUTO_START", "1") != "0"
    )


class NativeCodexManager:
    """One native worker owned by the Windows NetDeploy API process."""

    def __init__(self, project_root: Path, data_dir: Path, *,
                 local_root: Path | None = None, port: int = PORT):
        self.project_root = Path(project_root)
        self.data_dir = Path(data_dir)
        if local_root is None:
            appdata = os.environ.get("LOCALAPPDATA")
            if not appdata:
                raise RuntimeError("Windows LOCALAPPDATA 不可用，无法隔离 Codex 数据目录")
            local_root = Path(appdata) / "NetDeployAI" / "codex-native"
        self.local_root = Path(local_root)
        self.port = port
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.monitor_thread: threading.Thread | None = None
        self.child: subprocess.Popen | None = None
        self.setup_child: subprocess.Popen | None = None
        self._lock = threading.RLock()

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self._state("starting", "正在准备 Windows 原生 Codex（无需 Docker Desktop）")
        self.thread = threading.Thread(target=self._run, name="native-codex-bootstrap",
                                       daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        with self._lock:
            for proc in (self.setup_child, self.child):
                self._terminate(proc)
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=1)
        self._state("stopped", "Windows 原生 Codex 已随 NetDeploy 关闭")

    def _state(self, state: str, message: str) -> None:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            payload = {"state": state, "message": message,
                       "epoch": int(time.time())}
            (self.data_dir / "codex-worker-startup.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass  # UI status is advisory; never crash NetDeploy.

    @staticmethod
    def _terminate(proc: subprocess.Popen | None) -> None:
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass

    @staticmethod
    def _running_elevated() -> bool:
        """Do not run a native Codex SDK child with an administrator token."""
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return True  # Fail closed if Windows cannot determine elevation.

    @staticmethod
    def _env() -> dict[str, str]:
        """Explicit allowlist: no admin token, keyring paths, SSH or API keys."""
        keep = (
            "SystemRoot", "WINDIR", "USERPROFILE", "LOCALAPPDATA", "APPDATA",
            "PROGRAMDATA", "TEMP", "TMP", "COMSPEC", "PATHEXT",
            "PROCESSOR_ARCHITECTURE",
        )
        result = {name: os.environ[name] for name in keep if os.environ.get(name)}
        system_root = result.get("SystemRoot") or result.get("WINDIR", r"C:\Windows")
        result["PATH"] = os.pathsep.join((
            str(Path(system_root) / "System32"),
            str(Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0"),
            system_root,
        ))
        # Optional loopback-only proxy, used by ChatGPT in filtered networks.
        # Never pass remote proxies or embedded proxy credentials by default.
        for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
            raw = os.environ.get(name, "")
            if not raw:
                continue
            try:
                parsed = urlsplit(raw)
                if (parsed.scheme in ("http", "https", "socks5", "socks5h")
                    and parsed.hostname in ("127.0.0.1", "localhost", "::1")
                    and parsed.port and not parsed.username and not parsed.password):
                    result[name] = raw
            except ValueError:
                continue
        result["NO_PROXY"] = "localhost,127.0.0.1,::1"
        result["PYTHONNOUSERSITE"] = "1"
        result["PYTHONUNBUFFERED"] = "1"
        return result

    def _spawn(self, args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen:
        return subprocess.Popen(
            args, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )

    def _run_setup(self, args: list[str], cwd: Path, env: dict[str, str],
                   *, timeout: int, error: str) -> None:
        proc = self._spawn(args, cwd, env)
        with self._lock:
            self.setup_child = proc
        deadline = time.monotonic() + timeout
        try:
            while proc.poll() is None:
                if self.stop_event.wait(.25):
                    raise RuntimeError("Codex 初始化已取消")
                if time.monotonic() >= deadline:
                    raise RuntimeError(error + "（超时）")
            if proc.returncode != 0:
                raise RuntimeError(error)
        finally:
            self._terminate(proc)
            with self._lock:
                if self.setup_child is proc:
                    self.setup_child = None

    def _status(self, token: str) -> dict | None:
        try:
            with httpx.Client(timeout=1.2, trust_env=False,
                              follow_redirects=False) as client:
                r = client.get(
                    f"http://127.0.0.1:{self.port}/health",
                    headers={"X-Worker-Token": token},
                )
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and data.get("ready") is True and data.get("mode") == "windows-native":
                    return data
        except (httpx.HTTPError, ValueError):
            pass
        return None

    def _port_in_use(self) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=.6):
                return True
        except OSError:
            return False

    def _monitor_child(self, proc: subprocess.Popen) -> None:
        while not self.stop_event.wait(3):
            if proc.poll() is not None:
                self._state("failed", "Windows 原生 Codex 进程已退出，请重新启动 NetDeploy")
                return

    def _run(self) -> None:
        ready = False
        try:
            if self._running_elevated():
                raise RuntimeError("请使用普通用户权限启动 NetDeploy；管理员权限下不启动原生 Codex")
            token = os.environ.get("NETDEPLOY_WORKER_TOKEN", "")
            if len(token) < 24 or token.startswith("REPLACE_"):
                raise RuntimeError("本机 Codex 连接令牌尚未初始化")
            if self._status(token):
                ready = True
                self._state("ready", "Windows 原生 Codex 已连接，沿用现有 ChatGPT 登录")
                return
            if self._port_in_use():
                raise RuntimeError("本机 Codex 端口已被其他程序占用（8789），未连接未知服务")
            if self.stop_event.is_set():
                return

            root = self.local_root
            workspace, runtime, auth, venv = (
                root / "workspace", root / "runtime", root / "auth", root / "venv"
            )
            package = runtime / "app"
            for path in (workspace, package, auth):
                path.mkdir(parents=True, exist_ok=True)
            # No project files, SSH keys, secrets or DB inside the worker cwd.
            (package / "__init__.py").write_text("", encoding="utf-8")
            shutil.copyfile(self.project_root / "app" / "ai_worker.py",
                            package / "ai_worker.py")
            config = auth / "config.toml"
            if not config.exists():
                config.write_text("[features]\nprefer_mxc = true\n",
                                  encoding="utf-8")

            base_env = self._env()
            python = venv / "Scripts" / "python.exe"
            if not python.is_file():
                self._state("starting", "首次创建 Windows 原生 Codex 独立运行环境")
                self._run_setup(
                    [sys.executable, "-m", "venv", str(venv)], workspace, base_env,
                    timeout=180, error="创建 Codex 独立 Python 环境失败",
                )
            requirements = self.project_root / VENV_REQUIREMENTS
            digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
            marker = root / "requirements.sha256"
            installed = python.exists() and marker.exists() and (
                marker.read_text(encoding="utf-8").strip() == digest
            )
            if not installed:
                self._state("starting", "首次安装 Windows 原生 Codex SDK，后台继续启动 VPS 面板")
                self._run_setup(
                    [str(python), "-m", "pip", "install", "--disable-pip-version-check",
                     "--no-input", "--only-binary=:all:", "--retries", "1",
                     "--timeout", "20", "-r", str(requirements)],
                    workspace, base_env, timeout=600,
                    error="Codex SDK 安装失败，请检查网络及 Python Windows 版本",
                )
                marker.write_text(digest, encoding="utf-8")
            if self.stop_event.is_set():
                return

            env = self._env()
            env["NETDEPLOY_WORKER_TOKEN"] = token
            env["NETDEPLOY_CODEX_NATIVE"] = "1"
            env["NETDEPLOY_CODEX_PARENT_PID"] = str(os.getpid())
            env["CODEX_HOME"] = str(auth)
            env["PYTHONPATH"] = str(runtime)
            # Run the existing worker API on a separate native loopback port;
            # Docker's optional legacy worker may remain on 8788.
            self._state("starting", "正在启动 Windows 原生 Codex Worker（127.0.0.1:8789）")
            proc = self._spawn(
                [str(python), "-m", "uvicorn", "app.ai_worker:app",
                 "--app-dir", str(runtime), "--host", "127.0.0.1",
                 "--port", str(self.port), "--workers", "1", "--no-access-log"],
                workspace, env,
            )
            with self._lock:
                self.child = proc
            for _ in range(90):
                if self.stop_event.wait(.5):
                    return
                if self._status(token):
                    ready = True
                    self._state("ready", "Windows 原生 Codex 已就绪，可连接 ChatGPT")
                    self.monitor_thread = threading.Thread(
                        target=self._monitor_child, args=(proc,), daemon=True,
                        name="native-codex-monitor",
                    )
                    self.monitor_thread.start()
                    return
                if proc.poll() is not None:
                    raise RuntimeError("Windows 原生 Codex 运行进程启动失败")
            raise RuntimeError("Windows 原生 Codex Worker 启动超时")
        except Exception as exc:
            # Exception texts from pip, filesystem and paths must never leak.
            known = str(exc) if isinstance(exc, RuntimeError) else "本机 Codex 初始化失败"
            if not self.stop_event.is_set():
                self._state("failed", known[:180])
        finally:
            if self.stop_event.is_set() or not ready:
                # Failed health probes must not leave an unknown native
                # process listening with the user's login cache.
                with self._lock:
                    self._terminate(self.child)
