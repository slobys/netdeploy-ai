"""Dockge 1.5.0: audited Docker Compose deployment, localhost-only Web UI.

Dockge mounts /var/run/docker.sock (effectively root-level Docker control).
Never publish its HTTP management interface to a public IP. A stable version
tag is used, not a mutable :latest/:1; the tag is not an immutable digest.
"""
from __future__ import annotations

import re

VERSION = "1.5.0"
IMAGE = f"louislam/dockge:{VERSION}"
PORT = 5001
ROOT_DIR = "/opt/netdeploy/dockge"
STACKS_DIR = "/opt/stacks"
CONTAINER = "netdeploy-dockge"
MANAGED_MARK = "NetDeploy managed Dockge 1.5.0"

CHECK = r"""set -eu
test "$(id -u)" = 0 || { echo 'DOCKGE_ROOT_REQUIRED' >&2; exit 21; }
command -v docker >/dev/null || { echo 'DOCKGE_DOCKER_MISSING' >&2; exit 22; }
docker info >/dev/null || { echo 'DOCKGE_DOCKER_NOT_READY' >&2; exit 22; }
docker compose version >/dev/null || { echo 'DOCKGE_COMPOSE_V2_REQUIRED' >&2; exit 23; }
command -v ss >/dev/null || { echo 'DOCKGE_SS_REQUIRED' >&2; exit 24; }
command -v curl >/dev/null || { echo 'DOCKGE_CURL_REQUIRED' >&2; exit 24; }
test -S /var/run/docker.sock || { echo 'DOCKGE_SOCKET_UNAVAILABLE' >&2; exit 25; }
test "$(df -Pk / | awk 'NR==2 {print $4}')" -ge 1200000 || {
  echo 'DOCKGE_DISK_LOW: at least 1.2 GB free required for Docker image and data' >&2; exit 26;
}
case "$(uname -m)" in x86_64|aarch64|arm64) ;; *)
  echo 'DOCKGE_ARCH_UNSUPPORTED' >&2; exit 27;;
esac
for target in /opt/netdeploy /opt/netdeploy/dockge /opt/dockge /opt/stacks; do
  if test -L "$target"; then
    echo 'DOCKGE_UNSAFE_SYMLINK: refuse to follow pre-existing path' >&2; exit 28
  fi
done
# Do not adopt or overwrite an upstream/manual installation or partial setup.
if test -e /opt/dockge || test -e /opt/netdeploy/dockge; then
  echo 'DOCKGE_EXISTS: existing or interrupted deployment; inspect it first' >&2; exit 29
fi
if docker container inspect dockge >/dev/null 2>&1 ||
   docker container inspect netdeploy-dockge >/dev/null 2>&1 ||
   docker ps -a --format '{{.Image}}' | grep -Eq '(^|/)louislam/dockge(:|@)'; then
  echo 'DOCKGE_CONTAINER_EXISTS: refusing to replace an existing container' >&2; exit 29
fi
if ss -Hltn 'sport = :5001' | grep -q . ||
   test -n "$(docker ps -q --filter 'publish=5001/tcp')"; then
  echo 'DOCKGE_PORT_BUSY: TCP 5001 already in use' >&2; exit 30
fi
echo 'DOCKGE_PREFLIGHT_OK: Docker, Compose, free 5001/TCP, no existing Dockge'
"""

FETCH = r"""set -eu
test "$(id -u)" = 0
docker info >/dev/null
docker compose version >/dev/null
# Official Docker Hub image, fixed upstream stable release (not latest or nightly).
docker pull louislam/dockge:1.5.0
actual="$(docker image inspect -f '{{.Os}}/{{.Architecture}}' louislam/dockge:1.5.0)"
case "$(uname -m):$actual" in
  x86_64:linux/amd64|aarch64:linux/arm64|arm64:linux/arm64) ;;
  *) echo 'DOCKGE_IMAGE_ARCH_MISMATCH: wrong Docker image platform' >&2; exit 31 ;;
esac
echo 'DOCKGE_IMAGE_READY: pinned version 1.5.0 pulled; digest not guaranteed immutable'
"""

