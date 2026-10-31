"""Dockge Apps: reviewed source-built fork deployment, localhost-only Web UI.

The user's fork has no published Docker release image. Build the audited
Dockerfile.apps from an exact Git commit instead of pulling upstream Dockge.
Existing upstream/manual installations and stack data are never overwritten.
"""
from __future__ import annotations

import ipaddress
import re

VERSION = "1.5.0-apps.1"
SOURCE_REPO = "https://github.com/slobys/dockge-apps.git"
SOURCE_SHA = "66aec693a974bd980f632f643586deab16932531"
IMAGE = f"netdeploy/dockge-apps:{SOURCE_SHA[:12]}"
PORT = 5001  # The upstream container port stays fixed; host port is configurable.
ROOT_DIR = "/opt/netdeploy/dockge"
SOURCE_DIR = f"{ROOT_DIR}/source"
STACKS_DIR = "/opt/stacks"
CONTAINER = "netdeploy-dockge-apps"
MANAGED_MARK = f"NetDeploy managed Dockge Apps {SOURCE_SHA}"


CHECK = r"""set -eu
test "$(id -u)" = 0 || { echo 'DOCKGE_ROOT_REQUIRED' >&2; exit 21; }
command -v docker >/dev/null || { echo 'DOCKGE_DOCKER_MISSING' >&2; exit 22; }
docker info >/dev/null || { echo 'DOCKGE_DOCKER_NOT_READY' >&2; exit 22; }
docker compose version >/dev/null || { echo 'DOCKGE_COMPOSE_V2_REQUIRED' >&2; exit 23; }
command -v git >/dev/null || { echo 'DOCKGE_GIT_REQUIRED: install Git to build the source fork' >&2; exit 23; }
command -v ss >/dev/null || { echo 'DOCKGE_SS_REQUIRED' >&2; exit 24; }
command -v curl >/dev/null || { echo 'DOCKGE_CURL_REQUIRED' >&2; exit 24; }
test -S /var/run/docker.sock || { echo 'DOCKGE_SOCKET_UNAVAILABLE' >&2; exit 25; }
test "$(df -Pk / | awk 'NR==2 {print $4}')" -ge 3000000 || {
  echo 'DOCKGE_DISK_LOW: 3 GB free required to build the fork and retain Docker data' >&2; exit 26;
}
case "$(uname -m)" in x86_64|aarch64|arm64) ;; *)
  echo 'DOCKGE_ARCH_UNSUPPORTED' >&2; exit 27;;
esac
for target in /opt/netdeploy /opt/netdeploy/dockge /opt/dockge /opt/dockge-apps /opt/stacks; do
  if test -L "$target"; then
    echo 'DOCKGE_UNSAFE_SYMLINK: existing symlink, refusing to continue' >&2; exit 28;
  fi
done
# Old upstream Dockge, an existing fork, or any partial NetDeploy installation
# must be inspected/migrated separately; never steal another Docker stack.
if test -e /opt/dockge || test -e /opt/dockge-apps ||
   test -e /opt/netdeploy/dockge; then
  echo 'DOCKGE_EXISTS: existing upstream/fork installation or partial directory' >&2; exit 29
fi
if docker container inspect dockge >/dev/null 2>&1 ||
   docker container inspect dockge-apps >/dev/null 2>&1 ||
   docker container inspect netdeploy-dockge >/dev/null 2>&1 ||
   docker container inspect netdeploy-dockge-apps >/dev/null 2>&1 ||
   docker ps -a --format '{{.Image}}' |
     grep -Eq '(^|/)(louislam/dockge|dockge-apps|netdeploy/dockge-apps)(:|@)'; then
  echo 'DOCKGE_CONTAINER_EXISTS: refusing to replace a pre-existing Dockge image/container' >&2; exit 29
fi
if ss -Hltn 'sport = :__HOST_PORT__' | grep -q . ||
   test -n "$(docker ps -q --filter 'publish=__HOST_PORT__/tcp')"; then
  echo 'DOCKGE_PORT_BUSY: TCP __HOST_PORT__ already in use' >&2; exit 30
fi
echo 'DOCKGE_PREFLIGHT_OK: source build prerequisites, 5001/TCP free, no existing Dockge'
"""


