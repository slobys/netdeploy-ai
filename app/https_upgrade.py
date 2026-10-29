"""Controlled 3X-UI public HTTPS upgrade for existing or newly installed panels.

Port 80 is for Let's Encrypt HTTP-01. The panel remains on localhost until
a trusted cert is issued, checked and renewal configured. Certbot must support
short-lived IP certificates; no public HTTP fallback is permitted.
"""
from __future__ import annotations

import ipaddress
import re

from .three_x_ui import validate_port
from .firewall import acme_ufw_script, allow_port_script
from .listening import PUBLIC_SOCKET_CHECK

SAFE_DNS = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def identify(hostname: str) -> tuple[str, str]:
    if not isinstance(hostname, str):
        raise ValueError("证书标识必须是有效的公网 IPv4 或域名")
    hostname = hostname.strip().lower().rstrip(".")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if not SAFE_DNS.fullmatch(hostname) or hostname.endswith(".local") or hostname.endswith(".internal"):
            raise ValueError("HTTPS 证书必须使用有效的公网 IPv4 或可解析的公网域名")
        return "domain", hostname
    if address.version != 4 or not address.is_global:
        raise ValueError("IP 证书仅支持公网 IPv4 地址；不能为内网/保留地址签发")
    return "ip", str(address)


def https_steps(identity: str, port: int) -> list[dict]:
    mode, identity = identify(identity)
    validate_port(port)
    preflight = r"""set -eu
test "$(id -u)" = 0
test -x /usr/local/x-ui/x-ui || {
    echo 'XUI_CLI_MISSING: official 3X-UI program not found'; exit 40;
}
test -d /run/systemd/system
systemctl is-active --quiet x-ui
test -r /etc/x-ui/install-result.env
test "$(sed -n 's/^XUI_PANEL_PORT=//p' /etc/x-ui/install-result.env)" = "__PORT__"
test "$(stat -c %a /etc/x-ui/install-result.env)" = 600
addresses="$(ss -Hltn 'sport = :__PORT__' | awk '{print $4}')"
test "$addresses" = "127.0.0.1:__PORT__" || {
    echo '3X-UI must be localhost-only before HTTPS conversion'; exit 25;
}
if ss -Hltn 'sport = :80' | grep -q .; then
    echo 'TCP 80 is occupied; standalone ACME challenge cannot run'; exit 26;
fi
test "$(df -Pk / | awk 'NR==2 {print $4}')" -ge 300000
command -v curl >/dev/null
command -v getent >/dev/null
# Validate the requested hostname points to the actual public IPv4 egress.
public_ip="$(curl --proto '=https' --tlsv1.2 -4 -fsS --max-time 12 https://api.ipify.org)"
case "$public_ip" in ""|*[!0-9.]* ) echo 'Could not identify public IPv4'; exit 27;; esac
if [ "__MODE__" = "ip" ]; then
    test "$public_ip" = "__IDENTITY__" || {
        echo 'VPS public egress IP differs from certificate IP; abort'; exit 28;
    }
else
    getent ahostsv4 "__IDENTITY__" | awk '{print $1}' | grep -Fxq "$public_ip" || {
        echo 'Domain A record does not match VPS public IPv4; configure DNS before retry'; exit 29;
    }
fi
echo 'Public identity and local-only panel preflight passed; preparing local UFW for TCP 80'
""" + acme_ufw_script() + "\n"
    install = r"""set -eu
export DEBIAN_FRONTEND=noninteractive
if command -v certbot >/dev/null 2>&1 && command -v openssl >/dev/null 2>&1 && command -v curl >/dev/null 2>&1; then
    echo 'Certbot, OpenSSL and curl already available; skipping APT'
else
    # Do not delete /var/lib/dpkg/lock-frontend or terminate unattended-upgrades.
    # Let APT wait for the valid lock holder before installing.
    apt-get -o DPkg::Lock::Timeout=240 update -q
    apt-get -o DPkg::Lock::Timeout=240 install -y -q certbot openssl ca-certificates curl
fi
command -v certbot >/dev/null
if [ "__MODE__" = "ip" ]; then
    certbot --help all | grep -Fq -- '--ip-address' || {
        echo 'Installed Certbot does not support IP certificates (requires recent Certbot 5.3+)'; exit 31;
    }
    certbot --help all | grep -Fq -- '--preferred-profile' || {
        echo 'Certbot does not support the mandatory shortlived profile'; exit 32;
    }
fi
systemctl list-unit-files --no-legend certbot.timer | grep -q '^certbot[.]timer' || {
    echo 'Missing certbot.timer, refuse public HTTPS without renewal'; exit 33;
}
echo 'Certbot and renewal timer available'
"""
    issue_cmd = (r"""certbot certonly --non-interactive --agree-tos --register-unsafely-without-email \
    --standalone --preferred-challenges http --http-01-port 80 --cert-name "__IDENTITY__" \
    --preferred-profile shortlived --ip-address "__IDENTITY__" """
                 if mode == "ip" else
                 r"""certbot certonly --non-interactive --agree-tos --register-unsafely-without-email \
    --standalone --preferred-challenges http --http-01-port 80 --cert-name "__IDENTITY__" \
    -d "__IDENTITY__" """)
    issue = r"""set -eu
umask 077
cert_log="$(mktemp /tmp/netdeploy-certbot.XXXXXXXX)"
trap 'rm -f "$cert_log"' EXIT

# Never dump Certbot's untrusted raw output into the application or AI logs.
# Match known error types and show only fixed, actionable diagnostic messages.
explain_certbot_failure() {
    if grep -Eiq 'Timeout during connect|Connection refused|Connection timed out|Failed to connect to|connection reset by peer|network is unreachable' "$cert_log"; then
        echo 'LE_HTTP01_UNREACHABLE: Let’s Encrypt cannot reach this VPS on public TCP 80. Check cloud security group, system firewall and inbound routing (local free port is not sufficient).' >&2
    elif grep -Eiq 'Problem binding to port 80|Could not bind TCP port 80|Address already in use|Unable to bind|could not bind' "$cert_log"; then
        echo 'LE_PORT80_BUSY: Certbot cannot listen on TCP 80; check competing web services or firewalls, then retry after resolving.' >&2
    elif grep -Eiq 'Invalid response from|Incorrect response|unauthorized|Some challenges have failed|Challenge validation has failed' "$cert_log"; then
        echo 'LE_HTTP01_CHALLENGE_FAILED: HTTP-01 validation returned an unexpected response. Verify domain DNS A, proxies/CDN, and inbound TCP 80 to this VPS.' >&2
    elif grep -Eiq 'rate limit|too many certificates|too many failed authorizations|rateLimited' "$cert_log"; then
        echo 'LE_RATE_LIMIT: Let’s Encrypt rate limit was triggered. Do not retry repeatedly; wait for the CA retry window.' >&2
    elif grep -Eiq 'Profile.*(does not|not permitted|unsupported)|shortlived.*(not found|not available)|profile.*(unrecognized|unavailable)' "$cert_log"; then
        echo 'LE_PROFILE_UNSUPPORTED: The certificate authority rejected the required short-lived IP certificate profile.' >&2
    elif grep -Eiq 'unrecognized arguments|no such option|no such command|invalid option|not a valid.*argument' "$cert_log"; then
        echo 'CERTBOT_ARGS_INVALID: Certbot rejected a command flag. Check the installed Certbot version and supported options.' >&2
    elif grep -Eiq 'Unable to register|register an account|account.*(error|invalid)|ACME server.*error' "$cert_log"; then
        echo 'LE_ACCOUNT_ERROR: ACME account or certificate authority operation failed. Check outbound HTTPS and CA account status.' >&2
    elif grep -Eiq 'DNS problem|no valid A records|NXDOMAIN|SERVFAIL' "$cert_log"; then
        echo 'LE_DNS_ERROR: DNS resolution failed. Confirm the domain A record points to this VPS public IPv4.' >&2
    else
        echo 'LE_UNCLASSIFIED: Certbot failed for an undetermined reason. Review /var/log/letsencrypt/letsencrypt.log on VPS, redact sensitive data before sharing.' >&2
    fi
    echo 'Certificate was not activated; existing 3X-UI localhost listener was not opened to public HTTP.' >&2
}

# If a valid certificate with the correct identity is already present, do
# not request another one. This avoids needless CA rate-limit consumption.
reuse_certificate=no
existing_cert="/etc/letsencrypt/live/__IDENTITY__/fullchain.pem"
if test -s "$existing_cert" &&
   openssl x509 -in "$existing_cert" -noout -checkend 86400 >/dev/null 2>&1 &&
   openssl x509 -in "$existing_cert" -noout -__CHECK__ "__IDENTITY__" 2>/dev/null | grep -Fq 'does match'; then
    reuse_certificate=yes
    echo 'Existing valid certificate found for the selected IP/domain; skipping a new ACME request'
fi
if [ "$reuse_certificate" = no ]; then
    if ! __ISSUE_CMD__ >"$cert_log" 2>&1; then
        explain_certbot_failure
        exit 34
    fi
fi
test -s "/etc/letsencrypt/live/__IDENTITY__/fullchain.pem"
test -s "/etc/letsencrypt/live/__IDENTITY__/privkey.pem"
openssl x509 -in "/etc/letsencrypt/live/__IDENTITY__/fullchain.pem" -noout -checkend 86400
openssl x509 -in "/etc/letsencrypt/live/__IDENTITY__/fullchain.pem" -noout -__CHECK__ "__IDENTITY__" | grep -Fq 'does match'
# Renewal should be provided by the OS timer, not a foreground process.
systemctl enable --now certbot.timer >/dev/null
test "$(systemctl is-enabled certbot.timer)" = enabled
install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/netdeploy-xui-reload.sh <<'RENEW_HOOK'
#!/bin/sh
set -eu
systemctl try-restart x-ui >/dev/null
RENEW_HOOK
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/netdeploy-xui-reload.sh
echo 'Trusted certificate issued, identity checked, automatic renewal configured'
"""
    activate = r"""set -eu
# Any error after changing the listener must revert it, including a failed
# service restart or an unexpected certificate-validation failure.
# /usr/bin/x-ui is the interactive shell manager. It DOES NOT forward
# "cert" or "setting" commands. 3X-UI v3.11.0 installs the actual Go CLI
# at this pinned, verified upstream binary path.
panel_cli="/usr/local/x-ui/x-ui"
test -x "$panel_cli" || {
    echo 'XUI_CLI_MISSING: official 3X-UI program unavailable; no HTTPS settings were changed.' >&2
    exit 40
}
changes_started=no
original_cert=""
original_key=""
restore_local_listener() {
    if [ "$changes_started" = yes ]; then
        "$panel_cli" setting -listenIP 127.0.0.1 >/dev/null 2>&1 || true
        if [ -n "$original_cert" ] && [ -n "$original_key" ]; then
            "$panel_cli" cert -webCert "$original_cert" -webCertKey "$original_key" >/dev/null 2>&1 || true
        else
            "$panel_cli" cert -reset >/dev/null 2>&1 || true
        fi
        systemctl restart x-ui >/dev/null 2>&1 || true
    fi
}
trap restore_local_listener EXIT
cert="/etc/letsencrypt/live/__IDENTITY__/fullchain.pem"
key="/etc/letsencrypt/live/__IDENTITY__/privkey.pem"
test -s "$cert" && test -s "$key"
openssl x509 -in "$cert" -noout -checkend 86400 >/dev/null
openssl x509 -in "$cert" -noout -__CHECK__ "__IDENTITY__" | grep -Fq 'does match'
test "$(systemctl is-enabled certbot.timer)" = enabled
test "$(systemctl is-active certbot.timer)" = active
# Capture the prior settings for rollback. Flag readback uses the direct Go
# binary, not the /usr/bin/x-ui menu wrapper.
previous_cert_settings="$("$panel_cli" setting -getCert true 2>/dev/null || true)"
original_cert="$(printf '%s\n' "$previous_cert_settings" | sed -n 's/^cert: //p' | head -n 1)"
original_key="$(printf '%s\n' "$previous_cert_settings" | sed -n 's/^key: //p' | head -n 1)"
if [ -n "$original_cert" ] || [ -n "$original_key" ]; then
    if [ -z "$original_cert" ] || [ -z "$original_key" ] ||
       ! printf '%s\n' "$original_cert" | grep -Eq '^/[A-Za-z0-9._+/-]+$' ||
       ! printf '%s\n' "$original_key" | grep -Eq '^/[A-Za-z0-9._+/-]+$'; then
        echo 'XUI_PREVIOUS_CERT_UNSAFE: unable to restore prior certificate settings safely; no changes applied.' >&2
        exit 41
    fi
fi
# Never trust the CLI exit status alone: Go setters sometimes log failures
# but return exit code 0. Only explicitly selected settings are read back.
changes_started=yes
"$panel_cli" cert -webCert "$cert" -webCertKey "$key" >/dev/null
cert_settings="$("$panel_cli" setting -getCert true 2>/dev/null || true)"
printf '%s\n' "$cert_settings" | grep -Fxq "cert: $cert" || {
    echo 'XUI_CERT_SETTINGS_MISSING: x-ui did not persist the configured certificate path; no public listener was opened.' >&2
    exit 39
}
printf '%s\n' "$cert_settings" | grep -Fxq "key: $key" || {
    echo 'XUI_KEY_SETTINGS_MISSING: x-ui did not persist the private key path; no public listener was opened.' >&2
    exit 39
}
"$panel_cli" setting -listenIP 0.0.0.0 >/dev/null
listen_settings="$("$panel_cli" setting -getListen true 2>/dev/null || true)"
printf '%s\n' "$listen_settings" | grep -Fxq 'listenIP: 0.0.0.0' || {
    echo 'XUI_LISTENER_SETTINGS_MISSING: x-ui did not persist its public listen IP; reverting to localhost.' >&2
    exit 39
}
systemctl restart x-ui
# Go net.Listen("tcp", "0.0.0.0:PORT") can produce an IPv6
# dual-stack socket shown by ss as *:PORT / [::]:PORT. These are wildcard
# candidates, but we still require a *real IPv4 TLS curl probe* below.
__PUBLIC_SOCKET_CHECK__
listener_ready=no
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
    if systemctl is-active --quiet x-ui && netdeploy_public_socket __PORT__; then
        listener_ready=yes
        break
    fi
    sleep 1
done
if [ "$listener_ready" != yes ]; then
    if ! systemctl is-active --quiet x-ui; then
        echo 'XUI_SERVICE_FAILED: x-ui exited after HTTPS configuration. Check systemctl status x-ui and journalctl -u x-ui (do not paste secrets).' >&2
    elif ss -Hltn 'sport = :__PORT__' | awk '{print $4}' | grep -Fxq '127.0.0.1:__PORT__'; then
        echo 'XUI_LISTENER_LOCAL_ONLY: x-ui is still bound to localhost after the HTTPS switch. Review x-ui getListen setting and any XUI_PORT override.' >&2
    else
        echo 'XUI_LISTENER_MISSING: x-ui active but no public wildcard listener on TCP __PORT__ (0.0.0.0, * or [::]). Check actual panel port and runtime overrides.' >&2
    fi
    exit 37
fi
# Connect explicitly to loopback, while keeping the original IP/domain URL
# for TLS certificate identity verification. Never use -k/--insecure.
web_path="$(sed -n 's/^XUI_WEB_BASE_PATH=//p' /etc/x-ui/install-result.env)"
printf '%s' "$web_path" | grep -Eq '^[A-Za-z0-9_-]{4,80}$' || {
    echo 'XUI_WEB_PATH_INVALID: cannot verify panel without a valid web path' >&2; exit 38;
}
tls_ready=no
last_curl_exit=0
last_http_code=000
for attempt in 1 2 3 4 5 6; do
    last_http_code="$(curl --noproxy '*' --proto '=https' --tlsv1.2 \
        --silent --output /dev/null --write-out '%{http_code}' --connect-timeout 3 --max-time 7 \
        --connect-to '__IDENTITY__:__PORT__:127.0.0.1:__PORT__' \
        "https://__IDENTITY__:__PORT__/$web_path" 2>/dev/null)" && last_curl_exit=0 || last_curl_exit=$?
    case "$last_curl_exit:$last_http_code" in
        0:200|0:301|0:302|0:303|0:307|0:308|0:401|0:403)
            tls_ready=yes; break ;;
    esac
    sleep 1
done
if [ "$tls_ready" != yes ]; then
    case "$last_curl_exit" in
        60|51|58|59) echo 'XUI_TLS_IDENTITY_FAILED: HTTPS certificate chain or public IP/domain identity could not be verified. Panel returned to localhost.' >&2 ;;
        7|28) echo 'XUI_LOCAL_TLS_CONNECT_FAILED: local HTTPS handshake could not connect before timeout despite an earlier listener check. Panel returned to localhost.' >&2 ;;
        *) echo 'XUI_HTTPS_HEALTH_FAILED: HTTPS endpoint did not respond with a valid panel status, or TLS negotiation failed. Check x-ui settings and journalctl -u x-ui.' >&2 ;;
    esac
    exit 36
fi
echo 'XUI_HTTPS_VERIFIED: trusted TLS and local listener passed for the selected address and panel port'
echo 'HTTPS certificate verified; enabling only the approved local UFW panel port'
""" + allow_port_script(port, "tcp") + """
changes_started=no
trap - EXIT
echo 'Public HTTPS is active; cloud security group must separately permit the selected TCP port'
"""
    label = "检查公网 IP 和 ACME 80 端口" if mode == "ip" else "检查域名解析和 ACME 80 端口"
    stages = [(label, preflight, 35),
              ("检查 Certbot / 自动等待 Ubuntu APT 锁", install, 540),
              ("申请证书、验证标识并配置自动续期", issue, 300),
              ("验证后开启 HTTPS 直连（失败回退本机监听）", activate, 60)]
    # Expand nested placeholders inside the installer command, too.
    values = {"__ISSUE_CMD__": issue_cmd.strip(), "__MODE__": mode,
              "__IDENTITY__": identity, "__PORT__": str(port),
              "__PUBLIC_SOCKET_CHECK__": PUBLIC_SOCKET_CHECK,
              "__CHECK__": "checkip" if mode == "ip" else "checkhost"}
    result = []
    for label, script, timeout in stages:
        for key, value in values.items():
            script = script.replace(key, value)
        result.append({"label": label, "script": script, "timeout": timeout})
    return result


