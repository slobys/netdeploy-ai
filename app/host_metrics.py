"""Small, read-only Linux samples through the existing verified SSH executor."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import BoundedSemaphore, Lock
from time import monotonic

from .executor import SSHError

SAMPLE = """export LC_ALL=C
printf 'ND_CPU_FIRST '; awk '$1 == "cpu" {print; exit}' /proc/stat
sleep 0.5
printf 'ND_CPU_LAST '; awk '$1 == "cpu" {print; exit}' /proc/stat
awk '$1 == "MemTotal:" || $1 == "MemAvailable:" {print "ND_" $1, $2}' /proc/meminfo
df -P / | awk 'NR==2 && $5 ~ /^[0-9]+%$/ {print "ND_DISK", $5}'
"""


def parse_sample(output: str) -> dict[str, float | None]:
    rows = {}
    for line in output.splitlines():
        key, _, value = line.partition(" ")
        if key.startswith("ND_"):
            rows[key] = value.split()
    cpu = memory = disk = None
    first = rows.get("ND_CPU_FIRST", [])
    last = rows.get("ND_CPU_LAST", [])
    if len(first) >= 9 and len(last) >= 9 and first[0] == last[0] == "cpu":
        ticks = [int(after) - int(before) for before, after in zip(first[1:9], last[1:9])]
        if min(ticks) >= 0 and (total := sum(ticks)) > 0:
            cpu = round(100 * (total - ticks[3] - ticks[4]) / total, 1)
    if rows.get("ND_MemTotal:") and rows.get("ND_MemAvailable:"):
        total = int(rows["ND_MemTotal:"][0])
        available = int(rows["ND_MemAvailable:"][0])
        if total > 0 and 0 <= available <= total:
            memory = round(100 * (total - available) / total, 1)
    if rows.get("ND_DISK") and rows["ND_DISK"][0].endswith("%"):
        disk = min(100, max(0, int(rows["ND_DISK"][0][:-1])))
    return {"cpu": cpu, "memory": memory, "disk": disk}


class HostMetrics:
    def __init__(self):
        self._lock = Lock()
        self._slots = BoundedSemaphore(3)
        self._running = set()
        self._cache = {}

    def read(self, host: dict, executor) -> dict:
        if not executor.credential_ready(host):
            return {"status": "credentials"}
        try:
            pins = executor.pinned_hostkeys(host)
        except SSHError:
            return {"status": "trust"}
        if not pins:
            return {"status": "trust"}

        key = (host["id"], host["hostname"], host["port"], host["username"],
               host.get("auth_mode"), host.get("trust_epoch"),
               tuple(pin["fingerprint"] for pin in pins))
        with self._lock:
            now = monotonic()
            self._cache = {k: value for k, value in self._cache.items() if value[0] > now}
            if key in self._cache:
                return self._cache[key][1]
            if key in self._running or not self._slots.acquire(blocking=False):
                return {"status": "sampling"}
            self._running.add(key)
        try:
            result = self._sample(host, executor)
            with self._lock:
                self._cache[key] = (monotonic() + 20, result)
            return result
        finally:
            with self._lock:
                self._running.remove(key)
                self._slots.release()

    @staticmethod
    def _sample(host, executor):
        checked_at = datetime.now(timezone.utc).isoformat()
        try:
            output = executor.run(host, SAMPLE, timeout=9)
        except (SSHError, OSError) as exc:
            code = str(exc).split("：", 1)[0]
            status = {
                "SSH_HOST_KEY_CHANGED": "trust",
                "SSH_HOST_KEY_UNTRUSTED": "trust",
                "SSH_AUTH_FAILED": "auth_failed",
            }.get(code, "unreachable")
            # SSH errors can contain remote output. Only send a fixed status.
            return {"status": status, "checked_at": checked_at}
        try:
            values = parse_sample(output)
        except ValueError:
            values = {"cpu": None, "memory": None, "disk": None}
        return {"status": "connected", "checked_at": checked_at, **values}
