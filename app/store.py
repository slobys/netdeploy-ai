"""SQLite repository. No private keys, SSH passwords or AI credentials are persisted."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.RLock()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._db() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS hosts (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL, hostname TEXT NOT NULL,
                  port INTEGER NOT NULL, username TEXT NOT NULL,
                  tls_domain TEXT,
                  auth_mode TEXT NOT NULL DEFAULT 'key',
                  trust_epoch INTEGER NOT NULL DEFAULT 0,
                  facts_json TEXT, checked_at TEXT,
                  created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, host_id INTEGER NOT NULL,
                  project TEXT NOT NULL, plan_json TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                  approved_at TEXT, logs TEXT NOT NULL DEFAULT '',
                  error TEXT,
                  FOREIGN KEY(host_id) REFERENCES hosts(id));
            """)
        # Migrate databases created by v0.1.0 without losing existing devices.
        with self._db() as c:
            fields = {row[1] for row in c.execute("PRAGMA table_info(hosts)")}
            if "auth_mode" not in fields:
                c.execute("ALTER TABLE hosts ADD COLUMN auth_mode TEXT NOT NULL DEFAULT 'key'")
            if "trust_epoch" not in fields:
                c.execute("ALTER TABLE hosts ADD COLUMN trust_epoch INTEGER NOT NULL DEFAULT 0")
            if "tls_domain" not in fields:
                c.execute("ALTER TABLE hosts ADD COLUMN tls_domain TEXT")
        # No automatic retry after restart: remote jobs may have partly executed.
        with self._db() as c:
            c.execute("UPDATE jobs SET status='interrupted', error=? , updated_at=? WHERE status IN ('queued','running')",
                      ("进程重启，部署状态未知。请人工核对远端状态，不要直接重试。", now()))

    @contextmanager
    def _db(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def _row(row):
        if row is None:
            return None
        d = dict(row)
        if "facts_json" in d:
            d["facts"] = json.loads(d.pop("facts_json") or "null")
        if "plan_json" in d:
            d["plan"] = json.loads(d.pop("plan_json"))
        return d

    def hosts(self):
        with self._db() as c:
            return [self._row(r) for r in c.execute("SELECT * FROM hosts ORDER BY id DESC")]

    def host(self, id: int):
        with self._db() as c:
            return self._row(c.execute("SELECT * FROM hosts WHERE id=?", (id,)).fetchone())

    def add_host(self, data: dict):
        with self.lock, self._db() as c:
            cursor = c.execute("INSERT INTO hosts(name,hostname,port,username,tls_domain,auth_mode,created_at) VALUES(?,?,?,?,?,?,?)",
                               (data["name"], data["hostname"], data["port"], data["username"],
                                data.get("tls_domain"), data.get("auth_mode", "key"), now()))
            c.commit()
            return self.host(cursor.lastrowid)

    def host_job_count(self, host_id: int) -> int:
        with self._db() as c:
            return c.execute("SELECT COUNT(*) FROM jobs WHERE host_id=?", (host_id,)).fetchone()[0]

    def endpoint_hosts(self, hostname: str, port: int) -> list[dict]:
        with self._db() as c:
            rows = c.execute(
                "SELECT * FROM hosts WHERE lower(hostname)=lower(?) AND port=? ORDER BY id",
                (hostname, port),
            ).fetchall()
            return [self._row(row) for row in rows]

    def has_active_endpoint_jobs(self, hostname: str, port: int) -> bool:
        with self._db() as c:
            return bool(c.execute(
                """SELECT 1 FROM jobs j JOIN hosts h ON j.host_id=h.id
                   WHERE lower(h.hostname)=lower(?) AND h.port=?
                   AND j.status IN ('queued','running') LIMIT 1""",
                (hostname, port),
            ).fetchone())

    def update_host(self, host_id: int, name: str, hostname: str,
                    port: int, username: str, tls_domain: str | None = None) -> dict:
        with self.lock, self._db() as c:
            row = c.execute("SELECT * FROM hosts WHERE id=?", (host_id,)).fetchone()
            if row is None:
                raise ValueError("服务器记录不存在")
            changed = (row["hostname"].lower() != hostname.lower()
                       or row["port"] != port or row["username"] != username)
            tls_changed = (row["tls_domain"] or "") != (tls_domain or "")
            if tls_changed and c.execute(
                "SELECT 1 FROM jobs WHERE host_id=? AND status IN ('queued','running') LIMIT 1",
                (host_id,),
            ).fetchone():
                raise ValueError("该 VPS 正在执行任务，请完成部署后再更换证书域名")
            if changed:
                jobs = c.execute("SELECT COUNT(*) FROM jobs WHERE host_id=?",
                                 (host_id,)).fetchone()[0]
                if jobs:
                    raise ValueError("该 VPS 有部署历史，请只编辑名称；如需切换 IP、端口或账号，请新建一台服务器以保留旧任务记录")
                exists = c.execute(
                    "SELECT id FROM hosts WHERE lower(hostname)=lower(?) AND port=? AND id<>? LIMIT 1",
                    (hostname, port, host_id),
                ).fetchone()
                if exists:
                    raise ValueError("另一个 VPS 记录已使用此地址和端口，请编辑已有条目或删除重复记录")
            c.execute(
                """UPDATE hosts SET name=?, hostname=?, port=?, username=?, tls_domain=?,
                   facts_json=CASE WHEN ? THEN NULL ELSE facts_json END,
                   checked_at=CASE WHEN ? THEN NULL ELSE checked_at END,
                   trust_epoch=trust_epoch+?
                   WHERE id=?""",
                (name, hostname, port, username, tls_domain,
                 int(changed), int(changed), int(changed), host_id),
            )
            if tls_changed:
                # A previously prepared HTTPS plan has a frozen identity.
                # Do not silently retarget it to a newly entered domain.
                c.execute(
                    """UPDATE jobs SET status='invalidated',
                       error='证书域名已更新，旧审批计划不可用于新的证书标识',
                       updated_at=?
                       WHERE host_id=? AND project IN ('3x-ui','3x-ui-https')
                       AND status='planned'""",
                    (now(), host_id),
                )
        return self.host(host_id)

    def delete_host(self, host_id: int, purge_history: bool) -> dict:
        """Local-only deletion; never remote-uninstall or touch shared known_hosts."""
        with self.lock, self._db() as c:
            host = c.execute("SELECT * FROM hosts WHERE id=?", (host_id,)).fetchone()
            if host is None:
                raise ValueError("服务器不存在")
            active = c.execute(
                "SELECT COUNT(*) FROM jobs WHERE host_id=? AND status IN ('queued','running')",
                (host_id,),
            ).fetchone()[0]
            if active:
                raise ValueError("该服务器有排队或执行中的部署任务，禁止删除")
            count = c.execute("SELECT COUNT(*) FROM jobs WHERE host_id=?", (host_id,)).fetchone()[0]
            if count and not purge_history:
                raise ValueError(f"该服务器有 {count} 条本地部署历史，请确认一并删除；不会卸载 VPS 软件")
            c.execute("DELETE FROM jobs WHERE host_id=?", (host_id,))
            c.execute("DELETE FROM hosts WHERE id=?", (host_id,))
            return {"deleted_id": host_id, "deleted_jobs": count, "remote_unmodified": True}

    def invalidate_endpoint_trust(self, hostname: str, port: int) -> int:
        """VPS reinstall: invalidate all aliases sharing this SSH endpoint."""
        with self.lock, self._db() as c:
            active = c.execute(
                """SELECT 1 FROM jobs j JOIN hosts h ON j.host_id=h.id
                   WHERE lower(h.hostname)=lower(?) AND h.port=?
                   AND j.status IN ('queued','running') LIMIT 1""",
                (hostname, port),
            ).fetchone()
            if active:
                raise ValueError("该地址仍有正在执行的任务，禁止更换信任指纹")
            ids = [row[0] for row in c.execute(
                "SELECT id FROM hosts WHERE lower(hostname)=lower(?) AND port=?",
                (hostname, port))]
            for host_id in ids:
                c.execute(
                    """UPDATE hosts SET trust_epoch=trust_epoch+1,
                       facts_json=NULL, checked_at=NULL WHERE id=?""", (host_id,))
                c.execute(
                    """UPDATE jobs SET status='invalidated',
                       error='服务器重装或 SSH 信任密钥变化；旧审批方案已失效，请重新检测并生成计划',
                       updated_at=? WHERE host_id=? AND status='planned'""",
                    (now(), host_id),
                )
            return len(ids)

    def update_auth(self, host_id: int, auth_mode: str) -> dict:
        if auth_mode not in {"key", "password"}:
            raise ValueError("不支持的 SSH 认证方式")
        with self.lock, self._db() as c:
            active = c.execute("SELECT COUNT(*) FROM jobs WHERE host_id=? AND status IN ('queued','running')", (host_id,)).fetchone()[0]
            if active:
                raise ValueError("服务器存在执行中的任务，不能更换 SSH 凭据")
            c.execute("""UPDATE hosts SET auth_mode=?,
                      facts_json=CASE WHEN auth_mode=? THEN facts_json ELSE NULL END,
                      checked_at=CASE WHEN auth_mode=? THEN checked_at ELSE NULL END
                      WHERE id=?""", (auth_mode, auth_mode, auth_mode, host_id))
            c.commit()
            return self.host(host_id)

    def save_facts(self, host_id: int, facts: dict):
        with self.lock, self._db() as c:
            c.execute("UPDATE hosts SET facts_json=?, checked_at=? WHERE id=?",
                      (json.dumps(facts, ensure_ascii=False), now(), host_id))
            c.commit()
            return self.host(host_id)

    def jobs(self):
        with self._db() as c:
            rows = c.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 50").fetchall()
            return [self._row(row) for row in rows]

    def job(self, id: str):
        with self._db() as c:
            return self._row(c.execute("SELECT * FROM jobs WHERE id=?", (id,)).fetchone())

    def completed_https_upgrade(self, host_id: int, origin_job_id: str):
        """Find a matching completed HTTPS upgrade without trusting a foreign job."""
        with self._db() as c:
            rows = c.execute(
                "SELECT * FROM jobs WHERE host_id=? AND project='3x-ui-https' "
                "AND status='completed' ORDER BY updated_at DESC",
                (host_id,),
            )
            for row in rows:
                job = self._row(row)
                if job["plan"].get("options", {}).get("source_job_id") == origin_job_id:
                    return job
        return None

    def new_job(self, host_id: int, project: str, plan: dict):
        jid = uuid4().hex[:16]
        with self.lock, self._db() as c:
            c.execute("INSERT INTO jobs(id,host_id,project,plan_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                      (jid, host_id, project, json.dumps(plan, ensure_ascii=False), "planned", now(), now()))
            c.commit()
        return self.job(jid)

    def delete_job(self, job_id: str) -> bool:
        """Delete a terminal/planned *local* record, never alter remote VPS.

        Preserve completed 3X-UI source jobs while an HTTPS upgrade references
        them, so credentials and HTTPS navigation do not become orphaned.
        Protect queued/running jobs under the store lock and SQL transaction.
        """
        with self.lock, self._db() as db:
            row = db.execute("SELECT id,host_id,project,status FROM jobs WHERE id=?",
                             (job_id,)).fetchone()
            if row is None:
                return False
            if row["status"] in {"queued", "running"}:
                raise ValueError("任务正在排队或执行，不能删除；请先结束任务并核对远端状态")
            if row["project"] == "3x-ui":
                dependencies = db.execute(
                    "SELECT plan_json FROM jobs WHERE host_id=? AND project='3x-ui-https'",
                    (row["host_id"],),
                ).fetchall()
                if any(json.loads(dep["plan_json"]).get("options", {}).get("source_job_id") == job_id
                       for dep in dependencies):
                    raise ValueError("存在依赖此任务的 HTTPS 升级记录，请先删除相关升级任务")
            cursor = db.execute(
                "DELETE FROM jobs WHERE id=? AND status NOT IN ('queued','running')", (job_id,))
            return cursor.rowcount == 1


    def approve(self, id: str) -> bool:
        with self.lock, self._db() as c:
            cursor = c.execute("UPDATE jobs SET status='queued', approved_at=?, updated_at=? WHERE id=? AND status='planned'",
                               (now(), now(), id))
            c.commit()
            return cursor.rowcount == 1

    def set_status(self, id: str, status: str, error: str | None = None):
        with self.lock, self._db() as c:
            c.execute("UPDATE jobs SET status=?, error=?, updated_at=? WHERE id=?",
                      (status, error, now(), id))
            c.commit()

    def log(self, id: str, text: str):
        # Upper bound protects SQLite and browsers from accidental huge logs.
        with self.lock, self._db() as c:
            current = c.execute("SELECT logs FROM jobs WHERE id=?", (id,)).fetchone()
            if current is None:
                return
            new_log = (current["logs"] + f"[{now()}] {text}\n")[-60_000:]
            c.execute("UPDATE jobs SET logs=?, updated_at=? WHERE id=?", (new_log, now(), id))
            c.commit()
