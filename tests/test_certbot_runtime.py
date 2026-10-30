"""Offline regression: Debian 13 Certbot 4.0.0 -> isolated IP-capable Certbot.

Runs no real APT, SSH, ACME requests, certbot, or systemd changes.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.certbot_runtime import IP_BOOTSTRAP, IP_CERTBOT_BIN, IP_CERTBOT_VERSION, IP_CONFIG_DIR
from app.https_upgrade import https_steps, https_access_script
from app.sui_https import https_steps as sui_https_steps
from app.s_ui import STATUS as SUI_STATUS, ACCESS as SUI_ACCESS


def test_ip_uses_isolated_certbot_and_domain_keeps_os_certbot():
    ip, domain = https_steps("8.8.8.8", 8443), https_steps("panel.example.com", 8443)
    assert len(ip) == len(domain) == 4
    install = ip[1]["script"]
    assert 'test -x "$client"' in install
    assert "certbot==" + IP_CERTBOT_VERSION in install
    assert 'python3 -m venv "$venv"' in install
    assert "--index-url https://pypi.org/simple" in install
    assert "netdeploy-certbot-renew.timer" in install
    assert "systemctl enable --now certbot.timer" not in install
    assert "apt-get remove" not in install and "apt-get purge" not in install
    assert "/usr/bin/certbot" not in install

    issuance = ip[2]["script"]
    assert "--preferred-profile shortlived" in issuance
    assert '--ip-address "8.8.8.8"' in issuance
    assert f"{IP_CERTBOT_BIN} --config-dir {IP_CONFIG_DIR}" in issuance
    assert "/etc/netdeploy/letsencrypt/live/8.8.8.8/" in issuance
    assert "netdeploy-certbot-renew.timer" in issuance
    assert "certbot.timer" not in issuance
    assert "/etc/netdeploy/letsencrypt/renewal-hooks/deploy/netdeploy-xui-reload.sh" in issuance
    assert 'test "$(systemctl is-active netdeploy-certbot-renew.timer)" = active' in ip[3]["script"]
    assert 'test -s "/etc/netdeploy/letsencrypt/live/8.8.8.8/' in ip[2]["script"]
    assert "trap restore_local_listener EXIT" in ip[3]["script"]
    assert "ufw allow 8443/tcp" in ip[3]["script"]

    assert "certbot certonly" in domain[2]["script"]
    assert "certbot.timer" in domain[2]["script"]
    assert "/etc/letsencrypt/live/panel.example.com/" in domain[2]["script"]
    assert "/opt/netdeploy-certbot/" not in "\n".join(x["script"] for x in domain)
    assert "netdeploy-certbot-renew.timer" not in "\n".join(x["script"] for x in domain)


def test_sui_ip_uses_same_isolated_runtime_and_https_access_is_not_http():
    ip, domain = sui_https_steps("8.8.8.8"), sui_https_steps("panel.example.com","8.8.8.8")
    assert len(ip) == len(domain) == 4
    assert "netdeploy-certbot-renew.timer" in ip[1]["script"]
    assert IP_CERTBOT_BIN in ip[2]["script"]
    assert "netdeploy-sui-reload.sh" in ip[2]["script"]
    assert "netdeploy-xui-reload.sh" not in ip[2]["script"]
    assert "/etc/netdeploy/letsencrypt/live/8.8.8.8" in ip[2]["script"]
    assert "/etc/netdeploy/letsencrypt/live/8.8.8.8/fullchain.pem" in ip[3]["script"]
    assert "netdeploy-certbot-renew.timer" in ip[3]["script"]
    assert '"subListen": "127.0.0.1"' in ip[3]["script"]
    assert "ufw allow 2096/tcp" not in ip[3]["script"]
    assert "/etc/letsencrypt/live/panel.example.com/" in domain[3]["script"]
    assert "certbot.timer" in domain[3]["script"]
    assert "netdeploy-certbot-renew.timer" in SUI_STATUS
    assert "cert_root='/etc/letsencrypt'" in SUI_STATUS
    assert 'if [ "$access_mode" = local ]; then' in SUI_ACCESS
    assert SUI_ACCESS.index('if [ "$access_mode" = local ]; then') < SUI_ACCESS.index("http://127.0.0.1:2095")
    assert "elif sui_https_verified; then" in SUI_ACCESS


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                    reason="Isolated Linux shell test")
def test_debian13_apt4_bootstrap_installs_newer_ip_certbot_and_can_retry(tmp_path: Path):
    root, tools, fake = (tmp_path / "fake-vps", tmp_path / "tools", tmp_path / "bin")
    for folder in (tools, fake, root / "run/systemd/system", root / "etc/systemd/system"):
        folder.mkdir(parents=True, exist_ok=True)
    log = tmp_path / "commands.log"

    def executable(folder, name, content):
        file = folder / name
        file.write_text(content, encoding="utf-8")
        file.chmod(0o755)
        return file

    old = executable(fake, "certbot", "#!/bin/sh\necho 'certbot 4.0.0'\n")
    executable(fake, "id", "#!/bin/sh\n[ \"$1\" = -u ] && echo 0\n")
    executable(fake, "apt-get",
               "#!/bin/sh\nprintf 'apt %s\\n' \"$*\" >> \"$MOCK_CALLS\"\nexit 0\n")
    executable(fake, "python3", """#!/bin/sh
