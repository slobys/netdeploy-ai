"""Audited, deterministic deployment recipe registry.

Never interpret SKILL.md or model output as executable code. Only these reviewed
recipes may build commands for the remote SSH executor.
"""
from __future__ import annotations

import re
from typing import Any

CATALOG = {
    "3x-ui": {
        "name": "3X-UI", "subtitle": "Xray 可视化管理面板", "category": "面板",
        "icon": "layers", "deployment": "guided", "risk": "高",
        "docs": "https://docs.sanaei.dev/docs/guide/installation/",
        "summary": "官方提供交互式安装脚本和 Docker 部署。初版仅提供审核后的部署方案，不会直接执行未固定版本的远程脚本。",
        "requires": ["Linux VPS", "管理员权限", "管理面板 TLS 与访问控制方案"],
    },
    "sing-box": {
        "name": "sing-box", "subtitle": "通用网络代理内核", "category": "核心",
        "icon": "box", "deployment": "install", "risk": "中",
        "docs": "https://sing-box.sagernet.org/installation/package-manager/",
        "summary": "通过官方签名 APT 仓库安装内核；不自动生成对外监听配置，安装后仍需完成服务端配置。",
        "requires": ["Debian/Ubuntu", "x86_64/arm64", "root SSH", "APT 和 curl"],
    },
    "hysteria2": {
        "name": "Hysteria2", "subtitle": "基于 QUIC 的网络传输服务", "category": "协议",
        "icon": "zap", "deployment": "guided", "risk": "高",
        "docs": "https://hysteria.network/docs/getting-started/Server-Installation-Script/",
        "summary": "安装后仍需证书、认证和配置；初版展示完整先决条件，不自动执行下载脚本。",
        "requires": ["systemd Linux", "TLS 证书或可靠的签发方式", "认证配置", "开放 UDP 端口"],
    },
    "wg-easy": {
        "name": "wg-easy", "subtitle": "WireGuard + Web 管理界面", "category": "VPN",
        "icon": "shield", "deployment": "install", "risk": "高",
        "docs": "https://wg-easy.github.io/wg-easy/v15.4/examples/tutorials/basic-installation/",
        "summary": "使用 Docker Compose 部署 wg-easy v15，管理 Web 仅绑定 127.0.0.1，首次设置通过 SSH 隧道完成。",
        "requires": ["Linux amd64/arm64", "Docker Compose", "UDP 51820 未占用", "公网 IP/域名"],
    },
}

SUPPORTED_ARCHS = {"x86_64", "aarch64", "arm64"}

# Fixed scripts reviewed and maintained in source control. No model text here.
SINGBOX_STEPS = [
    {
        "label": "核实执行身份和系统包管理器",
        "script": "set -eu\ntest \"$(id -u)\" = 0\ncommand -v apt-get >/dev/null\ncommand -v curl >/dev/null\n",
        "timeout": 20,
    },
    {
        "label": "添加官方签名仓库并安装 sing-box",
        "script": """set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl
install -d -m 755 /etc/apt/keyrings
curl --proto '=https' --tlsv1.2 -fsSL https://sing-box.app/gpg.key -o /tmp/netdeploy-sagernet.asc
install -m 644 /tmp/netdeploy-sagernet.asc /etc/apt/keyrings/sagernet.asc
rm -f /tmp/netdeploy-sagernet.asc
cat > /etc/apt/sources.list.d/sagernet.sources <<'NETDEPLOY_APT'
Types: deb
URIs: https://deb.sagernet.org/
Suites: *
Components: *
Enabled: yes
Signed-By: /etc/apt/keyrings/sagernet.asc
NETDEPLOY_APT
apt-get update
apt-get install -y sing-box
""",
        "timeout": 300,
    },
    {
        "label": "核验已安装内核（不自动启动服务）",
        "script": "set -eu\ncommand -v sing-box\nsing-box version\n",
        "timeout": 30,
    },
]

