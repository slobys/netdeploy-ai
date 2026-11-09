"""Fixed, native Hiddify Manager installation on a dedicated Ubuntu VPS."""

VERSION = "14.0.5"
COMMIT = "331c1114d4bb0bcf62e9ac719932ae904e88cf9c"
UPSTREAM = f"https://raw.githubusercontent.com/hiddify/Hiddify-Manager/{COMMIT}/scripts/common"
INSTALLER_SHA256 = "03a60aaa97608bd42b4952eaedcc17ab5a3c4e4c6ff4a49f22a617323983d6c0"
UTILS_SHA256 = "0c3ea9b8f883faa3eb9498eaf819d642e5fd20fa19df080c081e0f36340e534b"

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
  for tool in ss curl sha256sum flock timeout systemctl systemd-detect-virt; do
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
            "label": f"复核专用 VPS 并运行固定版 Hiddify Manager {VERSION} 安装器",
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
curl --proto '=https' --proto-redir '=https' -fsSL --connect-timeout 15 --max-time 90 --retry 2 -o hiddify_installer.sh '{UPSTREAM}/hiddify_installer.sh'
curl --proto '=https' --proto-redir '=https' -fsSL --connect-timeout 15 --max-time 90 --retry 2 -o utils.sh '{UPSTREAM}/utils.sh'
printf '%s  %s\n' '{INSTALLER_SHA256}' hiddify_installer.sh '{UTILS_SHA256}' utils.sh | sha256sum --check --status
check_host
log=$(mktemp /var/log/netdeploy-hiddify.XXXXXX.log)
# The upstream installer creates runtimes for unprivileged systemd services.
# Keep NetDeploy's staging and log private without passing that mask to Hiddify.
if (umask 022 && timeout -k 20s 35m bash ./hiddify_installer.sh 'v{VERSION}' --no-gui --no-log) </dev/null >"$log" 2>&1; then
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
            "script": f"""set -eu
test "$(cat /opt/hiddify-manager/VERSION)" = '{VERSION}'
command -v hiddify >/dev/null
for attempt in $(seq 1 15); do
  if systemctl is-active --quiet hiddify-panel.service &&
     test -n "$(ss -Hltn 'sport = :80')" &&
     test -n "$(ss -Hltn 'sport = :443')"; then
    echo 'Hiddify 服务正在运行，80/443 TCP 已监听。通过可信 SSH 执行 hiddify admin 查看管理链接。'
    exit 0
  fi
  sleep 3
done
echo 'Hiddify 进程或 80/443 监听未通过验收，请通过可信 SSH 查看现有安装。' >&2
exit 1
""",
        },
    ]