FETCH = r"""set -eu
test "$(id -u)" = 0
command -v git >/dev/null
test ! -e /opt/netdeploy/dockge && test ! -L /opt/netdeploy/dockge || {
  echo 'DOCKGE_SOURCE_CONFLICT: a previous deployment exists; do not overwrite' >&2; exit 31;
}
test ! -L /opt/netdeploy || { echo 'DOCKGE_PARENT_SYMLINK' >&2; exit 31; }
install -d -m 700 /opt/netdeploy
tmp="$(mktemp -d /opt/netdeploy/.dockge-apps-build.XXXXXXXX)"
trap 'if test -n "$tmp" && test -d "$tmp"; then rm -rf -- "$tmp"; fi' EXIT
# Fetch only this exact audited revision. Never install a moving main/latest.
git -C "$tmp" init -q
git -C "$tmp" remote add origin https://github.com/slobys/dockge-apps.git
git -C "$tmp" -c protocol.version=2 fetch -q --depth 1 origin 66aec693a974bd980f632f643586deab16932531 || {
  echo 'DOCKGE_SOURCE_FETCH_FAILED: cannot fetch reviewed fork commit from GitHub' >&2; exit 31;
}
git -C "$tmp" checkout -q --detach FETCH_HEAD
actual="$(git -C "$tmp" rev-parse HEAD)"
test "$actual" = '66aec693a974bd980f632f643586deab16932531' || {
  echo 'DOCKGE_SOURCE_REVISION_MISMATCH: refusing unreviewed source code' >&2; exit 31;
}
test -s "$tmp/docker/Dockerfile.apps" &&
  test -s "$tmp/compose.apps.yaml" && test -s "$tmp/package-lock.json" || {
  echo 'DOCKGE_FORK_SOURCE_INCOMPLETE: Dockerfile.apps or app sources missing' >&2; exit 31;
}
grep -Eq '"version"[[:space:]]*:[[:space:]]*"1[.]5[.]0-apps[.]1"' "$tmp/package.json" || {
  echo 'DOCKGE_FORK_VERSION_MISMATCH' >&2; exit 31;
}
# Keep the fixed source checkout for rebuilds and future managed updates.
install -d -m 700 /opt/netdeploy/dockge
mv -- "$tmp" /opt/netdeploy/dockge/source
tmp=''
printf '%s\n' 'NetDeploy managed Dockge Apps 66aec693a974bd980f632f643586deab16932531' \
  > /opt/netdeploy/dockge/.netdeploy-managed
chmod 600 /opt/netdeploy/dockge/.netdeploy-managed
echo 'DOCKGE_SOURCE_READY: Dockge Apps 1.5.0-apps.1, pinned verified commit'
"""


CONFIGURE = r"""set -eu
test "$(id -u)" = 0
umask 077
root=/opt/netdeploy/dockge
src="$root/source"
test -f "$root/.netdeploy-managed" && test ! -L "$root/.netdeploy-managed" || {
  echo 'DOCKGE_MANAGED_MARKER_MISSING' >&2; exit 32;
}
grep -Fxq 'NetDeploy managed Dockge Apps 66aec693a974bd980f632f643586deab16932531' \
  "$root/.netdeploy-managed" || exit 32
test -d "$src" && test ! -L "$src" || exit 32
test "$(git -C "$src" rev-parse HEAD)" = '66aec693a974bd980f632f643586deab16932531' || {
  echo 'DOCKGE_SOURCE_CHANGED: aborting source build' >&2; exit 32;
}
test ! -e "$root/compose.yaml" && test ! -L "$root/compose.yaml" || {
  echo 'DOCKGE_CONFIG_CONFLICT: refusing to overwrite existing Compose' >&2; exit 32;
}
test ! -L /opt/stacks || {
  echo 'DOCKGE_STACKS_SYMLINK: refusing to follow /opt/stacks' >&2; exit 32;
}
if test -e /opt/stacks && test ! -d /opt/stacks; then
  echo 'DOCKGE_STACKS_CONFLICT: /opt/stacks is not a directory' >&2; exit 32
fi
install -d -m 700 "$root/data"
if test ! -d /opt/stacks; then install -d -m 750 /opt/stacks; fi
cat > "$root/compose.yaml" <<'NETDEPLOY_DOCKGE_APPS_COMPOSE'
services:
  dockge-apps:
    build:
      context: /opt/netdeploy/dockge/source
      dockerfile: docker/Dockerfile.apps
    image: netdeploy/dockge-apps:66aec693a974
    container_name: netdeploy-dockge-apps
    restart: unless-stopped
    ports:
      - "__HOST_BIND__:__HOST_PORT__:5001/tcp"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /opt/netdeploy/dockge/data:/app/data
      - /opt/stacks:/opt/stacks
    environment:
      DOCKGE_STACKS_DIR: /opt/stacks
      DOCKGE_ENABLE_CONSOLE: "false"
NETDEPLOY_DOCKGE_APPS_COMPOSE
chmod 600 "$root/compose.yaml"
cat > "$root/access.conf" <<'NETDEPLOY_DOCKGE_ACCESS'
DOCKGE_HOST_PORT=__HOST_PORT__
DOCKGE_BIND=__HOST_BIND__
NETDEPLOY_DOCKGE_ACCESS
chmod 600 "$root/access.conf"
docker compose -f "$root/compose.yaml" config -q
# Build the actual fork source, NOT the upstream louislam/dockge application.
# Dockerfile.apps itself uses an upstream base image (mutable), disclosed in docs.
docker compose -f "$root/compose.yaml" build --pull
actual="$(docker image inspect -f '{{.Os}}/{{.Architecture}}' netdeploy/dockge-apps:66aec693a974)"
case "$(uname -m):$actual" in
  x86_64:linux/amd64|aarch64:linux/arm64|arm64:linux/arm64) ;;
  *) echo 'DOCKGE_FORK_IMAGE_ARCH_MISMATCH' >&2; exit 32 ;;
esac
echo 'DOCKGE_APPS_BUILD_READY: source-built fork, host port __HOST_PORT__, Apps Center enabled'
"""


