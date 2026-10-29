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
