"""Enable direct public HTTP on an existing, NetDeploy-managed 3X-UI.

Requires an explicit approved plan. Never reinstall x-ui, change its
credentials, touch its certificate settings or use TCP 80/Certbot.
The internal HTTP URL is also usable by a trusted NPM container in host mode.
"""
from __future__ import annotations

from .three_x_ui import validate_port
from .listening import PUBLIC_SOCKET_CHECK
from .firewall import allow_port_script

HTTP_PREFLIGHT = r"""set -eu
test "$(id -u)" = 0
systemctl is-active --quiet x-ui
test -x /usr/local/x-ui/x-ui
test -f /etc/x-ui/install-result.env
test ! -L /etc/x-ui/install-result.env
test "$(stat -c %u /etc/x-ui/install-result.env)" = 0
test "$(stat -c %a /etc/x-ui/install-result.env)" = 600
grep -Fxq 'XUI_PANEL_PORT=__PORT__' /etc/x-ui/install-result.env
actual="$(ss -Hltn 'sport = :__PORT__' | awk '{print $4}')"
test "$actual" = '127.0.0.1:__PORT__' || {
  echo 'XUI_HTTP_EXPECTED_LOCAL: existing listener changed, no action taken' >&2; exit 55;
}
web_path="$(sed -n 's/^XUI_WEB_BASE_PATH=//p' /etc/x-ui/install-result.env)"
printf '%s' "$web_path" | grep -Eq '^[A-Za-z0-9_-]{4,80}$'
code="$(curl -4 --noproxy '*' --proto '=http' -s -o /dev/null -w '%{http_code}' \
  --max-time 7 "http://127.0.0.1:__PORT__/$web_path" 2>/dev/null)" || code=000
case "$code" in 200|301|302|303|307|308|401|403) ;; *)
  echo 'XUI_HTTP_LOCAL_PROBE_FAILED: refuse to publish an unverified panel' >&2; exit 55 ;;
esac
# Do not modify a panel whose HTTPS certificate files are configured.
current_cert="$(/usr/local/x-ui/x-ui setting -getCert true 2>/dev/null || true)"
printf '%s\n' "$current_cert" | grep -Eq '^(cert|key): /' && {
  echo 'XUI_CERT_ALREADY_CONFIGURED: use existing HTTPS access instead' >&2; exit 55;
}
echo 'XUI_PUBLIC_HTTP_PRECHECK_OK: approved service is managed and local-only'
"""

HTTP_ACTIVATE = r"""set -eu
test "$(id -u)" = 0
cli=/usr/local/x-ui/x-ui
test -x "$cli"
test -f /etc/x-ui/install-result.env && test ! -L /etc/x-ui/install-result.env
test "$(stat -c %a /etc/x-ui/install-result.env)" = 600
grep -Fxq 'XUI_PANEL_PORT=__PORT__' /etc/x-ui/install-result.env
test "$(ss -Hltn 'sport = :__PORT__' | awk '{print $4}')" = '127.0.0.1:__PORT__' || exit 55
web_path="$(sed -n 's/^XUI_WEB_BASE_PATH=//p' /etc/x-ui/install-result.env)"
printf '%s' "$web_path" | grep -Eq '^[A-Za-z0-9_-]{4,80}$'
previous="$("$cli" setting -getListen true 2>/dev/null || true)"
printf '%s\n' "$previous" | grep -Fxq 'listenIP: 127.0.0.1' || {
  echo 'XUI_HTTP_BASELINE_CHANGED: refuse unknown listener state' >&2; exit 55;
}
__PUBLIC_SOCKET_CHECK__
changed=no
rollback() {
  if test "$changed" = yes; then
    "$cli" setting -listenIP 127.0.0.1 >/dev/null 2>&1 || true
    systemctl restart x-ui >/dev/null 2>&1 || true
  fi
}
trap rollback EXIT
changed=yes
"$cli" setting -listenIP 0.0.0.0 >/dev/null
listen="$("$cli" setting -getListen true 2>/dev/null || true)"
printf '%s\n' "$listen" | grep -Fxq 'listenIP: 0.0.0.0' || {
  echo 'XUI_HTTP_LISTENER_READBACK_FAILED: rolling back' >&2; exit 56;
}
systemctl restart x-ui
ready=no
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if systemctl is-active --quiet x-ui && netdeploy_public_socket __PORT__; then
    code="$(curl -4 --noproxy '*' --proto '=http' -s -o /dev/null -w '%{http_code}' \
      --max-time 6 "http://127.0.0.1:__PORT__/$web_path" 2>/dev/null)" || code=000
    case "$code" in 200|301|302|303|307|308|401|403) ready=yes;break;; esac
  fi
  sleep 1
done
test "$ready" = yes || {
  echo 'XUI_HTTP_PUBLIC_HEALTH_FAILED: restoring localhost listener' >&2; exit 56;
}
# Only the selected TCP panel port, never UFW 80 or whole-firewall disable.
__UFW_ALLOW__
changed=no
trap - EXIT
echo 'XUI_PUBLIC_HTTP_VERIFIED: wildcard listener and HTTP loopback probe passed on TCP __PORT__'
echo 'NPM may reverse proxy http://127.0.0.1:__PORT__ via host networking'
echo 'The cloud security group must separately restrict inbound TCP __PORT__ to the administrator IP'
"""


def http_upgrade_steps(port: int) -> list[dict]:
    validate_port(port)
    data = {"__PORT__": str(port),
            "__PUBLIC_SOCKET_CHECK__": PUBLIC_SOCKET_CHECK,
            "__UFW_ALLOW__": allow_port_script(port, "tcp")}
    result = []
    for label, template, timeout in [
        ("核对已安装面板为受管理、本机 HTTP 状态", HTTP_PREFLIGHT, 35),
        ("切换公网 HTTP、验证监听与面板响应（失败回退）", HTTP_ACTIVATE, 75),
    ]:
        for key, value in data.items():
            template = template.replace(key, value)
        result.append({"label": label, "script": template, "timeout": timeout})
    return result