# Read only the two allowlisted values; NEVER source a remote config as shell.
ACCESS_SETTINGS = r"""dockge_access_settings() {
  record=/opt/netdeploy/dockge/access.conf
  dockge_host_port=5001
  dockge_bind=127.0.0.1
  if test -e "$record" || test -L "$record"; then
    test -f "$record" && test ! -L "$record" || return 1
    test "$(stat -c %u "$record")" = 0 && test "$(stat -c %a "$record")" = 600 || return 1
    test "$(grep -c '^DOCKGE_HOST_PORT=' "$record")" = 1 || return 1
    test "$(grep -c '^DOCKGE_BIND=' "$record")" = 1 || return 1
    dockge_host_port="$(sed -n 's/^DOCKGE_HOST_PORT=//p' "$record")"
    dockge_bind="$(sed -n 's/^DOCKGE_BIND=//p' "$record")"
  fi
  case "$dockge_host_port" in *[!0-9]*|'') return 1;; esac
  test "$dockge_host_port" -ge 1024 && test "$dockge_host_port" -le 65535 || return 1
  case "$dockge_bind" in 127.0.0.1|0.0.0.0) ;; *) return 1;; esac
}
"""
BINDING_GUARD = ACCESS_SETTINGS + r"""dockge_local_only() {
  dockge_access_settings || return 1
  portmap="$(docker container inspect -f '{{json .HostConfig.PortBindings}}' netdeploy-dockge-apps 2>/dev/null)" || return 1
  test "$portmap" = "{\"5001/tcp\":[{\"HostIp\":\"$dockge_bind\",\"HostPort\":\"$dockge_host_port\"}]}" || return 1
  docker container inspect -f '{{.Config.Image}}' netdeploy-dockge-apps 2>/dev/null |
    grep -Fxq 'netdeploy/dockge-apps:66aec693a974' || return 1
}
"""


VERIFY = r"""set -eu
__BINDING_GUARD__
test "$(id -u)" = 0
root=/opt/netdeploy/dockge
test -f "$root/compose.yaml" && test ! -L "$root/compose.yaml" || exit 33
test -f "$root/.netdeploy-managed" && test ! -L "$root/.netdeploy-managed" || exit 33
grep -Fxq 'NetDeploy managed Dockge Apps 66aec693a974bd980f632f643586deab16932531' \
  "$root/.netdeploy-managed" || exit 33
test "$(git -C "$root/source" rev-parse HEAD)" = '66aec693a974bd980f632f643586deab16932531' || exit 33
docker compose -f "$root/compose.yaml" up -d --no-build
ready=no
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if test "$(docker container inspect -f '{{.State.Running}}' netdeploy-dockge-apps 2>/dev/null)" = true &&
     dockge_local_only; then
    response="$(curl -4 --noproxy '*' --silent --output /dev/null --write-out '%{http_code}' --max-time 7 \
      "http://127.0.0.1:$dockge_host_port/" 2>/dev/null)" || response=000
    case "$response" in
      200|301|302|303|307|308|401|403) ready=yes; break ;;
    esac
  fi
  sleep 2
done
if test "$ready" != yes; then
  if ! dockge_local_only; then
    docker compose -f "$root/compose.yaml" stop >/dev/null 2>&1 || true
    echo 'DOCKGE_PORT_UNVERIFIED: service stopped to prevent unexpected public HTTP' >&2
  fi
  echo 'DOCKGE_VERIFY_FAILED: inspect dockge-apps logs and localhost 5001' >&2
  exit 33
fi
echo 'DOCKGE_APPS_READY: source-built Dockge Apps running on TCP __HOST_PORT__, bind __HOST_BIND__'
echo 'App Center includes Nginx Proxy Manager, IT-Tools and MyIP with editable ports'
"""


