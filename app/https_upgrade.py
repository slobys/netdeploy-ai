"""Controlled 3X-UI public HTTPS upgrade for existing or newly installed panels.

Port 80 is for Let's Encrypt HTTP-01. The panel remains on localhost until
a trusted cert is issued, checked and renewal configured. Certbot must support
short-lived IP certificates; no public HTTP fallback is permitted.
"""
from __future__ import annotations

import ipaddress
import re

from .three_x_ui import validate_port

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
command -v x-ui >/dev/null
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
echo 'Public identity and local-only panel preflight passed; TCP 80 must also be reachable from Internet'
"""
    install = r"""set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q certbot openssl ca-certificates curl
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
if ! __ISSUE_CMD__ >"$cert_log" 2>&1; then
    echo 'Let’s Encrypt issuance failed. Check public TCP 80, domain A record, CA rate limits, or Certbot version. Panel remains localhost-only.' >&2
    exit 34
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
public_listener_enabled=no
restore_local_listener() {
    if [ "$public_listener_enabled" = yes ]; then
        x-ui setting -listenIP 127.0.0.1 >/dev/null 2>&1 || true
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
# Keep the panel private until the certificate has been configured.
x-ui cert -webCert "$cert" -webCertKey "$key" >/dev/null
public_listener_enabled=yes
x-ui setting -listenIP 0.0.0.0 >/dev/null
systemctl restart x-ui
# TLS must validate against the CA chain and the requested identity.
if ! curl --noproxy '*' --silent --show-error --output /dev/null --max-time 10 \
    --resolve '__IDENTITY__:__PORT__:127.0.0.1' \
    'https://__IDENTITY__:__PORT__/' ; then
    echo 'HTTPS verification failed; reverting to localhost-only listener' >&2
    exit 36
fi
addresses="$(ss -Hltn 'sport = :__PORT__' | awk '{print $4}')"
if ! printf '%s\n' "$addresses" | grep -Fxq '0.0.0.0:__PORT__'; then
    echo 'HTTPS listener is not reachable on IPv4; reverting to localhost-only listener' >&2
    exit 37
fi
public_listener_enabled=no
trap - EXIT
echo 'HTTPS active with a trusted certificate; public TCP __PORT__ must be allowed by the cloud firewall'
"""
    stages = [("HTTPS 前置检查、DNS 与 ACME 80 端口", preflight, 35),
              ("安装 Certbot 并检查 IP 短期证书支持及续期定时器", install, 300),
              ("申请证书、验证标识并配置自动续期", issue, 300),
              ("验证后开启 HTTPS 直连（失败回退本机监听）", activate, 60)]
    # Expand nested placeholders inside the installer command, too.
    values = {"__ISSUE_CMD__": issue_cmd.strip(), "__MODE__": mode,
              "__IDENTITY__": identity, "__PORT__": str(port),
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
addresses="$(ss -Hltn 'sport = :__PORT__' | awk '{print $4}')"
printf '%s\n' "$addresses" | grep -Fxq '0.0.0.0:__PORT__'
cert="/etc/letsencrypt/live/__IDENTITY__/fullchain.pem"
test -s "$cert"
openssl x509 -in "$cert" -noout -checkend 86400 >/dev/null
openssl x509 -in "$cert" -noout -__CHECK__ "__IDENTITY__" | grep -Fq 'does match'
curl --noproxy '*' --silent --show-error --output /dev/null --max-time 8 \
    --resolve '__IDENTITY__:__PORT__:127.0.0.1' \
    'https://__IDENTITY__:__PORT__/'
grep -E '^XUI_(USERNAME|PASSWORD|PANEL_PORT|WEB_BASE_PATH)=' /etc/x-ui/install-result.env
"""
    for key, value in {"__PORT__": str(port), "__IDENTITY__": identity,
                       "__CHECK__": "checkip" if mode == "ip" else "checkhost"}.items():
        script = script.replace(key, value)
    return script


def https_url(identity: str, port: int, web_path: str) -> str:
    _, identity = identify(identity)
    validate_port(port)
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,80}", web_path):
        raise ValueError("无效的 Web 路径")
    return f"https://{identity}:{port}/{web_path}"
