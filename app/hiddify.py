"""Native Hiddify Manager installation on a dedicated Ubuntu VPS."""

import ipaddress
import json
import re
import socket
import ssl
from urllib.parse import urlsplit

from .https_upgrade import identify

RELEASE_INSTALLER = "https://i.hiddify.com/release"

STATUS = r"""set -eu
if command -v hiddify >/dev/null && systemctl is-active --quiet hiddify-panel.service; then
  http=$(ss -Hltn 'sport = :80')
  https=$(ss -Hltn 'sport = :443')
  if [ -n "$http" ] && [ -n "$https" ]; then
    echo HIDDIFY_STATUS=running
    exit 0
  fi
fi
echo HIDDIFY_STATUS=incomplete
"""

# Read the links produced by Hiddify's own configuration. The interactive
# hiddify admin command refreshes configs and can install a QR-code package.
ADMIN_LINKS = r"""set -eu
systemctl is-active --quiet hiddify-panel.service
test -n "$(ss -Hltn 'sport = :443')"
jq -ce '[.panel_links[]? | strings | select(length <= 512 and startswith("https://"))][:12]' \
  /opt/hiddify-manager/data/current.json
"""

_ADMIN_PATH = re.compile(
    r"/[A-Za-z0-9_-]+/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}(?:/admin)?/?", re.I
)

