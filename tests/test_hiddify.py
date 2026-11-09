import json
import os
from pathlib import Path
import shutil
import subprocess

from fastapi.testclient import TestClient
import pytest

from app import hiddify, main
from app.catalog import build_plan
from app.hiddify import (
    ADMIN_LINKS, PRECHECK, STATUS, select_admin_link, steps,
)
from app.store import Store


FACTS = {
    "OS_ID": "ubuntu", "OS_VERSION": "24.04", "ARCH": "x86_64",
    "UID": "0", "FREE_KB": "8000000", "HIDDIFY_STATE": "ready",
}


def test_hiddify_plan_uses_official_release_entrypoint_and_keeps_output_private():
    plan = build_plan("hiddify", FACTS)
    assert plan["executable"]
    install, verify = [step["script"] for step in plan["steps"]]
    assert "https://i.hiddify.com/release" in install
    assert 'test -s release.sh' in install
    assert 'NO_UI=true timeout -k 20s 35m bash ./release.sh' in install
    assert 'flock -n 9' in install
    assert '</dev/null >"$log" 2>&1' in install
    assert 'systemctl is-active --quiet hiddify-panel.service' in verify


@pytest.mark.parametrize("change", [
    {"HIDDIFY_STATE": "existing"}, {"HIDDIFY_STATE": "ports"},
    {"HIDDIFY_STATE": "services"}, {"HIDDIFY_STATE": "tools"},
    {"HIDDIFY_STATE": "systemd"}, {"HIDDIFY_STATE": "memory"},
    {"HIDDIFY_STATE": "ssh"}, {"HIDDIFY_STATE": None},
    {"OS_ID": "debian"}, {"OS_VERSION": "20.04"}, {"ARCH": "mips"},
    {"UID": "1000"}, {"FREE_KB": "4999999"},
])
def test_hiddify_plan_blocks_incompatible_targets(change):
    plan = build_plan("hiddify", {**FACTS, **change})
    assert not plan["executable"]
    assert plan["issues"]
    assert not plan["steps"]


@pytest.fixture
def bash_path():
    if os.name == "nt":
        git = shutil.which("git")
        bash = Path(git).resolve().parent.parent / "bin" / "bash.exe" if git else None
        if bash and not bash.is_file():
            bash = None
    else:
        bash = shutil.which("bash")
    if not bash:
        pytest.skip("Bash is required to exercise the VPS precheck")
    return str(bash)


@pytest.fixture
def run_hiddify_precheck(tmp_path, bash_path):
    (tmp_path / "os-release").write_bytes(b'ID=ubuntu\nVERSION_ID="24.04"\n')
    (tmp_path / "meminfo").write_bytes(b"MemTotal: 2000000 kB\n")
    precheck = PRECHECK.replace("/etc/os-release", "./os-release")
    precheck = precheck.replace("/proc/meminfo", "./meminfo").replace("/proc/", "./proc/")
    for prefix in ("/opt/hiddify", "/usr/bin/hiddify", "/usr/local/bin/hiddify", "/var/log/netdeploy-hiddify"):
        precheck = precheck.replace(prefix, "." + prefix)

    fake_vps = r"""
command() {
  case "$2" in
    ss|curl|sha256sum|flock|timeout|systemctl|systemd-detect-virt) return 0 ;;
    *) return 1 ;;
  esac
}
ps() { echo systemd; }
systemd-detect-virt() { return 1; }
ss() {
  echo 'tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:*'
  printf '%s\n' "$ND_LISTENERS"
}
readlink() {
  case "$1" in
    ./proc/1473/exe) printf '%s\n' "$ND_METRICS_EXE" ;;
    ./proc/1487/exe) echo /opt/google-cloud-ops-agent/subagents/fluent-bit/bin/fluent-bit ;;
    *) return 1 ;;
  esac
}
systemctl() {
  # Ubuntu 24.04 exits with 1 if the name filter finds no unit files.
  case "$*" in *'hiddify*.service'*) return 1 ;; esac
  printf '%s\n' "$ND_UNIT_LIST"
  return "$ND_UNIT_STATUS"
}
"""
    def run(
        unit_list="ssh.service enabled enabled", unit_status="0", listeners="",
        metrics_exe="/opt/google-cloud-ops-agent/subagents/opentelemetry-collector/otelopscol",
        metrics_cgroup="/system.slice/google-cloud-ops-agent-opentelemetry-collector.service",
    ):
        for pid, group in ((1473, metrics_cgroup), (1487, "/system.slice/google-cloud-ops-agent-fluent-bit.service")):
            path = tmp_path / "proc" / str(pid) / "cgroup"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"0::{group}\n".encode("ascii"))
        result = subprocess.run(
            [bash_path, "--noprofile", "--norc", "-se"],
            input=(fake_vps + precheck + "\nhiddify_precheck\n").encode("ascii"),
            cwd=tmp_path, capture_output=True, timeout=10, check=True,
            env={**os.environ, "SSH_CONNECTION": "192.0.2.10 54321 192.0.2.20 22",
                 "ND_UNIT_LIST": unit_list, "ND_UNIT_STATUS": unit_status,
                 "ND_LISTENERS": listeners, "ND_METRICS_EXE": metrics_exe},
        )
        return result.stdout.decode("ascii").strip()

    return run


