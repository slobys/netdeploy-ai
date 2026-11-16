"""Offline pre-update backup; never instantiate the application Store."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import uuid


FILES = (
    "settings.json", "data/known_hosts", "ssh_key", "window-main.json", "window-panel.json",
    "codex-native/auth/auth.json", "codex-native/auth/config.toml",
)


def backup(home: Path) -> Path:
    home = home.resolve(strict=True)
    target = home / "update-backups" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
    target.mkdir(parents=True)
    manifest = {}
    database = home / "data/netdeploy.db"
    if database.is_file():
        (target / "data").mkdir()
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as source:
            with sqlite3.connect(target / "data/netdeploy.db") as destination:
                source.backup(destination)
                if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise RuntimeError("更新前数据库备份验证失败。")
    for name in FILES:
        source = home / name
        if source.is_file():
            output = target / name
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, output)
            manifest[name] = hashlib.sha256(output.read_bytes()).hexdigest()
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (target / "COMPLETE").write_text("Backup completed before installation.\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    print(backup(parser.parse_args().home))
