"""Controlled S-UI v1.6.6 native HTTPS setup for local-only managed installs.

The release supports webCertFile, webKeyFile, webDomain and webListen. Public
Web TCP 2095 is enabled only after trusted certificate and renewal validation.
The subscription listener TCP 2096 must remain on 127.0.0.1 throughout.
"""
from __future__ import annotations

from .firewall import acme_ufw_script, allow_port_script
from .https_upgrade import https_steps as xui_https_steps, identify
from .listening import PUBLIC_SOCKET_CHECK
from .s_ui import HTTPS_STATUS_GUARD, LOCAL_LISTENER_GUARD, PORT


PRECHECK = r"""set -eu
__LOCAL_GUARD__
test "$(id -u)" = 0
test -d /run/systemd/system
test -x /usr/local/s-ui/sui
systemctl is-active --quiet s-ui
record='/var/lib/netdeploy/s-ui/install-result.env'
test -f "$record" && test ! -L "$record"
test "$(stat -c %a "$record")" = 600
test "$(stat -c %u "$record")" = 0
test "$(sed -n 's/^SUI_PANEL_PORT=//p' "$record")" = 2095
test "$(grep -c '^SUI_TLS_IDENTITY=' "$record")" = 0
sui_local_listeners_only || {
    echo 'SUI_LOCAL_ONLY_REQUIRED: HTTPS requires both ports localhost-only' >&2; exit 25;
}
if ss -Hltn 'sport = :80' | grep -q .; then
    echo 'SUI_ACME_PORT80_BUSY: TCP 80 occupied; standalone HTTP-01 unavailable' >&2
    exit 26
fi
test "$(df -Pk / | awk 'NR==2 {print $4}')" -ge 300000
command -v curl >/dev/null
command -v getent >/dev/null
public_ip="$(curl --proto '=https' --tlsv1.2 -4 -fsS --max-time 12 https://api.ipify.org)"
case "$public_ip" in ""|*[!0-9.]* ) echo 'SUI_PUBLIC_IP_UNKNOWN' >&2; exit 27;; esac
if [ -n "__SSH_IP__" ] && [ "$public_ip" != "__SSH_IP__" ]; then
    echo 'SUI_SSH_PUBLIC_IP_MISMATCH: VPS egress differs from pinned SSH IPv4' >&2
    exit 28
fi
if [ "__MODE__" = ip ]; then
    test "$public_ip" = "__IDENTITY__" || {
        echo 'SUI_IP_IDENTITY_MISMATCH: VPS public IPv4 differs from certificate IP' >&2; exit 28;
    }
else
    getent ahostsv4 "__IDENTITY__" | awk '{print $1}' | grep -Fxq "$public_ip" || {
        echo 'SUI_DOMAIN_DNS_MISMATCH: DNS A must match the VPS public IPv4' >&2; exit 29;
    }
fi
echo 'S-UI local listener and public certificate identity verified; preparing ACME TCP 80'
""" + acme_ufw_script()


