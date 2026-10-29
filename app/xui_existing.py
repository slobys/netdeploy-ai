"""Read-only detection and explicit login-info retrieval for an existing 3X-UI.

Existing installation presence must never create a zero-step deployment plan or
be treated as permission to reinstall. SSH remains pinned to known_hosts.
Only root-owned mode-0600 install-result.env files may supply credentials.
"""
from __future__ import annotations

import re
from .three_x_ui import validate_port
from .https_upgrade import identify, https_url


def _public_identity(hostname: str) -> str | None:
    try:
        return identify(hostname)[1]
    except ValueError:
        return None


STATUS_TEMPLATE = r"""set -eu
test "$(id -u)" = 0
if ! test -d /etc/x-ui && ! test -d /usr/local/x-ui &&
   ! command -v x-ui >/dev/null 2>&1 &&
   ! systemctl list-unit-files --no-legend x-ui.service 2>/dev/null | grep -q '^x-ui[.]service'; then
    echo 'XUI_EXISTS=no'
    exit 0
fi
echo 'XUI_EXISTS=yes'
if systemctl is-active --quiet x-ui; then
    echo 'XUI_SERVICE=active'
else
    echo 'XUI_SERVICE=inactive'
fi
# Presence alone does not establish a safe/readable credentials source.
if ! test -f /etc/x-ui/install-result.env ||
   test -L /etc/x-ui/install-result.env ||
   test "$(stat -c %a /etc/x-ui/install-result.env 2>/dev/null)" != 600 ||
   test "$(stat -c %u /etc/x-ui/install-result.env 2>/dev/null)" != 0; then
    echo 'XUI_MANAGED=no'
    exit 0
fi
port="$(sed -n 's/^XUI_PANEL_PORT=//p' /etc/x-ui/install-result.env)"
web_path="$(sed -n 's/^XUI_WEB_BASE_PATH=//p' /etc/x-ui/install-result.env)"
case "$port" in ''|*[!0-9]*) echo 'XUI_MANAGED=no'; exit 0 ;; esac
if ! test "$port" -ge 1 || ! test "$port" -le 65535; then
    echo 'XUI_MANAGED=no'
    exit 0
fi
if ! printf '%s' "$web_path" | grep -Eq '^[A-Za-z0-9_-]{4,80}$'; then
    echo 'XUI_MANAGED=no'
    exit 0
fi
# Never print the saved password, username, token or secret web path in status.
echo 'XUI_MANAGED=yes'
printf 'XUI_PORT=%s\n' "$port"
addresses="$(ss -Hltn "sport = :$port" | awk '{print $4}')"
if test "$addresses" = "127.0.0.1:$port"; then
    echo 'XUI_LISTENER=local'
elif test "$addresses" = "0.0.0.0:$port"; then
    # A public listener is safe to open only when the existing TLS identity
    # validates against the actual hostname with the OS trust store.
    if test -n '__IDENTITY__'; then
        code="$(curl --noproxy '*' --proto '=https' --tlsv1.2 --silent \
          --output /dev/null --write-out '%{http_code}' --max-time 7 \
          --connect-to '__IDENTITY__:'"$port"':127.0.0.1:'"$port" \
          'https://__IDENTITY__:'"$port"'/'"$web_path" 2>/dev/null || true)"
        case "$code" in
          200|301|302|303|307|308|401|403)
            echo 'XUI_LISTENER=https'
            exit 0
            ;;
        esac
    fi
    echo 'XUI_LISTENER=public_unverified'
else
    echo 'XUI_LISTENER=unknown'
fi
"""


def status_script(hostname: str) -> str:
    """Hostname is never sent into a command unless independently validated."""
    identity = _public_identity(hostname)
    return STATUS_TEMPLATE.replace("__IDENTITY__", identity or "")


def parse_status(raw: str) -> dict:
    accepted = {"XUI_EXISTS", "XUI_SERVICE", "XUI_MANAGED", "XUI_PORT", "XUI_LISTENER"}
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" not in line:
            raise ValueError("3X-UI 只读检查输出格式不正确")
        key, value = line.split("=", 1)
        if key not in accepted or key in values or len(value) > 100:
            raise ValueError("3X-UI 只读检查返回了无效字段")
        values[key] = value
    if values.get("XUI_EXISTS") == "no" and len(values) == 1:
        return {"installed": False, "service": "absent", "managed": False,
                "access_mode": "unavailable", "port": None}
    if values.get("XUI_EXISTS") != "yes" or values.get("XUI_SERVICE") not in {"active", "inactive"}:
        raise ValueError("3X-UI 检查缺少服务状态")
    if values.get("XUI_MANAGED") == "no" and len(values) == 3:
        return {"installed": True, "service": values["XUI_SERVICE"], "managed": False,
                "access_mode": "unknown", "port": None}
    if values.get("XUI_MANAGED") != "yes" or set(values) != accepted:
        raise ValueError("3X-UI 安装记录结构不完整")
    port = int(values["XUI_PORT"]) if re.fullmatch(r"[0-9]{1,5}", values["XUI_PORT"]) else -1
    if not 1 <= port <= 65535:
        raise ValueError("3X-UI 安装记录端口非法")
    if values["XUI_LISTENER"] not in {"local", "https", "public_unverified", "unknown"}:
        raise ValueError("3X-UI 端口监听信息不可识别")
    return {"installed": True, "service": values["XUI_SERVICE"], "managed": True,
            "access_mode": values["XUI_LISTENER"], "port": port}


PUBLIC_ACCESS_TEMPLATE = r"""set -eu
test "$(id -u)" = 0
systemctl is-active --quiet x-ui
test -f /etc/x-ui/install-result.env
test ! -L /etc/x-ui/install-result.env
test "$(stat -c %a /etc/x-ui/install-result.env)" = 600
test "$(stat -c %u /etc/x-ui/install-result.env)" = 0
test "$(sed -n 's/^XUI_PANEL_PORT=//p' /etc/x-ui/install-result.env)" = "__PORT__"
addresses="$(ss -Hltn 'sport = :__PORT__' | awk '{print $4}')"
test "$addresses" = "0.0.0.0:__PORT__"
web_path="$(sed -n 's/^XUI_WEB_BASE_PATH=//p' /etc/x-ui/install-result.env)"
printf '%s' "$web_path" | grep -Eq '^[A-Za-z0-9_-]{4,80}$'
code="$(curl --noproxy '*' --proto '=https' --tlsv1.2 --silent \
  --output /dev/null --write-out '%{http_code}' --max-time 8 \
  --connect-to '__IDENTITY__:__PORT__:127.0.0.1:__PORT__' \
  'https://__IDENTITY__:__PORT__/'"$web_path" 2>/dev/null || true)"
case "$code" in 200|301|302|303|307|308|401|403) ;; *) echo 'TLS verification failed' >&2; exit 44 ;; esac
# Only this explicit authenticated endpoint may return initial login credentials.
grep -E '^XUI_(USERNAME|PASSWORD|PANEL_PORT|WEB_BASE_PATH)=' /etc/x-ui/install-result.env
"""


def public_access_script(hostname: str, port: int) -> str:
    validate_port(port)
    identity = _public_identity(hostname)
    if not identity:
        raise ValueError("当前 SSH 地址不能安全匹配 HTTPS 证书")
    return PUBLIC_ACCESS_TEMPLATE.replace("__IDENTITY__", identity).replace("__PORT__", str(port))


def direct_url(hostname: str, port: int, web_path: str) -> str:
    return https_url(hostname, port, web_path)
