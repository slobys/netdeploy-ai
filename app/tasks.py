"""Step-level background execution. No AI-generated command execution."""
from __future__ import annotations

import re
import threading
import traceback
from datetime import datetime, timedelta, timezone

from .executor import SSHError
from .catalog import build_plan

SECRET_RE = re.compile(r'(?i)(password|passwd|token|secret|api[_ -]?key)\s*[:=]\s*[^\s]+')


def sanitize(value: str) -> str:
    return SECRET_RE.sub(r'\1=[REDACTED]', value)[:1600]


class JobRunner:
    def __init__(self, store, executor):
        self.store = store
        self.executor = executor
        self._locks: dict[int, threading.Lock] = {}
        self._mutex = threading.Lock()

    def approval_text(self, job: dict, host: dict) -> str:
        return f'DEPLOY {job["project"]} TO {host["hostname"]}'

    def enqueue(self, job: dict, host: dict, confirmation: str):
        if not job["plan"]["executable"]:
            raise ValueError("当前部署方案不允许自动执行")
        if confirmation != self.approval_text(job, host):
            raise ValueError("确认语句不一致")
        created = datetime.fromisoformat(job["created_at"])
        if datetime.now(timezone.utc) - created > timedelta(minutes=10):
            raise ValueError("部署方案已超过十分钟，请重新进行环境检测并生成方案")
        # Avoid running two mutations for the same VPS in one process.
        with self._mutex:
            lock = self._locks.setdefault(host["id"], threading.Lock())
            if not lock.acquire(blocking=False):
                raise ValueError("此服务器有其他正在运行的变更任务")
            if not self.store.approve(job["id"]):
                lock.release()
                raise ValueError("任务已执行或审批状态无效")
            threading.Thread(target=self._run, args=(job["id"], host, lock), daemon=True).start()

    def _run(self, job_id: str, host: dict, lock: threading.Lock):
        completed_steps = 0
        try:
            job = self.store.job(job_id)
            if not job:
                return
            # Rebuild each command from source-controlled recipes, NOT mutable job data.
            # No user/AI/DB-origin script is ever passed to SSH.
            current_host = self.store.host(host["id"])
            expected = build_plan(job["project"], current_host["facts"] or {}, job["plan"].get("options"))
            if not expected["executable"] or expected["steps"] != job["plan"]["steps"]:
                raise SSHError("拒绝执行：计划脚本与当前已审查的内置模板不一致，请重新生成")
            self.store.set_status(job_id, "running")
            self.store.log(job_id, "审批通过，开始执行经审查的固定部署步骤")
            for idx, step in enumerate(expected["steps"], 1):
                self.store.log(job_id, f'步骤 {idx}/{len(expected["steps"])}：{step["label"]}')
                out = self.executor.run(host, step["script"], timeout=step["timeout"])
                self.store.log(job_id, f'通过：{sanitize(out[-900:]) or "已完成"}')
                completed_steps = idx
            self.store.set_status(job_id, "completed")
            self.store.log(job_id, "部署执行结束。请检查项目的首次配置和网络连通性；这不等于业务已配置完成。")
        except Exception as exc:
            msg = sanitize(str(exc))
            last = self.store.job(job_id)
            installed_locally = (
                last is not None and last["project"] == "3x-ui"
                and last["plan"].get("options", {}).get("access_mode") == "https"
                and completed_steps >= 5
            )
            if installed_locally:
                self.store.log(job_id, f"HTTPS 未完成：{msg}；3X-UI 原安装步骤已完成，需核查本机监听状态")
                self.store.set_status(job_id, "partial", msg)
            else:
                self.store.log(job_id, f"失败：{msg}")
                self.store.set_status(job_id, "failed", msg)
        finally:
            lock.release()