ACTIVATE = r"""set -eu
__LOCAL_GUARD__
__HTTPS_GUARD__
test "$(id -u)" = 0
record='/var/lib/netdeploy/s-ui/install-result.env'
db='/usr/local/s-ui/db/s-ui.db'
cert='/etc/letsencrypt/live/__IDENTITY__/fullchain.pem'
key='/etc/letsencrypt/live/__IDENTITY__/privkey.pem'
test -f "$record" && test ! -L "$record"
test "$(stat -c %u "$record")" = 0 && test "$(stat -c %a "$record")" = 600
test -s "$db" && test -s "$cert" && test -s "$key"
systemctl is-active --quiet s-ui
sui_local_listeners_only
openssl x509 -in "$cert" -noout -checkend 86400 >/dev/null
openssl x509 -in "$cert" -noout -__CHECK__ '__IDENTITY__' | grep -Fq 'does match'
test "$(systemctl is-enabled certbot.timer)" = enabled
test "$(systemctl is-active certbot.timer)" = active
web_path="$(sed -n 's/^SUI_WEB_BASE_PATH=//p' "$record")"
printf '%s' "$web_path" | grep -Eq '^[a-f0-9]{24}$'

changed=no
restore_local() {
    # Stop FIRST to avoid serving HTTP publicly if SQLite restoration fails.
    systemctl stop s-ui >/dev/null 2>&1 || true
    if ! python3 - "$db" <<'PY'
import sqlite3, sys
db = sqlite3.connect(sys.argv[1], timeout=10)
try:
    db.execute("BEGIN IMMEDIATE")
    for k, v in (("webListen", "127.0.0.1"), ("webCertFile", ""),
                 ("webKeyFile", ""), ("webDomain", "")):
        rows = db.execute("SELECT id FROM settings WHERE key=?", (k,)).fetchall()
        if len(rows) != 1:
            raise RuntimeError("SUI_ROLLBACK_DB_INVALID: " + k)
        db.execute("UPDATE settings SET value=? WHERE id=?", (v, rows[0][0]))
    db.commit()
finally:
    db.close()
PY
    then
        echo 'SUI_ROLLBACK_DB_FAILED: service stopped to prevent public HTTP' >&2
        return 1
    fi
    # Remove TLS metadata only, preserving initial credentials and web path.
    if [ -f "$record" ]; then
        temp="$(mktemp /var/lib/netdeploy/s-ui/.rollback.XXXXXXXX)"
        grep -Ev '^SUI_TLS_(MODE|IDENTITY)=' "$record" > "$temp" || true
        chmod 600 "$temp"
        mv -f "$temp" "$record"
    fi
    if ! systemctl start s-ui >/dev/null 2>&1; then
        echo 'SUI_ROLLBACK_START_FAILED: no public listener enabled' >&2
        return 1
    fi
    if ! sui_local_listeners_only; then
        systemctl stop s-ui >/dev/null 2>&1 || true
        echo 'SUI_ROLLBACK_LISTENER_INVALID: service stopped for safety' >&2
        return 1
    fi
}
trap 'if [ "$changed" = yes ]; then restore_local || true; fi' EXIT

# One transaction ensures certificate+key and public bind are never half-set.
# Existing settings must be exactly the managed localhost defaults.
changed=yes
python3 - "$db" "$web_path" "$cert" "$key" <<'PY'
import sqlite3, sys
db_path, path, cert, key = sys.argv[1:]
conn = sqlite3.connect(db_path, timeout=10)
try:
    conn.execute("BEGIN IMMEDIATE")
    required = {"webListen": "127.0.0.1", "webCertFile": "", "webKeyFile": "",
                "webDomain": "", "webPort": "2095", "subListen": "127.0.0.1",
                "subPort": "2096", "webPath": "/" + path + "/"}
    for item, expected in required.items():
        rows = conn.execute("SELECT id,value FROM settings WHERE key=?", (item,)).fetchall()
        if len(rows) != 1 or rows[0][1] != expected:
            raise RuntimeError("SUI_HTTPS_PREVIOUS_SETTINGS_CHANGED: " + item)
    for item, value in (("webCertFile", cert), ("webKeyFile", key),
                        ("webDomain", "__WEB_DOMAIN__"), ("webListen", "0.0.0.0")):
        conn.execute("UPDATE settings SET value=? WHERE key=?", (value, item))
    conn.commit()
finally:
    conn.close()
PY
systemctl restart s-ui

# Go may represent a wildcard socket as *:2095 or [::]:2095.
# TLS validation uses a real IPv4 handshake with an identity-checked cert.
ready=no
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
    if systemctl is-active --quiet s-ui &&
       netdeploy_public_socket 2095 &&
       test "$(ss -Hltn 'sport = :2096' | awk '{print $4}')" = '127.0.0.1:2096'; then
        code="$(curl -4 --noproxy '*' --proto '=https' --tlsv1.2 --silent \
            --output /dev/null --write-out '%{http_code}' --max-time 8 \
            --connect-to '__IDENTITY__:2095:127.0.0.1:2095' \
            'https://__IDENTITY__:2095/'"$web_path"'/' 2>/dev/null)" || code=000
        case "$code" in 200|301|302|303|307|308|401|403) ready=yes; break ;; esac
    fi
    sleep 1
done
if [ "$ready" != yes ]; then
    echo 'SUI_HTTPS_VERIFY_FAILED: HTTPS identity/IPv4 not verified; rolling back' >&2
    exit 36
fi

# Open only the reviewed management port in local UFW, not subscription 2096.
""" + allow_port_script(PORT, "tcp") + r"""
# Record HTTPS identity atomically only after successful TLS/UFW validation.
temp="$(mktemp /var/lib/netdeploy/s-ui/.result.XXXXXXXX)"
cp "$record" "$temp"
{
    printf 'SUI_TLS_MODE=%s\n' '__MODE__'
    printf 'SUI_TLS_IDENTITY=%s\n' '__IDENTITY__'
} >> "$temp"
chmod 600 "$temp"
mv -f "$temp" "$record"
sui_https_verified || {
    echo 'SUI_HTTPS_RECHECK_FAILED: certificate check failed after activation' >&2; exit 37;
}
changed=no
trap - EXIT
echo 'SUI_HTTPS_VERIFIED: public HTTPS active on TCP 2095; subscription remains local'
echo 'Cloud security group must separately allow TCP 2095 from your management IP'
"""