STATUS = r"""set -eu
__BINDING_GUARD__
# Read-only: report old Dockge as present but UNMANAGED. Never mutate it.
if test -e /opt/dockge || test -e /opt/dockge-apps ||
   test -e /opt/netdeploy/dockge ||
   docker container inspect dockge >/dev/null 2>&1 ||
   docker container inspect dockge-apps >/dev/null 2>&1 ||
   docker container inspect netdeploy-dockge >/dev/null 2>&1 ||
   docker container inspect netdeploy-dockge-apps >/dev/null 2>&1 ||
   docker ps -a --format '{{.Image}}' 2>/dev/null |
     grep -Eq '(^|/)(louislam/dockge|dockge-apps|netdeploy/dockge-apps)(:|@)'; then
  echo 'DOCKGE_INSTALLED=yes'
else
  echo 'DOCKGE_INSTALLED=no'
  exit 0
fi
root=/opt/netdeploy/dockge
if test -f "$root/.netdeploy-managed" &&
   test ! -L "$root/.netdeploy-managed" &&
   grep -Fxq 'NetDeploy managed Dockge Apps 66aec693a974bd980f632f643586deab16932531' "$root/.netdeploy-managed" &&
   test -f "$root/compose.yaml" && test ! -L "$root/compose.yaml" &&
   test "$(git -C "$root/source" rev-parse HEAD 2>/dev/null)" = '66aec693a974bd980f632f643586deab16932531'; then
  echo 'DOCKGE_MANAGED=yes'
else
  echo 'DOCKGE_MANAGED=no'
fi
if docker container inspect netdeploy-dockge-apps >/dev/null 2>&1 &&
   test "$(docker container inspect -f '{{.State.Running}}' netdeploy-dockge-apps)" = true; then
  echo 'DOCKGE_RUNNING=yes'
else
  echo 'DOCKGE_RUNNING=no'
fi
if dockge_local_only; then
  printf 'DOCKGE_PORT=%s\n' "$dockge_host_port"
  code="$(curl -4 --noproxy '*' --silent --output /dev/null --write-out '%{http_code}' --max-time 6 \
    "http://127.0.0.1:$dockge_host_port/" 2>/dev/null)" || code=000
  case "$code" in
    200|301|302|303|307|308|401|403) if test "$dockge_bind" = 0.0.0.0; then echo 'DOCKGE_ACCESS=public'; else echo 'DOCKGE_ACCESS=local'; fi ;;
    *) echo 'DOCKGE_ACCESS=unverified' ;;
  esac
else
  echo 'DOCKGE_ACCESS=unverified'
fi
"""


for _name in ("VERIFY", "STATUS"):
    globals()[_name] = globals()[_name].replace("__BINDING_GUARD__", BINDING_GUARD)


def validate_port(port: int) -> int:
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("Dockge Apps 宿主机端口应为 1024–65535")
    return port


def steps(host_port: int = PORT, access_mode: str = "local") -> list[dict]:
    host_port = validate_port(host_port)
    if access_mode not in {"local", "public"}:
        raise ValueError("未知的 Dockge Apps 访问模式")
    bind = "0.0.0.0" if access_mode == "public" else "127.0.0.1"
    check = CHECK.replace("__HOST_PORT__", str(host_port))
    configure = CONFIGURE.replace("__HOST_PORT__", str(host_port)).replace("__HOST_BIND__", bind)
    verify = VERIFY.replace("__HOST_PORT__", str(host_port)).replace("__HOST_BIND__", bind)
    return [
        {"label": "检查 Docker、Compose、Git、目标端口及已有 Dockge", "script": check, "timeout": 45},
        {"label": "从 GitHub 下载并校验 Dockge Apps 固定源码版本", "script": FETCH, "timeout": 240},
        {"label": f"构建 Dockge Apps 并配置宿主机 {host_port}/TCP", "script": configure, "timeout": 1200},
        {"label": f"验证 Dockge Apps {host_port}/TCP 与真实 Docker 端口绑定", "script": verify, "timeout": 180},
    ]