@pytest.mark.parametrize(("unit_list", "unit_status", "expected"), [
    ("ssh.service enabled enabled", "0", "ready"),
    ("ssh.service enabled enabled\nhiddify-panel.service disabled enabled", "0", "existing"),
    ("", "1", "unit_files"),
])
def test_hiddify_precheck_distinguishes_no_matching_unit_from_systemctl_failure(
    run_hiddify_precheck, unit_list, unit_status, expected,
):
    assert run_hiddify_precheck(unit_list, unit_status) == expected
    if expected != "ready":
        assert not build_plan("hiddify", {**FACTS, "HIDDIFY_STATE": expected})["executable"]


OPS_METRICS = 'tcp LISTEN 0 128 [::]:20201 [::]:* users:(("otelopscol",pid=1473,fd=3))'
OPS_LOGS = 'tcp LISTEN 0 128 0.0.0.0:20202 0.0.0.0:* users:(("fluent-bit",pid=1487,fd=146))'


@pytest.mark.parametrize(("listeners", "process_override", "expected"), [
    pytest.param([OPS_METRICS, OPS_LOGS], {}, "ready", id="packaged-ops-agent"),
    pytest.param([OPS_METRICS], {"metrics_exe": "/usr/bin/otelopscol"}, "services", id="different-binary"),
    pytest.param([OPS_METRICS], {"metrics_cgroup": "/system.slice/custom.service"}, "services", id="different-service"),
    pytest.param([OPS_METRICS.split(" users:")[0]], {}, "services", id="unverified-owner"),
    pytest.param([OPS_METRICS.replace("fd=3))", 'fd=3),("other",pid=1488,fd=4))')], {}, "services", id="shared-socket"),
    pytest.param([OPS_METRICS, "tcp LISTEN 0 128 0.0.0.0:8080 0.0.0.0:*"], {}, "services", id="extra-listener"),
    pytest.param([OPS_LOGS, "tcp LISTEN 0 128 0.0.0.0:443 0.0.0.0:*"], {}, "ports", id="https-conflict"),
])
def test_hiddify_precheck_exempts_only_verified_ops_agent_listeners(
    run_hiddify_precheck, listeners, process_override, expected,
):
    assert run_hiddify_precheck(listeners="\n".join(listeners), **process_override) == expected


