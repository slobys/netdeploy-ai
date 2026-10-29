"""Audited, pinned, non-Docker 3X-UI deployment recipe.

The official v3.11.0 unattended installer binds public HTTP when SSL is
skipped. Verify the exact upstream installer SHA-256, then make a checked,
narrowly scoped change enforcing localhost-only HTTP via SSH tunnel.
"""
from __future__ import annotations

import re

VERSION = "v3.11.0"
INSTALLER_SHA256 = "9684bae4f769b2127fcceceb4f200045657381311867529e6ba76c6b58e2825d"
INSTALL_URL = f"https://raw.githubusercontent.com/MHSanaei/3x-ui/{VERSION}/install.sh"
STAGING = "/var/lib/netdeploy/3x-ui"
INSTALL_FILE = f"{STAGING}/install-{VERSION}.sh"
DEFAULT_PORT = 24443


def validate_port(port: object) -> int:
    # Strings and bool must not enter shell-script substitutions.
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("3X-UI 面板端口必须是 1024–65535 之间的整数")
    return port


def deployment_steps(port: int) -> list[dict]:
    validate_port(port)
    scripts = [
        (
            "检查 root / systemd / 现有 3X-UI 和 TCP 端口",
            r"""set -eu
test "$(id -u)" = 0
test -r /etc/os-release
. /etc/os-release
case "${ID:-}" in ubuntu|debian) ;; *) echo "Only Ubuntu/Debian supported" >&2; exit 12 ;; esac
test "$(uname -m)" = x86_64 || test "$(uname -m)" = aarch64
command -v bash >/dev/null
command -v apt-get >/dev/null
command -v systemctl >/dev/null
test -d /run/systemd/system
command -v ss >/dev/null
command -v sha256sum >/dev/null
command -v sed >/dev/null
command -v grep >/dev/null
test ! -d /usr/local/x-ui
test ! -d /etc/x-ui
if command -v x-ui >/dev/null 2>&1 || systemctl list-unit-files --no-legend x-ui.service 2>/dev/null | grep -q '^x-ui[.]service'; then
    echo 'Existing x-ui installation detected; refusing to overwrite' >&2
    exit 13
fi
if ss -Hltn 'sport = :__PORT__' | grep -q .; then
    echo 'Requested panel TCP port is occupied' >&2
    exit 14
fi
test "$(df -Pk / | awk 'NR==2 {print $4}')" -ge 600000
echo 'Prechecks passed; no existing x-ui service or TCP port conflict'
""",
            35,
        ),
        (
            "安装 TLS 下载与校验依赖（不安装 Docker）",
            r"""set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q curl ca-certificates
echo 'Download dependencies ready'
""",
            300,
        ),
        (
            f"下载并校验官方 {VERSION} 安装器，强制管理端仅本机访问",
            r"""set -eu
umask 077
install -d -m 700 __STAGING__
tmp="$(mktemp __STAGING__/.installer.XXXXXXXX)"
trap 'rm -f "$tmp"' EXIT
curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error --retry 3 --connect-timeout 15 --max-time 90 \
  '__INSTALL_URL__' --output "$tmp"
printf '%s  %s\n' '__INSTALL_SHA256__' "$tmp" | sha256sum -c - >/dev/null
# Official unattended HTTP mode binds all interfaces; require EXACTLY one known line.
count="$(grep -Ec '^[[:space:]]*bind_local="n"$' "$tmp" || true)"
test "$count" = 1 || { echo 'Upstream script safety patch location changed; aborting' >&2; exit 16; }
sed -i 's/^\([[:space:]]*\)bind_local="n"$/\1bind_local="y"/' "$tmp"
grep -Eq '^[[:space:]]*bind_local="y"$' "$tmp"
install -m 700 "$tmp" __INSTALL_FILE__
echo 'Pinned installer verified and configured for localhost-only HTTP'
""",
            120,
        ),
        (
            f"无人值守安装 3X-UI {VERSION}（敏感输出不进入任务日志）",
            r"""set -eu
umask 077
test -f __INSTALL_FILE__
test ! -d /usr/local/x-ui
test ! -d /etc/x-ui
if ss -Hltn 'sport = :__PORT__' | grep -q .; then
    echo 'TCP port became occupied; installer not started' >&2
    exit 14
fi
install_log="$(mktemp /tmp/netdeploy-3xui-log.XXXXXXXX)"
trap 'rm -f "$install_log"' EXIT
# Upstream installer prints credentials: do not forward its stdout/stderr.
if ! env XUI_NONINTERACTIVE=1 XUI_SSL_MODE=none XUI_DB_TYPE=sqlite \
      XUI_PANEL_PORT=__PORT__ XUI_ENABLE_FAIL2BAN=false \
      bash __INSTALL_FILE__ __VERSION__ >"$install_log" 2>&1; then
    systemctl stop x-ui >/dev/null 2>&1 || true
    echo 'Official installer failed; potential partial install; service stopped. Review VPS locally, do not blindly retry.' >&2
    exit 17
fi
test -s /etc/x-ui/install-result.env || {
    systemctl stop x-ui >/dev/null 2>&1 || true
    echo 'Installer did not create credentials file; service stopped' >&2
    exit 18
}
echo 'Official installer finished; sensitive credentials kept on VPS only'
""",
            900,
        ),
        (
            "验收服务运行与本机监听；失败则停止服务",
            r"""set -eu
if ! systemctl is-active --quiet x-ui; then
    echo '3X-UI service is not active' >&2; exit 19
fi
addresses="$(ss -Hltn 'sport = :__PORT__' | awk '{print $4}')"
if ! printf '%s\n' "$addresses" | grep -Fxq '127.0.0.1:__PORT__' || \
   printf '%s\n' "$addresses" | grep -Ev '^127[.]0[.]0[.]1:__PORT__$' | grep -q .; then
    systemctl stop x-ui >/dev/null 2>&1 || true
    echo 'Panel binding is not localhost-only; service stopped to prevent insecure public access' >&2
    exit 20
fi
test -s /etc/x-ui/install-result.env
grep -Fxq 'XUI_PANEL_PORT=__PORT__' /etc/x-ui/install-result.env
web_path="$(sed -n 's/^XUI_WEB_BASE_PATH=//p' /etc/x-ui/install-result.env)"
printf '%s' "$web_path" | grep -Eq '^[A-Za-z0-9_-]{4,80}$' || { echo 'Invalid web path'; exit 23; }
http_code=000
for attempt in 1 2 3 4 5; do
    http_code="$(curl --noproxy '*' --silent --output /dev/null --write-out '%{http_code}' --max-time 5 "http://127.0.0.1:__PORT__/$web_path" || true)"
    case "$http_code" in 200|301|302|303|307|308|401|403) break ;; esac
    sleep 2
done
case "$http_code" in
    200|301|302|303|307|308|401|403) echo 'Local web endpoint responded';;
    *) echo '3X-UI local HTTP endpoint not ready; inspect service manually' >&2; exit 24;;
esac
echo '3X-UI __VERSION__ service active; panel bound to 127.0.0.1:__PORT__'
echo 'Use an SSH tunnel to access the panel. Login details are available on explicit request.'
""",
            45,
        ),
    ]
    values = {"__PORT__": str(port), "__STAGING__": STAGING,
              "__INSTALL_FILE__": INSTALL_FILE, "__INSTALL_URL__": INSTALL_URL,
              "__INSTALL_SHA256__": INSTALLER_SHA256, "__VERSION__": VERSION}
    result = []
    for label, script, timeout in scripts:
        for marker, value in values.items():
            script = script.replace(marker, value)
        result.append({"label": label, "script": script, "timeout": timeout})
    return result


