"""S-UI native IP/domain HTTPS integration and fail-closed contracts.

No real VPS, CA, DNS, UFW, or SSH is touched. Generated remote shell is
syntax checked with bash -n. API tests use a deterministic fake SSH executor.
"""
from __future__ import annotations

import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app import main
from app.catalog import build_plan
from app.sui_https import https_steps
from app.s_ui import ACCESS, STATUS, parse_access, parse_status
from app.store import Store

AUTH = {"X-Admin-Token": "test-only-" + "a" * 32}
FACTS = {
    "OS_ID": "ubuntu", "OS_VERSION": "26.10", "ARCH": "aarch64",
    "UID": "0", "FREE_KB": "5000000", "SYSTEMD": "yes",
    "SS_AVAILABLE": "yes", "SUI_PRESENT": "no", "XUI_PRESENT": "no",
    "DOCKER": "no", "COMPOSE": "no", "UDP_51820": "free",
}
RECORD = (
    "SUI_PANEL_PORT=2095\n"
    "SUI_USERNAME=nd_123456789abc\n"
    "SUI_PASSWORD=" + "a" * 48 + "\n"
    "SUI_WEB_BASE_PATH=" + "f" * 24 + "\n"
)


@pytest.mark.parametrize("identity,mode,domain", [
    ("8.8.8.8", "ip", '("webDomain", "")'),
    ("panel.example.com", "domain", '("webDomain", "panel.example.com")'),
])
def test_new_sui_install_auto_https_and_native_tls(identity, mode, domain):
    opt = {"access_mode": "https", "tls_identity": identity}
    if mode == "domain":
        opt["ssh_ipv4"] = "8.8.8.8"
    plan = build_plan("s-ui", FACTS, opt)
    assert plan["executable"] and len(plan["steps"]) == 9
    assert plan["options"]["certificate_type"] == mode
    tls = "\n".join(s["script"] for s in plan["steps"][5:])
    assert domain in tls
    assert "webCertFile" in tls and "webKeyFile" in tls
    assert '"webListen", "0.0.0.0"' in tls
    assert '"subListen": "127.0.0.1"' in tls
    assert "certbot.timer" in tls
    assert "systemctl try-restart s-ui" in tls
    assert "systemctl try-restart x-ui" not in tls
    assert "netdeploy-sui-reload.sh" in tls
    assert "netdeploy-xui-reload.sh" not in tls
    assert "curl -4" in tls and "--connect-to" in tls and "--insecure" not in tls
    assert "trap 'if [ \"$changed\" = yes ]; then restore_local || true; fi' EXIT" in tls
    assert tls.index("systemctl stop s-ui") < tls.index('("webListen", "127.0.0.1")')
    assert "ufw allow 2095/tcp" in tls
    assert "ufw allow 2096/tcp" not in tls
    assert "ufw disable" not in tls
    assert "curl | bash" not in tls
    assert "--preferred-profile shortlived" in tls if mode == "ip" else '-d "panel.example.com"' in tls
    assert not any("__IDENTITY__" in s["script"] or "__WEB_DOMAIN__" in s["script"] for s in plan["steps"])


def test_local_mode_remains_allowed_and_does_not_touch_ca():
    plan = build_plan("s-ui", FACTS, {"access_mode": "local"})
    assert len(plan["steps"]) == 5
    assert "certbot" not in "\n".join(s["script"] for s in plan["steps"])
    assert "ufw allow" not in "\n".join(s["script"] for s in plan["steps"])


def test_https_recovery_uses_four_steps_and_does_not_reinstall():
    plan = build_plan("s-ui-https", dict(FACTS, SUI_PRESENT="yes"), {
        "tls_identity": "panel.example.com", "ssh_ipv4": "8.8.8.8"})
    assert plan["executable"] and len(plan["steps"]) == 4
    scripts = "\n".join(s["script"] for s in plan["steps"])
    assert "SUI_LOCAL_ONLY_REQUIRED" in scripts
    assert "SUI_HTTPS_VERIFIED" in scripts
    assert "curl --proto '=https'" in scripts
    assert "s-ui-linux-arm64.tar.gz" not in scripts
    assert "sui admin -username" not in scripts


