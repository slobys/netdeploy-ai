"""Dockge Apps: reviewed source-built fork deployment, localhost-only Web UI.

The user's fork has no published Docker release image. Build the audited
Dockerfile.apps from an exact Git commit instead of pulling upstream Dockge.
Existing upstream/manual installations and stack data are never overwritten.
"""
from __future__ import annotations

VERSION = "1.5.0-apps.1"
SOURCE_REPO = "https://github.com/slobys/dockge-apps.git"
SOURCE_SHA = "66aec693a974bd980f632f643586deab16932531"
IMAGE = f"netdeploy/dockge-apps:{SOURCE_SHA[:12]}"
PORT = 5001
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
if ss -Hltn 'sport = :5001' | grep -q . ||
   test -n "$(docker ps -q --filter 'publish=5001/tcp')"; then
  echo 'DOCKGE_PORT_BUSY: TCP 5001 already in use' >&2; exit 30
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
      - "127.0.0.1:5001:5001/tcp"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /opt/netdeploy/dockge/data:/app/data
      - /opt/stacks:/opt/stacks
    environment:
      DOCKGE_STACKS_DIR: /opt/stacks
      DOCKGE_ENABLE_CONSOLE: "false"
NETDEPLOY_DOCKGE_APPS_COMPOSE
chmod 600 "$root/compose.yaml"
docker compose -f "$root/compose.yaml" config -q
# Build the actual fork source, NOT the upstream louislam/dockge application.
# Dockerfile.apps itself uses an upstream base image (mutable), disclosed in docs.
docker compose -f "$root/compose.yaml" build --pull
actual="$(docker image inspect -f '{{.Os}}/{{.Architecture}}' netdeploy/dockge-apps:66aec693a974)"
case "$(uname -m):$actual" in
  x86_64:linux/amd64|aarch64:linux/arm64|arm64:linux/arm64) ;;
  *) echo 'DOCKGE_FORK_IMAGE_ARCH_MISMATCH' >&2; exit 32 ;;
esac
echo 'DOCKGE_APPS_BUILD_READY: source-built fork, localhost 5001, Apps Center enabled'
"""


# Real Docker HostConfig binding and the exact locally built image are required.
BINDING_GUARD = r"""dockge_local_only() {
  portmap="$(docker container inspect -f '{{json .HostConfig.PortBindings}}' netdeploy-dockge-apps 2>/dev/null)" || return 1
  test "$portmap" = '{"5001/tcp":[{"HostIp":"127.0.0.1","HostPort":"5001"}]}' || return 1
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
      'http://127.0.0.1:5001/' 2>/dev/null)" || response=000
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
echo 'DOCKGE_APPS_LOCAL_READY: source-built Dockge Apps running on localhost 5001'
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
  code="$(curl -4 --noproxy '*' --silent --output /dev/null --write-out '%{http_code}' --max-time 6 \
    'http://127.0.0.1:5001/' 2>/dev/null)" || code=000
  case "$code" in
    200|301|302|303|307|308|401|403) echo 'DOCKGE_ACCESS=local' ;;
    *) echo 'DOCKGE_ACCESS=unverified' ;;
  esac
else
  echo 'DOCKGE_ACCESS=unverified'
fi
"""


for _name in ("VERIFY", "STATUS"):
    globals()[_name] = globals()[_name].replace("__BINDING_GUARD__", BINDING_GUARD)


def steps() -> list[dict]:
    return [
        {"label": "检查 Docker、Compose、Git、5001 端口及已有 Dockge", "script": CHECK, "timeout": 45},
        {"label": "从 GitHub 下载并校验 Dockge Apps 固定源码版本", "script": FETCH, "timeout": 240},
        {"label": "构建 Dockge Apps 镜像并生成本机受保护 Compose", "script": CONFIGURE, "timeout": 1200},
        {"label": "启动 Dockge Apps、验证 Docker 端口和本机 Web", "script": VERIFY, "timeout": 180},
    ]


def parse_status(raw: str) -> dict:
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if line.startswith("DOCKGE_") and "=" in line:
            key, value = line.split("=", 1)
            if key in values:
                raise ValueError("重复的 Dockge 状态字段")
            if value not in {"yes", "no", "local", "unverified"}:
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
    local = values["DOCKGE_ACCESS"] == "local"
    return {
        "installed": True, "managed": managed, "service": "active" if running else "inactive",
        "access_mode": "local" if managed and running and local else "unverified",
        "port": PORT,
    }


def local_access(host: dict) -> dict:
    """Only call after successful status verification via pinned SSH identity."""
    from .executor import validate_host
    validate_host(host["hostname"], host["username"], int(host["port"]))
    ssh_port = int(host["port"])
    hostname = host["hostname"]
    user = host["username"]
    return {
        "local_url": f"http://127.0.0.1:{PORT}/",
        "ssh_tunnel": f"ssh -N -p {ssh_port} -L {PORT}:127.0.0.1:{PORT} {user}@{hostname}",
        "access_mode": "local",
        "port": PORT,
        "first_run_setup": True,
        "warning": "Dockge Apps 可以通过 Docker Socket 管理主机容器；不要公开 5001/TCP。首次进入页面请设置管理员账户。",
    }
