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
                  auth_mode TEXT NOT NULL DEFAULT 'key',
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
            cursor = c.execute("INSERT INTO hosts(name,hostname,port,username,auth_mode,created_at) VALUES(?,?,?,?,?,?)",
                               (data["name"], data["hostname"], data["port"], data["username"], data.get("auth_mode", "key"), now()))
            c.commit()
            return self.host(cursor.lastrowid)

    def update_auth(self, host_id: int, auth_mode: str) -> dict:
        if auth_mode not in {"key", "password"}:
            raise ValueError("不支持的 SSH 认证方式")
        with self.lock, self._db() as c:
            active = c.execute("SELECT COUNT(*) FROM jobs WHERE host_id=? AND status IN ('queued','running')", (host_id,)).fetchone()[0]
            if active:
                raise ValueError("服务器存在执行中的任务，不能更换 SSH 凭据")
            c.execute("UPDATE hosts SET auth_mode=?, facts_json=NULL, checked_at=NULL WHERE id=?",
                      (auth_mode, host_id))
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

    def new_job(self, host_id: int, project: str, plan: dict):
        jid = uuid4().hex[:16]
        with self.lock, self._db() as c:
            c.execute("INSERT INTO jobs(id,host_id,project,plan_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                      (jid, host_id, project, json.dumps(plan, ensure_ascii=False), "planned", now(), now()))
            c.commit()
        return self.job(jid)

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