CONFIGURE = r"""set -eu
test "$(id -u)" = 0
umask 077
test ! -e /opt/netdeploy/dockge && test ! -L /opt/netdeploy/dockge || {
  echo 'DOCKGE_CONFIG_CONFLICT: directory already exists' >&2; exit 32;
}
test ! -L /opt/netdeploy && test ! -L /opt/stacks || {
  echo 'DOCKGE_UNSAFE_DIRECTORY: symlink denied' >&2; exit 32;
}
if test -e /opt/stacks && ! test -d /opt/stacks; then
  echo 'DOCKGE_STACKS_CONFLICT: /opt/stacks exists but is not a directory' >&2; exit 32;
fi
# Dockge may edit existing /opt/stacks stacks; NEVER move/delete stack content.
install -d -m 700 /opt/netdeploy/dockge
install -d -m 700 /opt/netdeploy/dockge/data
if test ! -d /opt/stacks; then install -d -m 750 /opt/stacks; fi
printf '%s\n' 'NetDeploy managed Dockge 1.5.0' > /opt/netdeploy/dockge/.netdeploy-managed
chmod 600 /opt/netdeploy/dockge/.netdeploy-managed
cat > /opt/netdeploy/dockge/compose.yaml <<'NETDEPLOY_DOCKGE_COMPOSE'
services:
  dockge:
    image: louislam/dockge:1.5.0
    container_name: netdeploy-dockge
    restart: unless-stopped
    # No public HTTP. Use SSH -L or an authenticated HTTPS reverse proxy.
    ports:
      - "127.0.0.1:5001:5001/tcp"
    volumes:
      # Docker socket grants root-equivalent control; never expose the UI.
      - /var/run/docker.sock:/var/run/docker.sock
      - /opt/netdeploy/dockge/data:/app/data
      # Same absolute path on both sides as required by upstream.
      - /opt/stacks:/opt/stacks
    environment:
      DOCKGE_STACKS_DIR: /opt/stacks
      DOCKGE_ENABLE_CONSOLE: "false"
NETDEPLOY_DOCKGE_COMPOSE
chmod 600 /opt/netdeploy/dockge/compose.yaml
docker compose -f /opt/netdeploy/dockge/compose.yaml config -q
echo 'DOCKGE_COMPOSE_READY: localhost-only 5001, console disabled'
"""

# Shared with a read-only status call. Inspect actual Docker port bindings,
# not only the Compose file (which can be changed after deployment).
BINDING_GUARD = r"""dockge_local_only() {
  portmap="$(docker container inspect -f '{{json .HostConfig.PortBindings}}' netdeploy-dockge 2>/dev/null)" || return 1
  test "$portmap" = '{"5001/tcp":[{"HostIp":"127.0.0.1","HostPort":"5001"}]}' || return 1
  docker container inspect -f '{{.Config.Image}}' netdeploy-dockge 2>/dev/null |
      grep -Fxq 'louislam/dockge:1.5.0' || return 1
}
"""

VERIFY = r"""set -eu
__BINDING_GUARD__
test "$(id -u)" = 0
test -f /opt/netdeploy/dockge/compose.yaml &&
  test ! -L /opt/netdeploy/dockge/compose.yaml
grep -Fxq 'NetDeploy managed Dockge 1.5.0' /opt/netdeploy/dockge/.netdeploy-managed
docker compose -f /opt/netdeploy/dockge/compose.yaml up -d --no-build
ready=no
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if test "$(docker container inspect -f '{{.State.Running}}' netdeploy-dockge 2>/dev/null)" = true &&
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
  # If actual port binding differs from the reviewed localhost-only mapping,
  # stop Dockge before reporting failure; never leave an unexpected public UI.
  if ! dockge_local_only; then
    docker compose -f /opt/netdeploy/dockge/compose.yaml stop >/dev/null 2>&1 || true
    echo 'DOCKGE_PORT_UNVERIFIED: Dockge stopped, unexpected bind or image' >&2
  fi
  echo 'DOCKGE_VERIFY_FAILED: check docker logs netdeploy-dockge and local 5001' >&2
  exit 33
fi
echo 'DOCKGE_LOCAL_READY: verified on 127.0.0.1:5001; open with SSH tunnel, create first admin in Dockge'
"""

STATUS = r"""set -eu
__BINDING_GUARD__
if test -e /opt/dockge || test -e /opt/netdeploy/dockge ||
   docker container inspect dockge >/dev/null 2>&1 ||
   docker container inspect netdeploy-dockge >/dev/null 2>&1 ||
   docker ps -a --format '{{.Image}}' 2>/dev/null | grep -Eq '(^|/)louislam/dockge(:|@)'; then
  echo 'DOCKGE_INSTALLED=yes'
else
  echo 'DOCKGE_INSTALLED=no'
  exit 0
fi
if test -f /opt/netdeploy/dockge/.netdeploy-managed &&
   test ! -L /opt/netdeploy/dockge/.netdeploy-managed &&
   grep -Fxq 'NetDeploy managed Dockge 1.5.0' /opt/netdeploy/dockge/.netdeploy-managed &&
   test -f /opt/netdeploy/dockge/compose.yaml &&
   test ! -L /opt/netdeploy/dockge/compose.yaml; then
  echo 'DOCKGE_MANAGED=yes'
else
  echo 'DOCKGE_MANAGED=no'
fi
if docker container inspect netdeploy-dockge >/dev/null 2>&1 &&
   test "$(docker container inspect -f '{{.State.Running}}' netdeploy-dockge)" = true; then
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
        {"label": "检查 Docker、Compose、5001 端口和已有 Dockge", "script": CHECK, "timeout": 45},
        {"label": "拉取官方 Dockge 1.5.0 多架构 Docker 镜像", "script": FETCH, "timeout": 360},
        {"label": "写入仅本机访问的受保护 Compose 配置", "script": CONFIGURE, "timeout": 40},
        {"label": "启动 Dockge、校验本机监听及 Web 响应", "script": VERIFY, "timeout": 180},
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
        "warning": "Dockge 可以通过 Docker Socket 管理主机容器；不要公开 5001/TCP。首次进入页面请设置管理员账户。",
    }
