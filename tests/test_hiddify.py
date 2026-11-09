import os
from pathlib import Path
import shutil
import subprocess

from fastapi.testclient import TestClient
import pytest

from app import main
from app.catalog import build_plan
from app.hiddify import COMMIT, INSTALLER_SHA256, PRECHECK, UTILS_SHA256, VERSION
from app.store import Store


FACTS = {
    "OS_ID": "ubuntu", "OS_VERSION": "24.04", "ARCH": "x86_64",
    "UID": "0", "FREE_KB": "8000000", "HIDDIFY_STATE": "ready",
}


def test_hiddify_plan_pins_official_install_and_keeps_output_private():
    plan = build_plan("hiddify", FACTS)
    assert plan["executable"]
    install, verify = [step["script"] for step in plan["steps"]]
    for value in (VERSION, COMMIT, INSTALLER_SHA256, UTILS_SHA256):
        assert value in install
    assert 'sha256sum --check --status' in install
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


@pytest.mark.parametrize(("unit_list", "unit_status", "expected"), [
    ("ssh.service enabled enabled", "0", "ready"),
    ("ssh.service enabled enabled\nhiddify-panel.service disabled enabled", "0", "existing"),
    ("", "1", "unit_files"),
])
def test_hiddify_precheck_distinguishes_no_matching_unit_from_systemctl_failure(
    tmp_path, unit_list, unit_status, expected,
):
    if os.name == "nt":
        git = shutil.which("git")
        bash = Path(git).resolve().parent.parent / "bin" / "bash.exe" if git else None
        if bash and not bash.is_file():
            bash = None
    else:
        bash = shutil.which("bash")
    if not bash:
        pytest.skip("Bash is required to exercise the VPS precheck")

    (tmp_path / "os-release").write_bytes(b'ID=ubuntu\nVERSION_ID="24.04"\n')
    (tmp_path / "meminfo").write_bytes(b"MemTotal: 2000000 kB\n")
    precheck = PRECHECK.replace("/etc/os-release", "./os-release").replace("/proc/meminfo", "./meminfo")
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
ss() { echo 'tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:*'; }
systemctl() {
  # Ubuntu 24.04 exits with 1 if the name filter finds no unit files.
  case "$*" in *'hiddify*.service'*) return 1 ;; esac
  printf '%s\n' "$ND_UNIT_LIST"
  return "$ND_UNIT_STATUS"
}
"""
    result = subprocess.run(
        [str(bash), "--noprofile", "--norc", "-se"],
        input=(fake_vps + precheck + "\nhiddify_precheck\n").encode("ascii"),
        cwd=tmp_path, capture_output=True, timeout=10, check=True,
        env={**os.environ, "SSH_CONNECTION": "192.0.2.10 54321 192.0.2.20 22",
             "ND_UNIT_LIST": unit_list, "ND_UNIT_STATUS": unit_status},
    )
    assert result.stdout.decode("ascii").strip() == expected
    if expected != "ready":
        assert not build_plan("hiddify", {**FACTS, "HIDDIFY_STATE": expected})["executable"]


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