def https_access_script(identity: str, port: int) -> str:
    """Read credentials only when HTTPS certificate and renewal remain healthy."""
    mode, identity = identify(identity)
    validate_port(port)
    script = r"""set -eu
test "$(id -u)" = 0
systemctl is-active --quiet x-ui
test "$(systemctl is-active certbot.timer)" = active
test -r /etc/x-ui/install-result.env
test "$(stat -c %a /etc/x-ui/install-result.env)" = 600
test "$(sed -n 's/^XUI_PANEL_PORT=//p' /etc/x-ui/install-result.env)" = "__PORT__"
__PUBLIC_SOCKET_CHECK__
netdeploy_public_socket __PORT__ || {
    echo 'XUI_HTTPS_LISTENER_NOT_PUBLIC: no verified wildcard socket on panel TCP __PORT__' >&2; exit 37;
}
cert="/etc/letsencrypt/live/__IDENTITY__/fullchain.pem"
test -s "$cert"
openssl x509 -in "$cert" -noout -checkend 86400 >/dev/null
openssl x509 -in "$cert" -noout -__CHECK__ "__IDENTITY__" | grep -Fq 'does match'
web_path="$(sed -n 's/^XUI_WEB_BASE_PATH=//p' /etc/x-ui/install-result.env)"
printf '%s' "$web_path" | grep -Eq '^[A-Za-z0-9_-]{4,80}$'
http_code="$(curl --noproxy '*' --proto '=https' --tlsv1.2 --silent \
    --output /dev/null --write-out '%{http_code}' --max-time 8 \
    --connect-to '__IDENTITY__:__PORT__:127.0.0.1:__PORT__' \
    "https://__IDENTITY__:__PORT__/$web_path")"
case "$http_code" in 200|301|302|303|307|308|401|403) ;; *) exit 38 ;; esac
grep -E '^XUI_(USERNAME|PASSWORD|PANEL_PORT|WEB_BASE_PATH)=' /etc/x-ui/install-result.env
"""
    for key, value in {"__PORT__": str(port), "__IDENTITY__": identity,
                       "__PUBLIC_SOCKET_CHECK__": PUBLIC_SOCKET_CHECK,
                       "__CHECK__": "checkip" if mode == "ip" else "checkhost"}.items():
        script = script.replace(key, value)
    return script


def https_url(identity: str, port: int, web_path: str) -> str:
    _, identity = identify(identity)
    validate_port(port)
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,80}", web_path):
        raise ValueError("无效的 Web 路径")
    return f"https://{identity}:{port}/{web_path}"