# Only change a previously managed, live Dockge Apps instance. Existing data,
# application source, images, stacks and credentials remain untouched.
RECONFIGURE_CHECK = r"""set -eu
__BINDING_GUARD__
test "$(id -u)" = 0
test -f /opt/netdeploy/dockge/.netdeploy-managed && test -f /opt/netdeploy/dockge/compose.yaml
grep -Fxq 'NetDeploy managed Dockge Apps 66aec693a974bd980f632f643586deab16932531' \
  /opt/netdeploy/dockge/.netdeploy-managed
test "$(docker inspect -f '{{.State.Running}}' netdeploy-dockge-apps)" = true
dockge_local_only || {
  echo 'DOCKGE_ACCESS_BASELINE_CHANGED: current Docker binding is not verified' >&2; exit 50
}
if test "$dockge_host_port" != '__NEW_PORT__'; then
  if ss -Hltn 'sport = :__NEW_PORT__' | grep -q . ||
     test -n "$(docker ps -q --filter 'publish=__NEW_PORT__/tcp')"; then
    echo 'DOCKGE_ACCESS_PORT_BUSY: requested host port unavailable' >&2; exit 51
  fi
fi
echo 'DOCKGE_ACCESS_CHANGE_READY: existing managed Dockge Apps verified'
"""

RECONFIGURE_APPLY = r"""set -eu
__BINDING_GUARD__
root=/opt/netdeploy/dockge
test "$(id -u)" = 0
grep -Fxq 'NetDeploy managed Dockge Apps 66aec693a974bd980f632f643586deab16932531' \
  "$root/.netdeploy-managed" || exit 50
dockge_local_only || exit 50
test "$(docker inspect -f '{{.State.Running}}' netdeploy-dockge-apps)" = true || exit 50
if test "$dockge_host_port" != '__NEW_PORT__'; then
  if ss -Hltn 'sport = :__NEW_PORT__' | grep -q . ||
     test -n "$(docker ps -q --filter 'publish=__NEW_PORT__/tcp')"; then
    echo 'DOCKGE_ACCESS_PORT_BUSY' >&2; exit 51
  fi
fi
old='      - "'$dockge_bind':'$dockge_host_port':5001/tcp"'
new='      - "__NEW_BIND__:__NEW_PORT__:5001/tcp"'
test "$(grep -Fxc "$old" "$root/compose.yaml")" = 1 || {
  echo 'DOCKGE_COMPOSE_CHANGED: current published port must be reviewed' >&2; exit 52
}
test ! -L "$root/access.conf" && test ! -L "$root/compose.yaml" || exit 52
backup_compose="$(mktemp "$root/.old-compose.XXXXXXXX")"
backup_access="$(mktemp "$root/.old-access.XXXXXXXX")"
cp -p "$root/compose.yaml" "$backup_compose"
if test -f "$root/access.conf"; then
  cp -p "$root/access.conf" "$backup_access"
else
  : > "$backup_access"
fi
umask 077
edited="$(mktemp "$root/.new-compose.XXXXXXXX")"
rollback=yes
restore() {
  if test "$rollback" = yes; then
    cp -p "$backup_compose" "$root/compose.yaml" || true
    if test -s "$backup_access"; then
      cp -p "$backup_access" "$root/access.conf" || true
    else
      rm -f "$root/access.conf"
    fi
    docker compose -f "$root/compose.yaml" up -d --no-build >/dev/null 2>&1 ||
      docker compose -f "$root/compose.yaml" stop >/dev/null 2>&1 || true
  fi
  rm -f "$backup_compose" "$backup_access" "$edited"
}
trap restore EXIT
awk -v old="$old" -v new="$new" '
  $0 == old { count++; print new; next }
  { print }
  END { if (count != 1) exit 52 }
' "$root/compose.yaml" > "$edited" || {
  echo 'DOCKGE_COMPOSE_UNEXPECTED: no config changed' >&2; exit 52
}
chmod 600 "$edited"
mv -f "$edited" "$root/compose.yaml"
printf 'DOCKGE_HOST_PORT=__NEW_PORT__\nDOCKGE_BIND=__NEW_BIND__\n' > "$root/access.conf"
chmod 600 "$root/access.conf"
docker compose -f "$root/compose.yaml" config -q
docker compose -f "$root/compose.yaml" up -d --no-build
ready=no
for count in 1 2 3 4 5 6 7 8 9 10; do
  if dockge_local_only && test "$(docker inspect -f '{{.State.Running}}' netdeploy-dockge-apps)" = true; then
    code="$(curl -4 --noproxy '*' --silent --output /dev/null --write-out '%{http_code}' \
      --max-time 7 'http://127.0.0.1:__NEW_PORT__/' 2>/dev/null)" || code=000
    case "$code" in 200|301|302|303|307|308|401|403) ready=yes; break;; esac
  fi
  sleep 2
done
test "$ready" = yes || {
  echo 'DOCKGE_ACCESS_VERIFY_FAILED: restoring previous binding' >&2; exit 53
}
rollback=no
echo 'DOCKGE_ACCESS_CHANGE_VERIFIED: __NEW_BIND__:__NEW_PORT__'
"""


