"""Sanitized API client for the standalone Codex worker.

Windows defaults to a native SDK sidecar; Docker/NAS optionally keeps the
container worker. No SSH secrets or administrator token are passed by API.
"""
from __future__ import annotations

import json
import os
import httpx
from .tasks import sanitize


def diagnose(job: dict, facts: dict) -> str:
    url = os.getenv("NETDEPLOY_CODEX_WORKER_URL", "").rstrip("/")
    if not url:
        raise RuntimeError("Codex 尚未就绪：Windows 请正常启动 QuickStart；Docker/NAS 请启动 ai 服务")
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
        # The worker is localhost or a private Compose DNS name. Never send
        # the worker token/data through a user-configured HTTP(S) proxy.
        with httpx.Client(timeout=90, trust_env=False, follow_redirects=False) as client:
            res = client.post(
                url + "/diagnose", json=data,
                headers={"X-Worker-Token": os.getenv("NETDEPLOY_WORKER_TOKEN", "")},
            )
        if res.status_code == 409:
            raise RuntimeError("请先在 Codex AI 页面完成 ChatGPT 账号登录")
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
        raise RuntimeError("Codex 尚未就绪：Windows 请正常启动 QuickStart；Docker/NAS 请启动 ai 服务")
    try:
        with httpx.Client(timeout=25, trust_env=False, follow_redirects=False) as client:
            response = client.request(
                method, url + path,
                headers={"X-Worker-Token": os.getenv("NETDEPLOY_WORKER_TOKEN", "")},
            )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid Codex worker result")
        # Only expected fields enter the panel; never include auth tokens.
        allowed = ("available", "connected", "pending", "auth_type", "mode",
                   "verification_url", "user_code", "error", "cancelled")
        return {key: data[key] for key in allowed if key in data}
    except (httpx.HTTPError, ValueError) as exc:
        if route == "status":
            return {"available": False, "connected": False, "pending": False}
        raise RuntimeError("无法连接 Codex；请查看原生 Worker 启动状态或 Docker/NAS ai 配置") from exc


def codex_status() -> dict:
    return _worker_account_request("status")


def codex_connect() -> dict:
    return _worker_account_request("connect", method="POST")


def codex_cancel() -> dict:
    return _worker_account_request("cancel", method="POST")


def codex_logout() -> dict:
    return _worker_account_request("logout", method="POST")