if [ "$1" != -m ] || [ "$2" != venv ]; then exit 75; fi
mkdir -p "$3/bin"
cp "$MOCK_TOOLS/pip" "$3/bin/pip"
cp "$MOCK_TOOLS/python" "$3/bin/python"
printf 'venv %s\n' "$3" >> "$MOCK_CALLS"
""")
    executable(tools, "python", "#!/bin/sh\nexit 0\n")
    executable(tools, "pip", """#!/bin/sh
printf 'pip %s\n' "$*" >> "$MOCK_CALLS"
if [ "$MOCK_FAIL_PIP" = 1 ]; then exit 63; fi
cp "$MOCK_TOOLS/newcertbot" "$(dirname "$0")/certbot"
""")
    executable(tools, "newcertbot", """#!/bin/sh
case "$*" in
  *--help*) echo '--ip-address --preferred-profile' ;;
  *--version*) echo 'certbot 5.8.0' ;;
  *) exit 73 ;;
esac
""")
    executable(fake, "systemctl", """#!/bin/sh
printf 'systemctl %s\n' "$*" >> "$MOCK_CALLS"
if [ "$1" = list-unit-files ]; then echo 'netdeploy-certbot-renew.timer enabled'; fi
""")
    script = IP_BOOTSTRAP
    roots = {
        "/opt/netdeploy-certbot": root / "opt/netdeploy-certbot",
        "/etc/netdeploy/letsencrypt": root / "etc/netdeploy/letsencrypt",
        "/var/lib/netdeploy/certbot": root / "var/lib/netdeploy/certbot",
        "/var/log/netdeploy/certbot": root / "var/log/netdeploy/certbot",
        "/etc/systemd/system/netdeploy-certbot-renew": root / "etc/systemd/system/netdeploy-certbot-renew",
        "/run/systemd/system": root / "run/systemd/system",
    }
    for source, replacement in sorted(roots.items(), key=lambda pair:-len(pair[0])):
        script = script.replace(source, str(replacement))
    def run(fail=False):
        env = dict(os.environ, PATH=str(fake)+os.pathsep+os.environ.get("PATH",""),
                   MOCK_TOOLS=str(tools), MOCK_CALLS=str(log),
                   MOCK_FAIL_PIP="1" if fail else "0")
        return subprocess.run(["bash","-se"], input=script, text=True,
                              capture_output=True, env=env, timeout=20)

    initial = run(fail=True)
    assert initial.returncode == 31, (initial.stdout, initial.stderr)
    assert "ND_CERTBOT_PYPI_FAILED" in initial.stderr
    assert not (root / "opt/netdeploy-certbot/venv/bin/certbot").exists()
    assert not (root / "etc/netdeploy/letsencrypt/live").exists()

    retry = run()
    assert retry.returncode == 0, (retry.stdout, retry.stderr)
    assert "NETDEPLOY_CERTBOT_READY" in retry.stdout
    client = root / "opt/netdeploy-certbot/venv/bin/certbot"
    assert client.is_file()
    service=(root / "etc/systemd/system/netdeploy-certbot-renew.service").read_text()
    timer=(root / "etc/systemd/system/netdeploy-certbot-renew.timer").read_text()
    assert "--config-dir "+str(root / "etc/netdeploy/letsencrypt") in service
    assert "OnCalendar=*-*-* 00,04,08,12,16,20:15:00" in timer
    assert "Persistent=true" in timer
    assert "netdeploy-certbot-renew.service" in timer
    assert "/usr/bin/certbot" not in service
    count=log.read_text().count("pip ")
    second=run()
    assert second.returncode==0,second.stderr
    assert log.read_text().count("pip ")==count, "Healthy venv must not reinstall"
    assert subprocess.run([str(old)],capture_output=True,text=True).stdout.strip()=="certbot 4.0.0"


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                    reason="Linux shell syntax")
def test_all_generated_ip_and_domain_scripts_parse():
    for identity in ("8.8.8.8", "panel.example.com"):
        for group in (https_steps(identity,8443), sui_https_steps(identity)):
            for stage in group:
                result=subprocess.run(["bash","-n"],input=stage["script"],text=True,capture_output=True)
                assert result.returncode==0,(stage["label"],result.stderr)
    for script in (SUI_STATUS,SUI_ACCESS,https_access_script("8.8.8.8",8443)):
        result=subprocess.run(["bash","-n"],input=script,text=True,capture_output=True)
        assert result.returncode==0,result.stderr
