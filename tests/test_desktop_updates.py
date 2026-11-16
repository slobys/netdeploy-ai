import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app.desktop_update import backup, FILES

ROOT = Path(__file__).resolve().parents[1]


def test_update_backup_preserves_database_authorization_and_window(tmp_path):
    home = tmp_path / "用户数据"
    (home / "data").mkdir(parents=True)
    with sqlite3.connect(home / "data/netdeploy.db") as connection:
        connection.execute("CREATE TABLE jobs(id, status)")
        connection.execute("INSERT INTO jobs VALUES(1, 'completed')")
    expected = {}
    for name in FILES:
        file = home / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(("private test data " + name).encode())
        expected[name] = hashlib.sha256(file.read_bytes()).hexdigest()
    first = backup(home)
    second = backup(home)
    assert first != second and (first / "COMPLETE").exists()
    assert json.loads((first / "manifest.json").read_text()) == expected
    for name in FILES:
        assert (home / name).read_bytes() == (first / name).read_bytes()
    with sqlite3.connect(first / "data/netdeploy.db") as connection:
        assert connection.execute("SELECT * FROM jobs").fetchall() == [(1, "completed")]


def test_failed_backup_is_not_marked_complete(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/netdeploy.db").write_bytes(b"broken database")
    with pytest.raises(sqlite3.DatabaseError):
        backup(tmp_path)
    assert not list((tmp_path / "update-backups").glob("*/COMPLETE"))


@pytest.mark.skipif(sys.platform != "win32", reason="Requires .NET Framework compiler")
def test_native_update_download_and_validation(tmp_path):
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    target = tmp_path / "updates-test.exe"
    subprocess.run([str(compiler), "/nologo", "/target:exe", "/reference:System.Net.Http.dll",
                    "/reference:System.Web.Extensions.dll", f"/out:{target}",
                    str(ROOT / "packaging/windows/DesktopUpdates.cs"),
                    str(ROOT / "tests/desktop_updates_harness.cs")], check=True, timeout=30)
    subprocess.run([str(target), str(tmp_path)], check=True, timeout=30)