def test_hiddify_installer_keeps_staging_private_and_uses_service_compatible_umask(tmp_path, bash_path):
    install = steps()[0]["script"].replace(PRECHECK, "\nhiddify_precheck() { echo ready; }\n")
    install = install.replace("/run/lock/netdeploy-hiddify.lock", "./install.lock")
    install = install.replace("/var/log/netdeploy-hiddify.XXXXXX.log", "../netdeploy-hiddify.XXXXXX.log")
    install = install.replace("""trap 'rm -rf -- "$work"' EXIT""", "")
    fake_vps = r"""
export TMPDIR="$PWD"
id() { echo 0; }
uname() { echo x86_64; }
df() { printf 'header\nfs 0 0 8000000 0 /\n'; }
flock() { :; }
curl() {
  case "$*" in *' https://i.hiddify.com/release') ;; *) return 1 ;; esac
  cat > release.sh <<'RELEASE'
set -eu
test "$NO_UI" = true
test ! -t 0
printf 'installer_mask=%s\n' "$(umask)"
RELEASE
}
mktemp() {
  printf 'staging_mask=%s\n' "$(umask)" >&2
  command mktemp "$@"
}
timeout() { shift 3; "$@"; }
"""
    result = subprocess.run(
        [bash_path, "--noprofile", "--norc", "-se"],
        input=(fake_vps + install).encode("utf-8"),
        cwd=tmp_path, capture_output=True, timeout=10, check=True,
    )
    assert result.stderr.splitlines() == [b"staging_mask=0077", b"staging_mask=0077"]
    log, = tmp_path.glob("netdeploy-hiddify.*.log")
    assert log.read_bytes() == b"installer_mask=0022\n"
    if os.name != "nt":
        assert log.stat().st_mode & 0o777 == 0o600


ADMIN_PATH = "/panel-path/12345678-1234-1234-1234-123456789abc/"


def test_hiddify_admin_url_requires_a_recognized_https_destination(monkeypatch):
    host = {"hostname": "192.0.2.10", "tls_domain": "panel.example.com"}
    rejected = [
        "http://192.0.2.10" + ADMIN_PATH,
        "https://other.example.com" + ADMIN_PATH,
        "https://panel.example.com.other.example.com" + ADMIN_PATH,
        "https://other.example.com@192.0.2.10" + ADMIN_PATH,
        "https://192.0.2.10:9000" + ADMIN_PATH,
        "https://192.0.2.10" + ADMIN_PATH + "?next=https://other.example.com",
        "https://192.0.2.10/other-path",
    ]
    direct = "https://192.0.2.10" + ADMIN_PATH
    domain = "https://panel.example.com" + ADMIN_PATH
    probes = []

    def check_tls(name, address):
        probes.append((name, address))
        return name == "192.0.2.10"

    monkeypatch.setattr(hiddify, "_tls_verified", check_tls)
    with pytest.raises(ValueError):
        select_admin_link(json.dumps(rejected), host)
    assert probes == []
    assert select_admin_link(json.dumps([direct, domain]), host) == {"url": direct, "tls_verified": True}
    assert probes == [("panel.example.com", "panel.example.com"), ("192.0.2.10", "192.0.2.10")]
    probes.clear()
    assert select_admin_link(json.dumps([domain, direct]), {"hostname": "192.0.2.10"})["url"] == direct
    assert probes == [("192.0.2.10", "192.0.2.10")]