def _link_host(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return value.lower().rstrip(".")


def _same_vps_domain(name: str, vps: str) -> bool:
    """Allow an auto-discovered domain only when every address is the enrolled public IP."""
    try:
        if identify(vps)[0] != "ip" or identify(name)[0] != "domain":
            return False
        addresses = {ipaddress.ip_address(entry[4][0])
                     for entry in socket.getaddrinfo(name, 443, type=socket.SOCK_STREAM)}
        return addresses == {ipaddress.ip_address(vps)}
    except (OSError, ValueError):
        return False


def _tls_verified(name: str, address: str) -> bool:
    """Check chain and name using local trust roots. Never send the secret URL path."""
    try:
        with socket.create_connection((address, 443), timeout=3) as connection:
            with ssl.create_default_context().wrap_socket(connection, server_hostname=name):
                return True
    except (OSError, ValueError):
        return False


def select_admin_link(raw: str, host: dict) -> dict:
    """Prefer a verified official HTTPS link and retain the known host as a fallback."""
    links = json.loads(raw)
    if not isinstance(links, list):
        raise ValueError("Invalid Hiddify link list")
    vps = _link_host(host["hostname"])
    allowed_hosts = [vps]
    if host.get("tls_domain"):
        allowed_hosts.insert(0, _link_host(host["tls_domain"]))
    valid = {}
    for link in links:
        if not isinstance(link, str) or not re.fullmatch(r"[!-~]{1,512}", link) or any(c in link for c in "\\?#"):
            continue
        try:
            url = urlsplit(link)
            if url.scheme != "https" or not url.hostname or url.username is not None or url.port not in {None, 443}:
                continue
        except ValueError:
            continue
        name = _link_host(url.hostname)
        if not _ADMIN_PATH.fullmatch(url.path):
            continue
        valid.setdefault(name, link)
    approved = [name for name in allowed_hosts if name in valid]
    for name in approved:
        if _tls_verified(name, name):
            return {"url": valid[name], "tls_verified": True}
    for name in valid:
        if name not in approved and _same_vps_domain(name, vps) and _tls_verified(name, vps):
            return {"url": valid[name], "tls_verified": True}
    if approved:
        return {"url": valid[approved[0]], "tls_verified": False}
    raise ValueError("No Hiddify admin link for the approved host")


BLOCKERS = {
    "ubuntu": "仅支持 Ubuntu 22.04、24.04 或 26.04",
    "systemd": "Hiddify 需要运行 systemd 的独立虚拟机或物理服务器",
    "tools": "缺少 ss、curl、flock 或其他基础检查工具",
    "unit_files": "systemctl 无法读取系统服务列表，无法确认是否已有 Hiddify",
    "listeners": "ss 无法读取端口监听状态，无法确认是否有端口冲突",
    "memory": "可用服务器规格不足，建议至少 1 GB 内存",
    "existing": "检测到现有 Hiddify 或安装残留，请通过 Hiddify 的管理工具检查",
    "ports": "TCP 或 UDP 的 80/443 已有监听，禁止覆盖现有服务",
    "services": "检测到其他服务器软件或非 SSH 的公网监听，请改用干净的专用 VPS",
    "ssh": "首版仅支持 SSH 使用标准 TCP 22 的专用 VPS",
}

PRECHECK = r"""
hiddify_is_ops_agent_owner() {
  local owner=$1 process=$2 component=$3 program=$4 pid
  local pattern="^users:\\(\\(\"$process\",pid=([1-9][0-9]*),fd=[0-9]+\\)\\)$"
  [[ "$owner" =~ $pattern ]] || return 1
  pid=${BASH_REMATCH[1]}
  [ "$(readlink "/proc/$pid/exe" 2>/dev/null)" = "/opt/google-cloud-ops-agent/subagents/$program" ] || return 1
  awk -F: -v group="/system.slice/google-cloud-ops-agent-$component.service" '
    (($1 == "0" && $2 == "") || $2 == "name=systemd") && $3 == group { found=1 }
    END { exit !found }
  ' "/proc/$pid/cgroup" 2>/dev/null
}

hiddify_precheck() {
  local protocol socket_state recv_queue send_queue address peer owner
  if ! (. /etc/os-release && [ "${ID:-}" = ubuntu ] &&
        case "${VERSION_ID:-}" in 22.04|24.04|26.04) true ;; *) false ;; esac); then
    echo ubuntu; return
  fi
  case "${SSH_CONNECTION:-}" in *' 22') ;; *) echo ssh; return ;; esac
  for tool in ss curl flock timeout systemctl systemd-detect-virt; do
    if ! command -v "$tool" >/dev/null 2>&1; then echo tools; return; fi
  done
  if [ "$(ps -p 1 -o comm=)" != systemd ] || systemd-detect-virt --container --quiet; then
    echo systemd; return
  fi
  for path in /opt/hiddify-manager /opt/hiddify-config /opt/hiddify-server /usr/bin/hiddify /usr/local/bin/hiddify; do
    if [ -e "$path" ] || [ -L "$path" ]; then echo existing; return; fi
  done
  if compgen -G '/var/log/netdeploy-hiddify.*.log' >/dev/null; then echo existing; return; fi
  # systemd 255 returns 1 when a name filter matches no unit files.
  if ! units=$(systemctl list-unit-files --type=service --no-legend --no-pager); then echo unit_files; return; fi
  if [[ "$units" =~ (^|$'\n')[[:blank:]]*hiddify[^[:space:]]*[.]service([[:space:]]|$) ]]; then
    echo existing; return
  fi
  if ! listeners=$(ss -H -lntup); then echo listeners; return; fi
  if printf '%s\n' "$listeners" | awk '$5 ~ /:(80|443)$/ { busy=1 } END { exit !busy }'; then
    echo ports; return
  fi
  while read -r protocol socket_state recv_queue send_queue address peer owner; do
    [ -n "$protocol" ] || continue
    case "$address" in 127.*|\[::1\]:*|::1:*) continue ;; esac
    case "$protocol:${address##*:}" in
      tcp:22|udp:68|udp:546) continue ;;
      # Google Cloud's packaged Ops Agent uses these sockets within the VM.
      # Verify the sole socket owner by executable and systemd service cgroup.
      tcp:20201)
        hiddify_is_ops_agent_owner "$owner" otelopscol opentelemetry-collector \
          opentelemetry-collector/otelopscol && continue ;;
      tcp:20202)
        hiddify_is_ops_agent_owner "$owner" fluent-bit fluent-bit \
          fluent-bit/bin/fluent-bit && continue ;;
    esac
    echo services; return
  done <<< "$listeners"
  for tool in nginx apache2 haproxy caddy x-ui s-ui xray sing-box docker mariadbd mysqld redis-server; do
    if command -v "$tool" >/dev/null 2>&1; then echo services; return; fi
  done
  if ! awk '$1 == "MemTotal:" { ok=($2 >= 900000) } END { exit !ok }' /proc/meminfo; then
    echo memory; return
  fi
  echo ready
}
"""


def steps() -> list[dict]:
    return [
        {
            "label": "复核专用 VPS 并运行 Hiddify 官网一键安装入口（release）",
            "timeout": 2500,
            "script": """set -eu
umask 077
test "$(id -u)" = 0
case "$(uname -m)" in x86_64|aarch64|arm64) ;; *) exit 1 ;; esac
""" + PRECHECK + f"""
command -v flock >/dev/null 2>&1
exec 9>/run/lock/netdeploy-hiddify.lock
flock -n 9 || {{ echo '已有 Hiddify 安装进程' >&2; exit 1; }}
check_host() {{
  state=$(hiddify_precheck)
  test "$state" = ready || {{ printf 'Hiddify 环境复核阻止安装：%s\n' "$state" >&2; exit 1; }}
  free_kb=$(df -Pk / | awk 'NR == 2 {{ print $4 }}')
  test "$free_kb" -ge 5000000
}}
check_host
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
cd "$work"
curl --proto '=https' --proto-redir '=https' -fsSL --connect-timeout 15 --max-time 90 --retry 2 -o release.sh '{RELEASE_INSTALLER}'
test -s release.sh
check_host
log=$(mktemp /var/log/netdeploy-hiddify.XXXXXX.log)
# The upstream installer creates runtimes for unprivileged systemd services.
# Keep NetDeploy's staging and log private without passing that mask to Hiddify.
if (umask 022 && NO_UI=true timeout -k 20s 35m bash ./release.sh) </dev/null >"$log" 2>&1; then
  printf '安装器已返回；受保护的原始日志在 VPS 的 %s\n' "$log"
else
  printf '安装未完成。请在 VPS 检查受保护的日志 %s 和现有服务，避免直接重装。\n' "$log" >&2
  exit 1
fi
""",
        },
        {
            "label": "通过可信 SSH 只读验收 Hiddify 服务",
            "timeout": 90,
            "script": """set -eu
version=$(cat /opt/hiddify-manager/VERSION)
[[ "$version" =~ ^v?[0-9]+[.][0-9]+[.][0-9]+$ ]]
command -v hiddify >/dev/null
for attempt in $(seq 1 15); do
  if systemctl is-active --quiet hiddify-panel.service &&
     test -n "$(ss -Hltn 'sport = :80')" &&
     test -n "$(ss -Hltn 'sport = :443')"; then
    printf 'Hiddify Manager %s 正在运行，80/443 TCP 已监听。请在任务中打开管理面板。\n' "$version"
    exit 0
  fi
  sleep 3
done
echo 'Hiddify 进程或 80/443 监听未通过验收，请通过可信 SSH 查看现有安装。' >&2
exit 1
""",
        },
    ]