def reconfigure_steps(host_port: int, access_mode: str) -> list[dict]:
    host_port = validate_port(host_port)
    if access_mode not in {"local", "public"}:
        raise ValueError("无效的 Dockge Apps 访问模式")
    bind = "0.0.0.0" if access_mode == "public" else "127.0.0.1"
    values = {"__NEW_PORT__": str(host_port), "__NEW_BIND__": bind,
              "__BINDING_GUARD__": BINDING_GUARD}
    output = []
    for label, body, timeout in (
        ("核对已安装 Dockge Apps 与目标端口", RECONFIGURE_CHECK, 45),
        ("更新 Docker 端口映射、验证服务与安全回退", RECONFIGURE_APPLY, 110),
    ):
        for old, new in values.items():
            body = body.replace(old, new)
        output.append({"label": label, "script": body, "timeout": timeout})
    return output



def parse_status(raw: str) -> dict:
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if line.startswith("DOCKGE_") and "=" in line:
            key, value = line.split("=", 1)
            if key in values:
                raise ValueError("重复的 Dockge 状态字段")
            if key == "DOCKGE_PORT":
                if not value.isascii() or not value.isdecimal() or not 1024 <= int(value) <= 65535:
                    raise ValueError("Dockge 宿主机端口不合法")
            elif value not in {"yes", "no", "local", "public", "unverified"}:
                raise ValueError("Dockge 状态字段内容不合法")
            values[key] = value
    if values.get("DOCKGE_INSTALLED") == "no":
        return {"installed": False, "managed": False, "service": "absent", "access_mode": "unavailable", "port": PORT}
    if values.get("DOCKGE_INSTALLED") != "yes":
        raise ValueError("无法确认 Dockge 是否安装")
    if not {"DOCKGE_MANAGED", "DOCKGE_RUNNING", "DOCKGE_ACCESS"} <= values.keys():
        raise ValueError("Dockge 状态不完整")
    managed = values["DOCKGE_MANAGED"] == "yes"
    running = values["DOCKGE_RUNNING"] == "yes"
    mode = values["DOCKGE_ACCESS"]
    port = int(values.get("DOCKGE_PORT", PORT))
    return {
        "installed": True, "managed": managed, "service": "active" if running else "inactive",
        "access_mode": mode if managed and running and mode in {"local", "public"} else "unverified",
        "port": port,
    }



def local_access(host: dict, status: dict | None = None) -> dict:
    """Generate routes after live SSH status checked the real Docker binding."""
    from .executor import validate_host
    validate_host(host["hostname"], host["username"], int(host["port"]))
    status = status or {"port": PORT, "access_mode": "local"}
    port = validate_port(status["port"])
    mode = status["access_mode"]
    if mode not in {"local", "public"}:
        raise ValueError("Dockge Apps 监听未经验证")
    hostname = host["hostname"]
    ssh_port = int(host["port"])
    ssh_user = host["username"]
    result = {
        "local_url": f"http://127.0.0.1:{port}/",
        "ssh_tunnel": f"ssh -N -p {ssh_port} -L {port}:127.0.0.1:{port} {ssh_user}@{hostname}",
        "access_mode": mode, "port": port, "first_run_setup": True,
        "warning": "Dockge Apps 能操作 Docker Socket；公网直连仅适合管理员初始化完成并限定来源的环境。",
    }
    if mode == "public":
        ip = ipaddress.ip_address(hostname)
        if not isinstance(ip, ipaddress.IPv4Address) or not ip.is_global:
            raise ValueError("公网直连地址要求 VPS SSH 地址是可路由的公网 IPv4")
        result["direct_url"] = f"http://{ip}:{port}/"
    return result