ACCESS_SCRIPT = r"""set -eu
test "$(id -u)" = 0
systemctl is-active --quiet x-ui
test -r /etc/x-ui/install-result.env
test "$(stat -c %a /etc/x-ui/install-result.env)" = 600
port="$(sed -n 's/^XUI_PANEL_PORT=//p' /etc/x-ui/install-result.env)"
case "$port" in ""|*[!0-9]*) echo "Invalid panel port" >&2; exit 21 ;; esac
addresses="$(ss -Hltn "sport = :$port" | awk '{print $4}')"
test "$addresses" = "127.0.0.1:$port" || { echo "Panel is not localhost-only" >&2; exit 22; }
# Only invoked by explicit authorized credentials request, never task logging.
grep -E '^XUI_(USERNAME|PASSWORD|PANEL_PORT|WEB_BASE_PATH)=' /etc/x-ui/install-result.env
"""


def parse_access_result(output: str, expected_port: int) -> dict[str, object]:
    validate_port(expected_port)
    fields: dict[str, str] = {}
    accepted = {"XUI_USERNAME", "XUI_PASSWORD", "XUI_PANEL_PORT", "XUI_WEB_BASE_PATH"}
    for line in output.splitlines():
        if "=" not in line:
            raise ValueError("3X-UI 凭据文件格式不正确")
        key, value = line.split("=", 1)
        if key not in accepted or key in fields:
            raise ValueError("3X-UI 凭据文件存在无效或重复字段")
        fields[key] = value
    if set(fields) != accepted:
        raise ValueError("3X-UI 凭据文件缺少必要字段")
    if fields["XUI_PANEL_PORT"] != str(expected_port):
        raise ValueError("3X-UI 端口与审批方案不一致")
    for key in ("XUI_USERNAME", "XUI_PASSWORD"):
        if not re.fullmatch(r"[A-Za-z0-9]{8,80}", fields[key]):
            raise ValueError("3X-UI 凭据格式不符合当前版本预期")
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,80}", fields["XUI_WEB_BASE_PATH"]):
        raise ValueError("3X-UI Web 路径格式不符合当前版本预期")
    return {
        "username": fields["XUI_USERNAME"],
        "password": fields["XUI_PASSWORD"],
        "port": expected_port,
        "web_path": fields["XUI_WEB_BASE_PATH"],
        "local_url": f"http://127.0.0.1:{expected_port}/{fields['XUI_WEB_BASE_PATH']}",
    }