@pytest.mark.parametrize("addresses, expected", [
    (["8.8.4.4"], True),
    (["8.8.4.4", "192.0.2.5"], False),
    (["127.0.0.1"], False),
])
def test_hiddify_prefers_a_trusted_domain_that_resolves_only_to_the_vps(monkeypatch, addresses, expected):
    direct = "https://8.8.4.4" + ADMIN_PATH
    domain = "https://panel.example.com" + ADMIN_PATH
    probes = []

    def resolve(name, port, *, type):
        assert name == "panel.example.com"
        assert port == 443
        return [(None, None, None, "", (address, port)) for address in addresses]

    def check_tls(name, address):
        probes.append((name, address))
        return name == "panel.example.com"

    monkeypatch.setattr(hiddify.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(hiddify, "_tls_verified", check_tls)
    result = select_admin_link(json.dumps([direct, domain]), {"hostname": "8.8.4.4"})
    assert result == {"url": domain if expected else direct, "tls_verified": expected}
    assert probes == ([("8.8.4.4", "8.8.4.4"), ("panel.example.com", "8.8.4.4")] if expected
                      else [("8.8.4.4", "8.8.4.4")])


def test_existing_hiddify_status_is_read_only_and_bound_to_the_saved_host(tmp_path, monkeypatch):
    db = Store(str(tmp_path / "netdeploy.sqlite"))
    monkeypatch.setattr(main, "store", db)
    host = db.add_host({"name": "Test VPS", "hostname": "192.0.2.10", "port": 22, "username": "root"})
    plan = build_plan("hiddify", {**FACTS, "HIDDIFY_STATE": "existing"})
    plan.update(hostname=host["hostname"], trust_epoch=host["trust_epoch"])
    job = db.new_job(host["id"], "hiddify", plan)
    stale = db.new_job(host["id"], "hiddify", {**plan, "trust_epoch": 99})
    state = "running"
    calls = []

    def read(target, script, timeout):
        assert target["id"] == host["id"]
        calls.append(target["id"])
        if script == ADMIN_LINKS:
            return json.dumps(["https://192.0.2.10" + ADMIN_PATH])
        assert script == STATUS
        return f"HIDDIFY_STATUS={state}\n"

    monkeypatch.setattr(main.executor, "credential_ready", lambda host: True)
    monkeypatch.setattr(main.executor, "run", read)
    monkeypatch.setattr(hiddify, "_tls_verified", lambda name, address: False)
    client = TestClient(main.app)
    headers = {"X-Admin-Token": main.ADMIN_TOKEN}
    path = f'/api/jobs/{job["id"]}/hiddify-status'
    assert client.get(path, headers=headers).json() == {"status": "running"}
    state = "incomplete"
    assert client.get(path, headers=headers).json() == {"status": "incomplete"}
    assert client.get(f'/api/jobs/{stale["id"]}/hiddify-status', headers=headers).status_code == 409
    admin_path = f'/api/jobs/{job["id"]}/hiddify-admin'
    assert client.get(admin_path).status_code == 401
    assert client.get(f'/api/jobs/{stale["id"]}/hiddify-admin', headers=headers).status_code == 409
    admin = client.get(admin_path, headers=headers)
    assert admin.json() == {"url": "https://192.0.2.10" + ADMIN_PATH, "tls_verified": False}
    assert admin.headers["Cache-Control"] == "no-store"
    assert len(calls) == 3
    assert db.job(job["id"]) == job
    assert len(db.jobs()) == 2


def test_hiddify_approval_rechecks_the_dedicated_host(tmp_path, monkeypatch):
    db = Store(str(tmp_path / "netdeploy.sqlite"))
    monkeypatch.setattr(main, "store", db)
    host = db.add_host({
        "name": "Test VPS", "hostname": "192.0.2.10",
        "port": 22, "username": "root",
    })
    latest = FACTS.copy()
    enqueued = []

    def preflight(target, *, include_hiddify=False):
        assert target["id"] == host["id"]
        assert include_hiddify
        return latest.copy()

    monkeypatch.setattr(main.executor, "preflight", preflight)
    monkeypatch.setattr(main.executor, "credential_ready", lambda host: True)
    monkeypatch.setattr(main.runner, "enqueue", lambda job, host, phrase: enqueued.append(job["id"]))
    client = TestClient(main.app)
    headers = {"X-Admin-Token": main.ADMIN_TOKEN}
    response = client.post("/api/jobs", headers=headers, json={"host_id": host["id"], "project": "hiddify"})
    assert response.status_code == 200
    assert response.json()["plan"]["executable"]

    def choose_project(context):
        assert context["projects"]["hiddify"] == "Hiddify Manager"
        assert "plan:hiddify" in context["actions"]
        return {"action": "plan:hiddify", "host_id": host["id"], "message": "已选择专用 VPS"}

    monkeypatch.setattr(main, "interpret_panel_command", choose_project)
    codex = client.post("/api/codex/command", headers=headers, json={
        "prompt": "为 Test VPS 生成 Hiddify Manager 部署方案",
    })
    assert codex.status_code == 200
    job = codex.json()["job"]
    assert job["status"] == "planned" and job["plan"]["executable"]
    assert not enqueued
    approval = f'/api/jobs/{job["id"]}/approve'

    legacy = {"confirmation": main.runner.approval_text(job, host)}
    assert client.post(approval, headers=headers, json=legacy).status_code == 409
    latest["HIDDIFY_STATE"] = "ports"
    blocked = client.post(approval, headers=headers, json={"confirmed_risk": True})
    assert blocked.status_code == 409
    assert not enqueued

    latest["HIDDIFY_STATE"] = "ready"
    approved = client.post(approval, headers=headers, json={"confirmed_risk": True})
    assert approved.status_code == 200
    assert enqueued == [job["id"]]