@pytest.mark.parametrize("bad", [
    {"access_mode": "https", "tls_identity": "127.0.0.1"},
    {"access_mode": "https", "tls_identity": "192.168.1.2"},
    {"access_mode": "https", "tls_identity": "evil;id"},
    {"access_mode": "https", "tls_identity": "panel.example.com", "ssh_ipv4": "evil;rm"},
    {"access_mode": "https", "tls_identity": "8.8.8.8", "certificate_type": "domain"},
    {"access_mode": "local", "tls_identity": "8.8.8.8"},
    {"access_mode": "https", "tls_identity": "8.8.8.8", "custom_shell": "id"},
])
def test_cert_identity_and_plan_options_are_not_injectable(bad):
    with pytest.raises(ValueError):
        build_plan("s-ui", FACTS, bad)


@pytest.mark.parametrize("change", [
    {"SUI_PRESENT": "yes"}, {"SUI_PRESENT": "unknown"}, {"UID": "1000"},
    {"ARCH": "mips"}, {"SYSTEMD": "no"}, {"OS_ID": "alpine"},
])
def test_new_sui_cannot_overwrite_or_skip_compatibility(change):
    plan = build_plan("s-ui", dict(FACTS, **change), {
        "access_mode": "https", "tls_identity": "8.8.8.8"})
    assert not plan["executable"] and plan["steps"] == []


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"),
                    reason="Linux VPS scripts are checked with bash -n")
def test_https_scripts_parse_as_bash_for_both_certificate_types():
    for identity in ("8.8.8.8", "panel.example.com"):
        for stage in https_steps(identity):
            res = subprocess.run(["bash", "-n"], input=stage["script"],
                                 text=True, capture_output=True)
            assert res.returncode == 0, (stage["label"], res.stderr)
    for script in (STATUS, ACCESS):
        res = subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True)
        assert res.returncode == 0, res.stderr



@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"),
                    reason="Isolated fake Linux commands")
