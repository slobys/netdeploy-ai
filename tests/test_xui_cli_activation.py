"""Reproduce the v3.11.0 x-ui wrapper/Go-binary split.

Official install.sh puts the interactive shell wrapper at /usr/bin/x-ui
and the Go binary at /usr/local/x-ui/x-ui. The wrapper does not implement
the "cert" or "setting" subcommands; it may print help and exit 0 instead.

All commands in this test are local fake programs. Never contact a VPS/CA.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.https_upgrade import https_steps


def test_pinned_3xui_cli_is_real_go_binary_not_menu_script():
    from app.catalog import build_plan
    facts = {"OS_ID": "ubuntu", "OS_VERSION": "26.10", "ARCH": "x86_64",
             "UID": "0", "FREE_KB": "2000000", "SYSTEMD": "yes",
             "SS_AVAILABLE": "yes", "XUI_PRESENT": "no",
             "DOCKER": "no", "COMPOSE": "no", "UDP_51820": "free"}
    fresh = build_plan("3x-ui", facts, {
        "panel_port": 8443, "tls_identity": "45.32.35.195", "access_mode": "https"
    })
    assert fresh["executable"]
    assert len(fresh["steps"]) == 9  # One approved install already includes TLS.
    for identity in ("45.32.35.195", "panel.example.com"):
        script = https_steps(identity, 8443)[3]["script"]
        assert 'panel_cli="/usr/local/x-ui/x-ui"' in script
        assert 'test -x "$panel_cli"' in script
        for required in (
            '"$panel_cli" cert -webCert "$cert" -webCertKey "$key"',
            '"$panel_cli" setting -getCert true',
            '"$panel_cli" setting -listenIP 0.0.0.0',
            '"$panel_cli" setting -getListen true',
            '"$panel_cli" setting -listenIP 127.0.0.1',
            '"$panel_cli" cert -reset',
        ):
            assert required in script
        assert not re.search(r"(?m)^\s*x-ui\s+(?:setting|cert)\b", script)
        assert script.index('panel_cli="/usr/local/x-ui/x-ui"') < script.index('"$panel_cli" cert -webCert')
        assert "trap restore_local_listener EXIT" in script


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                    reason="Simulates Linux SSH scripts in an isolated bash environment")
@pytest.mark.parametrize(("failure", "socket_addr", "curl_exit"), [
    (None, "0.0.0.0:24443", 0),
    (None, "*:24443", 0),
    (None, "[::]:24443", 0),
    (None, ":::24443", 0),
    ("readback", "0.0.0.0:24443", 0),
    ("prior", "0.0.0.0:24443", 0),
    ("local", "127.0.0.1:24443", 0),
    ("wrong_port", "*:24444", 0),
    ("ipv6_only", "[::]:24443", 7),
])
def test_real_cli_used_and_failed_cert_restores_original_settings(
        tmp_path, failure, socket_addr, curl_exit):
    fake_bin = tmp_path / "mockbin"
    fake_bin.mkdir()
    marker = tmp_path / "state"
    marker.mkdir()
    if failure == "prior":
        (marker / "cert").write_text("/etc/ssl/prior-chain.pem")
        (marker / "key").write_text("/etc/ssl/prior-key.pem")
    cert_dir = tmp_path / "cert"
    cert_dir.mkdir()
    (cert_dir / "fullchain.pem").write_text("dummy chain")
    (cert_dir / "privkey.pem").write_text("dummy key")
    install_file = tmp_path / "install-result.env"
    install_file.write_text("XUI_PANEL_PORT=24443\nXUI_WEB_BASE_PATH=SecretRoute123\n")

    # The *wrong* PATH executable mimics official /usr/bin/x-ui shell
    # manager, which prints help and returns success for unknown commands.
    fake_bin.joinpath("x-ui").write_text(
        "#!/bin/sh\n"
        "echo \"$*\" >> \"$FAKE_WRAPPER_CALLS\"\n"
        "echo 'x-ui management menu usage'\n"
        "exit 0\n",
    )

    # The *real* executable mimics /usr/local/x-ui/x-ui; result values are
    # deliberately shaped like the Go project's GetCertificate/GetListenIP.
    real_cli = tmp_path / "x-ui-real"
    real_cli.write_text(
        "#!/usr/bin/env python3\n"
        "import os,sys\n"
        "from pathlib import Path\n"
        "state=Path(os.environ['FAKE_XUI_STATE'])\n"
        "args=sys.argv[1:]\n"
        "with (state/'binary.log').open('a') as log: log.write(' '.join(args)+'\\n')\n"
        "cert=state/'cert'; key=state/'key'; listen=state/'listen'\n"
        "def val(k): return k.read_text() if k.exists() else ''\n"
        "if args[:2]==['setting','-getCert']:\n"
        "  if os.environ.get('FAKE_READBACK_FAILURE')=='yes' and (state/'new-written').exists():\n"
        "    print('cert: '); print('key: ')\n"
        "  else:\n"
        "    print('cert: '+val(cert));print('key: '+val(key))\n"
        "elif args[:2]==['setting','-getListen']:\n"
        "  print('listenIP: '+val(listen))\n"
        "elif args[:2]==['setting','-listenIP']:\n"
        "  listen.write_text(args[2])\n"
        "elif args and args[0]=='cert' and '-reset' in args:\n"
        "  cert.unlink(missing_ok=True);key.unlink(missing_ok=True)\n"
        "elif args and args[0]=='cert':\n"
        "  cert.write_text(args[args.index('-webCert')+1])\n"
        "  key.write_text(args[args.index('-webCertKey')+1])\n"        "  (state/'new-written').write_text('1')\n"

        "else:\n"
        "  sys.exit(9)\n"
    )

    # All other commands used by the activation stage are deterministic
    # fakes: no privileged files, systemd, ACME, UFW or outbound traffic.
    fake_commands = {
        "id": "#!/bin/sh\necho 0\n",
        "systemctl": "#!/bin/sh\ncase \"$1\" in\n"
                     "is-enabled) echo enabled ;;\n"
                     "is-active) case \"$2\" in --quiet) exit 0;; *) echo active;; esac ;;\n"
                     "restart) echo 'restart x-ui' >> \"$FAKE_SYSTEMD_CALLS\" ;;\n"
                     "*) exit 10;;\n"
                     "esac\n",
        "openssl": "#!/bin/sh\n"
                   "case \" $* \" in *' -checkip '*|*' -checkhost '*) echo 'does match';; esac\n",
        "ss": "#!/bin/sh\nprintf 'LISTEN 0 128 %s *:*\\n' \"$FAKE_SS_ADDRESS\"\n",
        "sleep": "#!/bin/sh\nexit 0\n",
        "curl": "#!/bin/sh\n"
                "echo \"$*\" >> \"$FAKE_CURL_CALLS\"\n"
                "if [ \"$FAKE_CURL_EXIT\" = 7 ]; then exit 7; fi\n"
                "echo 200\n",
        "ufw": "#!/bin/sh\n"
               "if [ \"$1\" = status ]; then echo 'Status: active'; "
               "elif [ \"$1\" = allow ]; then echo \"$*\" >> \"$FAKE_UFW_CALLS\"; fi\n",
    }
    for name, script in fake_commands.items():
        target = fake_bin / name
        target.write_text(script)
        target.chmod(0o755)
    (fake_bin / "x-ui").chmod(0o755)
    real_cli.chmod(0o755)

    script = https_steps("45.32.35.195", 24443)[3]["script"]
    script = script.replace('"/usr/local/x-ui/x-ui"', f'"{real_cli}"')
    script = script.replace('/etc/letsencrypt/live/45.32.35.195', str(cert_dir))
    script = script.replace('/etc/x-ui/install-result.env', str(install_file))
    env = os.environ.copy()
    env.update({
        "PATH": str(fake_bin) + os.pathsep + env.get("PATH", ""),
        "FAKE_XUI_STATE": str(marker),
        "FAKE_WRAPPER_CALLS": str(tmp_path / "wrong-wrapper.log"),
        "FAKE_SYSTEMD_CALLS": str(tmp_path / "systemd.log"),
        "FAKE_CURL_CALLS": str(tmp_path / "curl.log"),
        "FAKE_UFW_CALLS": str(tmp_path / "ufw.log"),
        "FAKE_READBACK_FAILURE": "yes" if failure in {"readback", "prior"} else "no",
        "FAKE_SS_ADDRESS": socket_addr,
        "FAKE_CURL_EXIT": str(curl_exit),
    })
    proc = subprocess.run(["bash", "-se"], input=script, text=True,
                          capture_output=True, timeout=20, env=env)
    assert not Path(env["FAKE_WRAPPER_CALLS"]).exists(), proc.stderr
    binary_calls = (marker / "binary.log").read_text()
    assert "cert -webCert" in binary_calls
    assert "setting -getCert true" in binary_calls
    if failure:
        expected = {"readback": (39, "XUI_CERT_SETTINGS_MISSING"),
                    "prior": (39, "XUI_CERT_SETTINGS_MISSING"),
                    "local": (37, "XUI_LISTENER_LOCAL_ONLY"),
                    "wrong_port": (37, "XUI_LISTENER_MISSING"),
                    "ipv6_only": (36, "XUI_LOCAL_TLS_CONNECT_FAILED")}
        code, diagnostic = expected[failure]
        assert proc.returncode == code, (proc.stdout, proc.stderr)
        assert diagnostic in proc.stderr, proc.stderr
        assert (marker / "listen").read_text() == "127.0.0.1"
        if failure == "prior":
            # Preserve pre-existing cert configuration when a retry fails.
            assert (marker / "cert").read_text() == "/etc/ssl/prior-chain.pem"
            assert (marker / "key").read_text() == "/etc/ssl/prior-key.pem"
        else:
            # First-time activation is reverted to localhost HTTP.
            assert not (marker / "cert").exists()
            assert not (marker / "key").exists()
        assert not Path(env["FAKE_UFW_CALLS"]).exists()
        assert "restart x-ui" in Path(env["FAKE_SYSTEMD_CALLS"]).read_text()
    else:
        assert proc.returncode == 0, proc.stderr
        assert "XUI_HTTPS_VERIFIED" in proc.stdout
        assert (marker / "listen").read_text() == "0.0.0.0"
        assert (marker / "cert").read_text() == str(cert_dir / "fullchain.pem")
        assert (marker / "key").read_text() == str(cert_dir / "privkey.pem")
        assert Path(env["FAKE_UFW_CALLS"]).read_text().strip().startswith("allow 24443/tcp")
        assert "--connect-to 45.32.35.195:24443:127.0.0.1:24443" in Path(env["FAKE_CURL_CALLS"]).read_text()
