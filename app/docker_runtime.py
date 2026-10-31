"""Audited Docker Engine + Compose plugin prerequisites for Dockge Apps.

slobys/docker is the usability reference. It calls a remote curl|bash script
and downloads standalone x86_64 Compose, so NetDeploy instead uses Docker's
official signed Debian/Ubuntu APT repository and Docker Compose CLI plugin.
Never purge, remove, upgrade, or adopt an existing Docker installation.
"""
from __future__ import annotations

KEY_FPR = "9DC858229FC7DD38854AE2D88D81803C0EBFCD88"
PKGS = "docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin"

# Shared read-only guard for both SSH preflight and immediate pre-install checks.
PRISTINE = r"""netdeploy_docker_pristine() {
  command -v apt-get >/dev/null 2>&1 && command -v dpkg >/dev/null 2>&1 || return 1
  for program in docker dockerd containerd docker-compose; do
    if command -v "$program" >/dev/null 2>&1; then return 1; fi
  done
  for path in /var/run/docker.sock /run/docker.sock /var/lib/docker /etc/docker \
              /var/lib/containerd /etc/apt/sources.list.d/docker.sources \
              /etc/apt/sources.list.d/docker.list /etc/apt/keyrings/docker.asc \
              /etc/apt/keyrings/docker.gpg /etc/systemd/system/docker.service \
              /lib/systemd/system/docker.service /usr/lib/systemd/system/docker.service; do
    if test -e "$path" || test -L "$path"; then return 1; fi
  done
  if grep -Els 'download[.]docker[.]com' /etc/apt/sources.list \
       /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources 2>/dev/null | grep -q .; then
    return 1
  fi
  if command -v ip >/dev/null 2>&1 && ip link show docker0 >/dev/null 2>&1; then return 1; fi
  for pkg in docker.io docker-compose docker-compose-v2 docker-doc docker-buildx \
             podman-docker docker-ce docker-ce-cli docker-ce-rootless-extras \
             docker-compose-plugin docker-buildx-plugin containerd containerd.io runc; do
    if dpkg -s "$pkg" >/dev/null 2>&1; then return 1; fi
  done
  return 0
}
"""

OS_GUARD = r"""netdeploy_docker_supported_os() {
  test -r /etc/os-release && command -v dpkg >/dev/null || return 1
  . /etc/os-release
  case "$ID:$VERSION_CODENAME" in
    debian:bookworm|debian:trixie|ubuntu:jammy|ubuntu:noble|ubuntu:resolute|ubuntu:stonking) ;;
    *) return 1 ;;
  esac
  case "$(dpkg --print-architecture)" in amd64|arm64) ;; *) return 1 ;; esac
  test -d /run/systemd/system
}
"""

# Read-only fact. An incomplete installation deliberately reports "blocked".
ENV_CHECK = PRISTINE + r"""
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 &&
   docker compose version >/dev/null 2>&1; then
  echo DOCKER_SETUP=ready
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 &&
     ! docker compose version >/dev/null 2>&1 &&
     dpkg -s docker-ce 2>/dev/null | grep -Fxq 'Status: install ok installed' &&
     test -s /etc/apt/sources.list.d/docker.sources &&
     test -r /etc/apt/keyrings/docker.asc; then
  echo DOCKER_SETUP=compose
elif netdeploy_docker_pristine; then
  echo DOCKER_SETUP=clean
else
  echo DOCKER_SETUP=blocked
fi
"""

FRESH_CHECK = "set -eu\n" + PRISTINE + OS_GUARD + r"""
test "$(id -u)" = 0 || { echo 'ND_DOCKER_ROOT_REQUIRED' >&2; exit 41; }
netdeploy_docker_supported_os || {
  echo 'ND_DOCKER_OS_UNSUPPORTED: only official Debian/Ubuntu AMD64/ARM64 releases' >&2; exit 41;
}
netdeploy_docker_pristine || {
  echo 'ND_DOCKER_INSTALL_CONFLICT: existing Docker files/packages; no automatic replacement' >&2; exit 42;
}
test "$(df -Pk / | awk 'NR==2 {print $4}')" -ge 4000000 || {
  echo 'ND_DOCKER_DISK_LOW: at least 4 GB free for the combined deployment' >&2; exit 43;
}
echo 'ND_DOCKER_CLEAN: safe to prepare an official signed APT repository'
"""