def test_activation_failure_executes_local_only_rollback_with_real_sqlite(tmp_path):
    """Run a relocated Bash activation plan with fake systemctl/ss/openssl.

    Certbot files and SQLite are temporary; no sudo, UFW, VPS or CA is touched.
    An unexpected service restart failure must restore the original database
    and leave the S-UI access record without any public HTTPS marker.
    """
    import os
    import sqlite3

    root = tmp_path / "fake-vps"
    home = root / "var/lib/netdeploy/s-ui"
    db = root / "usr/local/s-ui/db/s-ui.db"
    live = root / "etc/letsencrypt/live/panel.example.com"
    fake = tmp_path / "fakebin"
    for folder in (home, db.parent, live, fake):
        folder.mkdir(parents=True, exist_ok=True)
    record = home / "install-result.env"
    record.write_text(RECORD, encoding="utf-8")
    record.chmod(0o600)
    (live / "fullchain.pem").write_text("test certificate", encoding="utf-8")
    (live / "privkey.pem").write_text("test key", encoding="utf-8")
    original = {
        "webListen": "127.0.0.1", "webCertFile": "", "webKeyFile": "",
        "webDomain": "", "webPort": "2095", "subListen": "127.0.0.1",
        "subPort": "2096", "webPath": "/" + "f"*24 + "/",
    }
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, key TEXT UNIQUE, value TEXT)")
        conn.executemany("INSERT INTO settings(key,value) VALUES (?,?)", original.items())

    def command(name, source):
        path = fake / name
        path.write_text(source, encoding="utf-8")
        path.chmod(0o755)
    command("id", "#!/bin/sh\necho 0\n")
    command("stat", '#!/bin/sh\n'
            'if [ "$1" = "-c" ] && [ "$2" = "%u" ]; then echo 0; else /usr/bin/stat "$@"; fi\n')
    command("ss", '#!/bin/sh\n'
            'case "$*" in\n'
            '  *2095*) printf "LISTEN 0 128 127.0.0.1:2095 0.0.0.0:*\\n";;\n'
            '  *2096*) printf "LISTEN 0 128 127.0.0.1:2096 0.0.0.0:*\\n";;\n'
            '  *) exit 90;;\n'
            'esac\n')
    command("openssl", '#!/bin/sh\n'
            'case "$*" in *-checkhost*|*-checkip*) echo "does match";; esac\n'
            'exit 0\n')
    commands = tmp_path / "systemctl.log"
    command("systemctl", '#!/bin/sh\n'
            'echo "$*" >> "$MOCK_SYSTEMCTL_LOG"\n'
            'case "$*" in\n'
            '  "is-active certbot.timer") echo active; exit 0;;\n'
            '  "is-active --quiet s-ui") exit 0;;\n'
            '  "is-enabled certbot.timer") echo enabled; exit 0;;\n'
            '  "restart s-ui") exit 77;;\n'
            '  "stop s-ui"|"start s-ui") exit 0;;\n'
            '  *) exit 90;;\n'
            'esac\n')

    plan = https_steps("panel.example.com", "8.8.8.8")
    script = plan[-1]["script"]
    replacements = {
        "/var/lib/netdeploy/s-ui/install-result.env": str(record),
        "/var/lib/netdeploy/s-ui/.rollback.": str(home / ".rollback."),
        "/var/lib/netdeploy/s-ui/.result.": str(home / ".result."),
        "/usr/local/s-ui/db/s-ui.db": str(db),
        "/etc/letsencrypt/live/panel.example.com": str(live),
    }
    for upstream, sandbox in replacements.items():
        script = script.replace(upstream, sandbox)
    environment = {**os.environ,
                   "PATH": str(fake) + os.pathsep + os.environ.get("PATH", ""),
                   "MOCK_SYSTEMCTL_LOG": str(commands)}
    run = subprocess.run(["bash", "-se"], input=script, capture_output=True,
                         text=True, env=environment, timeout=20)
    assert run.returncode != 0
    assert "test certificate" not in run.stdout
    with sqlite3.connect(db) as conn:
        latest = dict(conn.execute("SELECT key,value FROM settings"))
    assert latest == original, "Failed public TLS activation must restore local DB settings"
    assert record.read_text(encoding="utf-8") == RECORD
    actions = commands.read_text(encoding="utf-8")
    assert "restart s-ui" in actions, f"actions={actions!r}, error={run.stderr!r}, out={run.stdout!r}"
    assert "stop s-ui" in actions and "start s-ui" in actions
    assert actions.splitlines().index("stop s-ui") < actions.splitlines().index("start s-ui")

def test_status_and_access_only_claim_verified_https_with_matching_identity():
    raw = "SUI_INSTALLED=yes\nSUI_SERVICE=active\nSUI_MANAGED=yes\nSUI_ACCESS=https\nSUI_IDENTITY=panel.example.com\n"
    status = parse_status(raw)
    assert status["identity"] == "panel.example.com"
    assert status["access_mode"] == "https"
    host = {"hostname": "8.8.8.8", "port": 22, "username": "root"}
    access = parse_access(RECORD + "SUI_ACCESS_MODE=https\nSUI_TLS_IDENTITY=panel.example.com\n", host)
    assert access["direct_url"] == "https://panel.example.com:2095/" + "f"*24 + "/"
    assert "local_url" not in access
    assert "ssh_tunnel" not in access
    for bad in ["localhost", "10.0.0.1", "evil;id", ""]:
        with pytest.raises(ValueError):
            parse_access(RECORD + "SUI_ACCESS_MODE=https\nSUI_TLS_IDENTITY=" + bad + "\n", host)