WGEASY_STEPS = [
    {
        "label": "检查 Docker / Compose / root 权限和端口",
        "script": """set -eu
test "$(id -u)" = 0
docker info >/dev/null
docker compose version >/dev/null
if command -v ss >/dev/null && ss -Hlun | grep -Eq '(^|[[:space:]])[^[:space:]]*:51820([[:space:]]|$)'; then
  echo 'UDP 51820 seems occupied' >&2
  exit 16
fi
test ! -e /opt/netdeploy/wg-easy/compose.yaml
""",
        "timeout": 30,
    },
    {
        "label": "写入最小权限 Docker Compose 配置",
        "script": """set -eu
umask 077
mkdir -p /opt/netdeploy/wg-easy
cat > /opt/netdeploy/wg-easy/compose.yaml <<'NETDEPLOY_WG_EASY_COMPOSE'
services:
  wg-easy:
    image: ghcr.io/wg-easy/wg-easy:15
    container_name: netdeploy-wg-easy
    networks:
      wg:
        ipv4_address: 10.42.42.42
        ipv6_address: fdcc:ad94:bacf:61a3::2a
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    volumes:
      - wg_data:/etc/wireguard
      - /lib/modules:/lib/modules:ro
    ports:
      - '51820:51820/udp'
      - '127.0.0.1:51821:51821/tcp'
    sysctls:
      - net.ipv4.ip_forward=1
      - net.ipv4.conf.all.src_valid_mark=1
      - net.ipv6.conf.all.disable_ipv6=0
      - net.ipv6.conf.all.forwarding=1
      - net.ipv6.conf.default.forwarding=1
    restart: unless-stopped
volumes:
  wg_data:
networks:
  wg:
    driver: bridge
    enable_ipv6: true
    ipam:
      driver: default
      config:
        - subnet: 10.42.42.0/24
        - subnet: fdcc:ad94:bacf:61a3::/64
NETDEPLOY_WG_EASY_COMPOSE
docker compose -f /opt/netdeploy/wg-easy/compose.yaml config -q
""",
        "timeout": 30,
    },
    {
        "label": "启动 wg-easy 容器",
        "script": "set -eu\ndocker compose -f /opt/netdeploy/wg-easy/compose.yaml up -d\n",
        "timeout": 300,
    },
    {
        "label": "检查容器运行状态",
        "script": "set -eu\ntest \"$(docker inspect -f '{{.State.Running}}' netdeploy-wg-easy)\" = true\n",
        "timeout": 30,
    },
]


def compatibility(project: str, facts: dict[str, Any]) -> tuple[bool, list[str]]:
    issues: list[str] = []
    os_id = str(facts.get("OS_ID", "")).lower()
    arch = str(facts.get("ARCH", "")).lower()
    if str(facts.get("UID", "")) != "0":
        issues.append("第一阶段只允许以已验证的 root SSH 身份执行变更操作")
    if arch not in SUPPORTED_ARCHS:
        issues.append(f"当前 CPU 架构 {arch or '未知'} 尚未通过第一阶段验证")
    if project == "sing-box" and os_id not in {"debian", "ubuntu"}:
        issues.append("自动安装 sing-box 暂仅覆盖 Debian/Ubuntu APT 环境")
    if project == "wg-easy":
        if facts.get("DOCKER") != "yes":
            issues.append("未检测到可用的 Docker daemon")
        if facts.get("COMPOSE") != "yes":
            issues.append("未检测到 Docker Compose v2")
        if facts.get("UDP_51820") != "free":
            issues.append("UDP 51820 端口已占用，或无法可靠检测端口占用状态")
    if project == "hysteria2" and facts.get("SYSTEMD") != "yes":
        issues.append("Hysteria2 官方安装脚本需要 systemd")
    if not str(facts.get("FREE_KB", "")).isdigit():
        issues.append("无法确认根分区可用空间")
    elif int(facts["FREE_KB"]) < 400_000:
        issues.append("根分区可用空间低于 400 MB")
    return not issues, issues


def build_plan(project: str, facts: dict[str, Any]) -> dict[str, Any]:
    if project not in CATALOG:
        raise ValueError("不支持该项目")
    meta = CATALOG[project]
    eligible, issues = compatibility(project, facts)
    runnable = eligible and meta["deployment"] == "install"
    if meta["deployment"] == "guided":
        issues.append("此项目暂采用人工确认的引导模式；第一阶段不执行远程安装命令")
    steps = (SINGBOX_STEPS if project == "sing-box" else WGEASY_STEPS) if runnable else []
    return {
        "project": project,
        "name": meta["name"],
        "docs": meta["docs"],
        "risk": meta["risk"],
        "eligible": eligible,
        "executable": runnable,
        "issues": issues,
        "requires": meta["requires"],
        "steps": [dict(x) for x in steps],
        "warnings": {
            "sing-box": ["安装的是内核，不会自动配置对外监听或打开端口", "APT 仓库密钥来自官方 HTTPS 地址，初版尚未固定密钥指纹", "APT 变更不会自动回滚"],
            "wg-easy": ["需预先安装 Docker 且 Docker 网络不可与 10.42.42.0/24 冲突；不会自动修改防火墙", "Web 管理端只绑定 VPS 的 localhost，必须使用 SSH 隧道或安全反代", "容器镜像使用 v15 主版本标签，不是不可变 digest", "首次访问还需设置管理员账户及公网地址"],
            "3x-ui": ["需要固定上游版本及安装器校验后才能开放自动执行"],
            "hysteria2": ["需要单独实现 TLS 证书、身份认证和服务器配置"],
        }[project],
    }