APT_REPOSITORY = "set -eu\n" + OS_GUARD + r"""
test "$(id -u)" = 0
netdeploy_docker_supported_os || exit 41
export DEBIAN_FRONTEND=noninteractive LC_ALL=C
for path in /etc/apt/sources.list.d/docker.sources /etc/apt/sources.list.d/docker.list \
            /etc/apt/keyrings/docker.asc /etc/apt/keyrings/docker.gpg; do
  if test -e "$path" || test -L "$path"; then
    echo 'ND_DOCKER_APT_CONFLICT: existing Docker repository or key'; exit 44
  fi
done
apt-get -o DPkg::Lock::Timeout=240 update -q
apt-get -o DPkg::Lock::Timeout=240 install -y -q ca-certificates curl gnupg git
install -d -m 0755 /etc/apt/keyrings
key="$(mktemp /etc/apt/keyrings/.netdeploy-docker.XXXXXXXX)"
trap 'rm -f -- "$key"' EXIT
. /etc/os-release
curl --proto '=https' --tlsv1.2 -fsSL --max-time 45 \
  "https://download.docker.com/linux/$ID/gpg" -o "$key"
fingerprint="$(gpg --batch --with-colons --show-keys "$key" 2>/dev/null |
  awk -F: '$1 == "fpr" {print $10; exit}')"
test "$fingerprint" = '__KEY_FPR__' || {
  echo 'ND_DOCKER_SIGNING_KEY_MISMATCH: refusing to trust unsigned packages' >&2; exit 45
}
install -m 0644 "$key" /etc/apt/keyrings/docker.asc
suite="$VERSION_CODENAME"
cat > /etc/apt/sources.list.d/docker.sources <<NETDEPLOY_DOCKER_REPO
# NetDeploy-managed Docker stable repository
Types: deb
URIs: https://download.docker.com/linux/$ID
Suites: $suite
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
NETDEPLOY_DOCKER_REPO
chmod 644 /etc/apt/sources.list.d/docker.sources
apt-get -o DPkg::Lock::Timeout=240 update -q
echo 'ND_DOCKER_OFFICIAL_REPO_READY: verified signing fingerprint, source configured'
""".replace("__KEY_FPR__", KEY_FPR)

ENGINE_INSTALL = r"""set -eu
test "$(id -u)" = 0
test -r /etc/apt/sources.list.d/docker.sources &&
  grep -Fxq '# NetDeploy-managed Docker stable repository' /etc/apt/sources.list.d/docker.sources
test -r /etc/apt/keyrings/docker.asc
fingerprint="$(gpg --batch --with-colons --show-keys /etc/apt/keyrings/docker.asc 2>/dev/null |
  awk -F: '$1 == "fpr" {print $10; exit}')"
test "$fingerprint" = '__KEY_FPR__' || {
  echo 'ND_DOCKER_SIGNING_KEY_MISMATCH: package installation denied' >&2; exit 45;
}
export DEBIAN_FRONTEND=noninteractive LC_ALL=C
simulation="$(apt-get -s -o DPkg::Lock::Timeout=240 install __PACKAGES__)" || {
  echo 'ND_DOCKER_APT_SIMULATION_FAILED: inspect package conflicts' >&2; exit 46;
}
if printf '%s\n' "$simulation" | grep -Eq '^Remv[[:space:]]'; then
  echo 'ND_DOCKER_APT_REMOVAL_BLOCKED: package plan would remove existing packages' >&2; exit 46
fi
apt-get -o DPkg::Lock::Timeout=240 install -y -q __PACKAGES__
systemctl enable --now docker
echo 'ND_DOCKER_ENGINE_READY: official Docker Engine, Buildx, Compose CLI plugin installed'
""".replace("__KEY_FPR__", KEY_FPR).replace("__PACKAGES__", PKGS)

COMPOSE_CHECK = "set -eu\n" + OS_GUARD + r"""
test "$(id -u)" = 0
netdeploy_docker_supported_os || exit 47
docker info >/dev/null && test -S /var/run/docker.sock || exit 47
! docker compose version >/dev/null 2>&1 || exit 47
dpkg -s docker-ce 2>/dev/null | grep -Fxq 'Status: install ok installed' || {
  echo 'ND_DOCKER_EXISTING_ENGINE_UNSUPPORTED: requires official docker-ce' >&2; exit 47;
}
test -r /etc/apt/sources.list.d/docker.sources && test -r /etc/apt/keyrings/docker.asc
fingerprint="$(gpg --batch --with-colons --show-keys /etc/apt/keyrings/docker.asc 2>/dev/null |
  awk -F: '$1 == "fpr" {print $10; exit}')"
test "$fingerprint" = '__KEY_FPR__' || exit 47
echo 'ND_DOCKER_COMPOSE_PRECHECK_OK: existing Engine will be retained'
""".replace("__KEY_FPR__", KEY_FPR)