def https_steps(identity: str, ssh_ipv4: str | None = None) -> list[dict]:
    """Build four immutable HTTPS stages, sharing tested 3X-UI ACME logic."""
    mode, identity = identify(identity)
    if ssh_ipv4 is not None:
        if mode != "domain" or identify(ssh_ipv4)[0] != "ip":
            raise ValueError("S-UI SSH IPv4 binding requires a domain certificate")
        _, ssh_ipv4 = identify(ssh_ipv4)
    core = xui_https_steps(identity, PORT, ssh_ipv4)
    dep = dict(core[1])
    issuer = dict(core[2])
    old = """cat > /etc/letsencrypt/renewal-hooks/deploy/netdeploy-xui-reload.sh <<'RENEW_HOOK'
#!/bin/sh
set -eu
systemctl try-restart x-ui >/dev/null
RENEW_HOOK"""
    new = """cat > /etc/letsencrypt/renewal-hooks/deploy/netdeploy-sui-reload.sh <<'RENEW_HOOK'
#!/bin/sh
set -eu
# Restart only when this managed S-UI certificate was renewed.
if [ "${RENEWED_LINEAGE:-}" = '/etc/letsencrypt/live/""" + identity + """' ]; then
    systemctl try-restart s-ui >/dev/null
fi
RENEW_HOOK"""
    script = issuer["script"]
    if script.count(old) != 1 or script.count("netdeploy-xui-reload.sh") != 2:
        raise RuntimeError("Certbot template changed: review S-UI renewal integration")
    script = script.replace(old, new)
    script = script.replace("netdeploy-xui-reload.sh", "netdeploy-sui-reload.sh")
    script = script.replace("existing 3X-UI localhost listener", "existing S-UI localhost listener")
    issuer["script"] = script
    values = {
        "__IDENTITY__": identity, "__MODE__": mode,
        "__SSH_IP__": ssh_ipv4 or "",
        "__CHECK__": "checkip" if mode == "ip" else "checkhost",
        "__WEB_DOMAIN__": identity if mode == "domain" else "",
        "__LOCAL_GUARD__": LOCAL_LISTENER_GUARD,
        "__HTTPS_GUARD__": HTTPS_STATUS_GUARD,
    }
    result = []
    for label, script, timeout in (
        ("检查 S-UI 本机监听、公网 IP/域名及 TCP 80", PRECHECK, 55),
        (dep["label"], dep["script"], dep["timeout"]),
        ("申请可信 IP/域名证书并配置 S-UI 自动续期", issuer["script"], issuer["timeout"]),
        ("启用 S-UI HTTPS、验收后开放管理端口（失败回退）", ACTIVATE, 120),
    ):
        for token, value in values.items():
            script = script.replace(token, value)
        result.append({"label": label, "script": script, "timeout": timeout})
    return result