@pytest.fixture
def sui_web(monkeypatch, tmp_path):
    data = Store(str(tmp_path / "netdeploy.db"))
    host = data.add_host({"name": "SUI test", "hostname": "8.8.8.8", "port": 22,
                          "username": "root", "tls_domain": "panel.example.com"})
    class SSH:
        def __init__(self):
            self.facts = dict(FACTS)
            self.state = "SUI_INSTALLED=no\n"
            self.access = RECORD + "SUI_ACCESS_MODE=local\n"
        def credential_ready(self, host):
            return True
        def preflight(self, host):
            return dict(self.facts)
        def run(self, host, script, timeout=25):
            if "SUI_INSTALLED=" in script:
                return self.state
            if "SUI_ACCESS_MODE=%s" in script:
                return self.access
            raise AssertionError("Unexpected SSH script")
    ssh = SSH()
    monkeypatch.setattr(main, "store", data)
    monkeypatch.setattr(main, "executor", ssh)
    client = TestClient(main.app)
    return client, data, host, ssh


def test_new_job_defaults_to_domain_https_and_existing_can_upgrade(sui_web):
    client, data, host, ssh = sui_web
    first = client.post("/api/jobs", headers=AUTH, json={"host_id":host["id"], "project":"s-ui"})
    assert first.status_code == 200, first.text
    created = first.json()
    assert created["plan"]["options"]["certificate_type"] == "domain"
    assert created["plan"]["options"]["tls_identity"] == "panel.example.com"
    assert created["plan"]["options"]["ssh_ipv4"] == "8.8.8.8"
    assert len(created["plan"]["steps"]) == 9
    assert created["status"] == "planned"

    # Simulate S-UI installed but the ACME phase did not finish.
    ssh.facts["SUI_PRESENT"] = "yes"
    ssh.state = "SUI_INSTALLED=yes\nSUI_SERVICE=active\nSUI_MANAGED=yes\nSUI_ACCESS=local\n"
    upgrade = client.post("/api/jobs", headers=AUTH, json={"host_id":host["id"],"project":"s-ui-https"})
    assert upgrade.status_code == 200, upgrade.text
    assert len(upgrade.json()["plan"]["steps"]) == 4
    assert data.job(upgrade.json()["id"])["status"] == "planned"
    # Already installed but a new initial install would overwrite; must block it.
    duplicate = client.post("/api/jobs", headers=AUTH, json={"host_id":host["id"],"project":"s-ui"})
    assert duplicate.status_code == 409


def test_access_denies_unverified_and_does_not_leak_password_by_status(sui_web):
    client, data, host, ssh = sui_web
    ssh.state = ("SUI_INSTALLED=yes\nSUI_SERVICE=active\nSUI_MANAGED=yes\n"
                 "SUI_ACCESS=https\nSUI_IDENTITY=panel.example.com\n")
    ssh.access = RECORD + "SUI_ACCESS_MODE=https\nSUI_TLS_IDENTITY=panel.example.com\n"
    url = f"/api/hosts/{host['id']}/s-ui/access"
    assert client.get(url).status_code == 401
    result = client.get(url, headers=AUTH)
    assert result.status_code == 200, result.text
    assert result.json()["direct_url"].startswith("https://panel.example.com:2095/")
    status = client.get(f"/api/hosts/{host['id']}/s-ui", headers=AUTH)
    assert status.status_code == 200
    assert "SUI_PASSWORD" not in status.text and "a"*48 not in status.text
    ssh.access = RECORD + "SUI_ACCESS_MODE=https\nSUI_TLS_IDENTITY=other.example.com\n"
    assert client.get(url, headers=AUTH).status_code == 409
    ssh.state = "SUI_INSTALLED=yes\nSUI_SERVICE=active\nSUI_MANAGED=yes\nSUI_ACCESS=unverified\n"
    assert client.get(url, headers=AUTH).status_code == 409