COMPOSE_INSTALL = r"""set -eu
test "$(id -u)" = 0
export DEBIAN_FRONTEND=noninteractive LC_ALL=C
apt-get -o DPkg::Lock::Timeout=240 update -q
simulation="$(apt-get -s -o DPkg::Lock::Timeout=240 install docker-compose-plugin docker-buildx-plugin git)" || exit 46
if printf '%s\n' "$simulation" | grep -Eq '^Remv[[:space:]]'; then
  echo 'ND_DOCKER_APT_REMOVAL_BLOCKED: no change to existing engine' >&2; exit 46
fi
if printf '%s\n' "$simulation" | grep -Eq '^Inst[[:space:]](docker-ce|docker-ce-cli|containerd[.]io|docker[.]io|containerd|runc)([[:space:]]|:)'; then
  echo 'ND_DOCKER_ENGINE_CHANGE_BLOCKED: preserving existing Docker packages' >&2; exit 46
fi
apt-get -o DPkg::Lock::Timeout=240 install -y -q docker-compose-plugin docker-buildx-plugin git
echo 'ND_DOCKER_COMPOSE_PLUGIN_INSTALLED: existing Docker Engine preserved'
"""

GIT_CHECK = r"""set -eu
test "$(id -u)" = 0
docker info >/dev/null && docker compose version >/dev/null
! command -v git >/dev/null 2>&1 || exit 47
command -v apt-get >/dev/null
test -d /run/systemd/system
echo 'ND_DOCKER_GIT_PRECHECK_OK'
"""
GIT_INSTALL = r"""set -eu
export DEBIAN_FRONTEND=noninteractive LC_ALL=C
apt-get -o DPkg::Lock::Timeout=240 update -q
simulation="$(apt-get -s -o DPkg::Lock::Timeout=240 install git)" || exit 46
if printf '%s\n' "$simulation" | grep -Eq '^Remv[[:space:]]'; then
  echo 'ND_DOCKER_APT_REMOVAL_BLOCKED: no changes to Docker packages' >&2; exit 46
fi
if printf '%s\n' "$simulation" | grep -Eq '^Inst[[:space:]](docker-ce|docker-ce-cli|containerd[.]io|docker[.]io|containerd|runc)([[:space:]]|:)'; then
  echo 'ND_DOCKER_ENGINE_CHANGE_BLOCKED: Git install would change existing Engine' >&2; exit 46
fi
apt-get -o DPkg::Lock::Timeout=240 install -y -q git
command -v git >/dev/null
echo 'ND_DOCKER_GIT_INSTALLED'
"""

VERIFY = r"""set -eu
test "$(id -u)" = 0
systemctl is-active --quiet docker
test -S /var/run/docker.sock
docker info >/dev/null
docker compose version
docker buildx version
command -v git >/dev/null
echo 'ND_DOCKER_VERIFIED: Docker Engine, Compose CLI plugin, Buildx and Git'
"""


def setup_mode(facts: dict) -> str:
    engine, compose = facts.get("DOCKER"), facts.get("COMPOSE")
    state = facts.get("DOCKER_SETUP")
    if engine == "yes" and compose == "yes" and state in {"ready", None}:
        return "git" if facts.get("GIT_AVAILABLE") == "no" else "ready"
    if engine == "yes" and compose == "no" and state == "compose":
        return "compose"
    if engine == "no" and compose == "no" and state == "clean":
        return "fresh"
    return "blocked"


def extra_steps(facts: dict) -> list[dict]:
    """Stages are immutable; execution happens only after explicit plan approval."""
    mode = setup_mode(facts)
    if mode == "fresh":
        return [
            {"label": "确认 VPS 没有旧 Docker 数据及软件包冲突", "script": FRESH_CHECK, "timeout": 50},
            {"label": "添加 Docker 官方签名软件源并准备 Git", "script": APT_REPOSITORY, "timeout": 600},
            {"label": "安装 Docker Engine、Buildx、Compose v2 插件", "script": ENGINE_INSTALL, "timeout": 900},
            {"label": "检查 Docker、Compose、Buildx 与 Git 是否正常", "script": VERIFY, "timeout": 65},
        ]
    if mode == "compose":
        return [
            {"label": "检查现有官方 Docker Engine 与签名软件源", "script": COMPOSE_CHECK, "timeout": 45},
            {"label": "为现有 Docker 安装 Compose v2 插件与 Git", "script": COMPOSE_INSTALL, "timeout": 600},
            {"label": "检查 Docker、Compose v2 和 Git", "script": VERIFY, "timeout": 65},
        ]
    if mode == "git":
        return [
            {"label": "检查 Docker 与 Compose 已可用，仅缺少 Git", "script": GIT_CHECK, "timeout": 40},
            {"label": "安装 Git 供 Dockge Apps 下载源码", "script": GIT_INSTALL, "timeout": 360},
            {"label": "检查 Docker、Compose v2 和 Git", "script": VERIFY, "timeout": 65},
        ]
    if mode == "ready":
        return []
    raise ValueError("Unknown or conflicting Docker installation; no automatic changes allowed")
