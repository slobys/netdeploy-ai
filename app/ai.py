"""Sanitized, strictly outbound client for an isolated Codex worker.

Codex runs in a SEPARATE container with no SSH keys, admin token, DB or
Docker socket. The primary API cannot launch a local Codex subprocess.
"""
from __future__ import annotations

import json
import os
import httpx
from .tasks import sanitize


def diagnose(job: dict, facts: dict) -> str:
    url = os.getenv("NETDEPLOY_CODEX_WORKER_URL", "").rstrip("/")
    if not url:
        raise RuntimeError("Codex 隔离服务未启用：请按 README 启动独立 AI Worker")
    data = {
        "project": job["project"],
        "status": job["status"],
        "risk": job["plan"]["risk"],
        "issues": job["plan"]["issues"],
        "warnings": job["plan"]["warnings"],
        "device": {k: v for k, v in (facts or {}).items() if k in {"OS_ID", "OS_VERSION", "ARCH", "DOCKER", "COMPOSE", "SYSTEMD"}},
        "logs": sanitize(job["logs"][-5000:]),
    }
    try:
        res = httpx.post(url + "/diagnose", json=data, timeout=90,
                         headers={"X-Worker-Token":os.getenv("NETDEPLOY_WORKER_TOKEN", "")})
        res.raise_for_status()
        return res.json().get("message", "AI 未返回有效诊断")
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("隔离 Codex Worker 未就绪、未授权或响应失败；普通部署功能不受影响") from exc

def _worker_account_request(route: str, *, method: str = "GET") -> dict:
    """Allow only fixed internal routes; never forward arbitrary panel URLs."""
    path = {
        "status": "/account/status",
        "connect": "/account/device-login",
        "cancel": "/account/cancel",
        "logout": "/account/logout",
    }[route]
    url = os.getenv("NETDEPLOY_CODEX_WORKER_URL", "").rstrip("/")
    if not url:
        if route == "status":
            return {"available": False, "connected": False, "pending": False}
        raise RuntimeError("AI Worker 尚未启用。请使用 Docker Compose 的 ai 配置启动")
    try:
        response = httpx.request(
            method, url + path, timeout=25, follow_redirects=False,
            headers={"X-Worker-Token": os.getenv("NETDEPLOY_WORKER_TOKEN", "")},
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid Codex worker result")
        # Only expected fields enter the panel; never include auth tokens.
        allowed = ("available", "connected", "pending", "auth_type",
                   "verification_url", "user_code", "error", "cancelled")
        return {key: data[key] for key in allowed if key in data}
    except (httpx.HTTPError, ValueError) as exc:
        if route == "status":
            return {"available": False, "connected": False, "pending": False}
        raise RuntimeError("无法连接隔离 AI Worker；请确认已经启动 ai 配置及登录功能") from exc


def codex_status() -> dict:
    return _worker_account_request("status")


def codex_connect() -> dict:
    return _worker_account_request("connect", method="POST")


def codex_cancel() -> dict:
    return _worker_account_request("cancel", method="POST")


def codex_logout() -> dict:
    return _worker_account_request("logout", method="POST")
