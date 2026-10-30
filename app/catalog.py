"""Audited, deterministic deployment recipe registry.

Never interpret SKILL.md or model output as executable code. Only these reviewed
recipes may build commands for the remote SSH executor.
"""
from __future__ import annotations

import re
from typing import Any

from .three_x_ui import DEFAULT_PORT, VERSION as XUI_VERSION, deployment_steps, validate_port
from .https_upgrade import identify, https_steps
from .s_ui import VERSION as SUI_VERSION, steps as sui_steps
from .sui_https import https_steps as sui_https_steps

CATALOG = {
    "3x-ui": {
        "name": "3X-UI", "subtitle": "Xray 可视化管理面板", "category": "面板",
        "icon": "layers", "deployment": "install", "risk": "高",
        "docs": "https://docs.sanaei.dev/docs/guide/installation/",
        "summary": "使用固定 v3.11.0 官方安装器及 SHA-256 校验，无 Docker 部署；面板仅监听本机，通过 SSH 隧道安全访问。",
        "requires": ["Ubuntu/Debian root VPS", "x86_64/arm64", "systemd 和 ss", "无已有 x-ui 安装", "面板仅本机监听，不自动打开公网端口"],
    },
    "3x-ui-https": {
        "name": "3X-UI HTTPS 直连", "subtitle": "为已安装面板签发 IP/域名证书",
        "category": "HTTPS", "icon": "lock", "deployment": "install",
        "internal": True, "risk": "高",
        "docs": "https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability",
        "summary": "对现有 3X-UI 开通公网可信 HTTPS；只有证书验证和续期配置成功才更改监听。",
        "requires": ["已完成并运行的 3X-UI", "域名 A 记录或公网 IPv4", "公网上 TCP 80 可访问", "支持 IP 证书的 Certbot", "云防火墙放行管理端口"],
    },
    "s-ui": {
        "name": "S-UI", "subtitle": "sing-box 可视化管理面板", "category": "面板",
        "icon": "layers", "deployment": "install", "risk": "高",
        "docs": "https://github.com/alireza0/s-ui",
        "summary": "官方 v1.6.6 固定发行包与随机管理凭据；签发公网 IP/域名证书并验收后启用 S-UI 原生 HTTPS。",
        "requires": ["Debian/Ubuntu root VPS", "x86_64/arm64", "systemd、ss、Python3 SQLite",
                     "2095/2096 端口未占用", "无已有 S-UI 安装", "HTTPS 需要公网 TCP 80 及云防火墙允许管理端口"],
    },
    "s-ui-https": {
        "name": "S-UI HTTPS 直连", "subtitle": "为已有 S-UI 面板配置公网 IP/域名证书",
        "category": "HTTPS", "icon": "lock", "deployment": "install", "internal": True,
        "risk": "高", "docs": "https://github.com/alireza0/s-ui",
        "summary": "只升级已安装的受管理 S-UI HTTPS，不覆盖软件或更改订阅端口。",
        "requires": ["受管理且本机监听的 S-UI", "公网 IPv4/域名", "TCP 80 ACME 入站", "Certbot 自动续期", "云安全组 TCP 2095"],
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
    if project in {"3x-ui", "3x-ui-https"}:
        if os_id not in {"debian", "ubuntu"}:
            issues.append("3X-UI 一键部署目前仅对 Ubuntu/Debian 开放")
        if arch not in {"x86_64", "aarch64"}:
            issues.append("3X-UI 目前仅支持 x86_64 / aarch64")
        if facts.get("SYSTEMD") != "yes":
            issues.append("3X-UI 需要可用的 systemd")
        if facts.get("SS_AVAILABLE") != "yes":
            issues.append("无法可靠检测面板 TCP 端口，请先安装 iproute2 并重新环境检测")
        expected = "yes" if project == "3x-ui-https" else "no"
        if facts.get("XUI_PRESENT") != expected:
            issues.append("HTTPS 升级要求已安装 x-ui，且已完成冲突检测" if project == "3x-ui-https" else "已存在 x-ui 安装，或尚未完成新版 x-ui 冲突检测；禁止覆盖")
    if project in {"s-ui", "s-ui-https"}:
        if os_id not in {"debian", "ubuntu"}:
            issues.append("S-UI 自动安装目前仅对 Debian/Ubuntu 开放")
        if arch not in {"x86_64", "aarch64", "arm64"}:
            issues.append("S-UI 目前只支持 x86_64/arm64")
        if facts.get("SYSTEMD") != "yes" or facts.get("SS_AVAILABLE") != "yes":
            issues.append("S-UI 安装需要 systemd 和 ss 端口检测")
        if facts.get("SUI_PRESENT") != ("yes" if project == "s-ui-https" else "no"):
            issues.append("S-UI HTTPS 需要已安装并完成冲突检测的面板" if project == "s-ui-https" else "已有 S-UI 或尚未完成冲突检查；禁止覆盖已安装程序")
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
    elif int(facts["FREE_KB"]) < (600_000 if project in {"3x-ui", "s-ui"} else 400_000):
        issues.append("根分区可用空间不足（至少需要 600 MB）" if project in {"3x-ui", "s-ui"} else "根分区可用空间低于 400 MB")
    return not issues, issues


def build_plan(project: str, facts: dict[str, Any], options: dict | None = None) -> dict[str, Any]:
    if project not in CATALOG:
        raise ValueError("不支持该项目")
    options = dict(options or {})
    if project == "3x-ui":
        if set(options) - {"panel_port", "access_mode", "tls_identity", "certificate_type", "ssh_ipv4"}:
            raise ValueError("3X-UI 部署选项包含未授权字段")
        port = validate_port(options.get("panel_port", DEFAULT_PORT))
        access_mode = options.get("access_mode", "local")
        if access_mode not in {"local", "https"}:
            raise ValueError("不支持的 3X-UI 访问方式")
        if access_mode == "https":
            mode, identity = identify(options.get("tls_identity", ""))
            if "certificate_type" in options and options["certificate_type"] != mode:
                raise ValueError("保存的证书类型与 IP/域名不一致，请重新生成部署方案")
            ssh_ip = options.get("ssh_ipv4")
            if ssh_ip is not None and (mode != "domain" or identify(ssh_ip)[0] != "ip"):
                raise ValueError("证书域名与 SSH 服务器公网 IPv4 不匹配")
            options = {"panel_port": port, "access_mode": "https", "tls_identity": identity,
                       "certificate_type": mode}
            if ssh_ip is not None:
                options["ssh_ipv4"] = ssh_ip
        else:
            if "tls_identity" in options or "certificate_type" in options or "ssh_ipv4" in options:
                raise ValueError("仅 HTTPS 模式可填写证书标识")
            options = {"panel_port": port}
    elif project in {"s-ui", "s-ui-https"}:
        allowed = {"access_mode", "tls_identity", "certificate_type", "ssh_ipv4"}
        if project == "s-ui-https":
            allowed.discard("access_mode")
            allowed.add("source_job_id")
        if set(options) - allowed:
            raise ValueError("S-UI HTTPS 部署含未授权参数")
        if project == "s-ui":
            mode = options.get("access_mode", "local")
            if mode not in {"https", "local"}:
                raise ValueError("S-UI 访问方式不合法")
            if mode == "local":
                if set(options) - {"access_mode"}:
                    raise ValueError("只有 S-UI HTTPS 模式允许证书选项")
                options = {"access_mode": "local"}
        else:
            mode = "https"
            if "source_job_id" in options:
                source = options["source_job_id"]
                if not isinstance(source, str) or not re.fullmatch(r"[a-f0-9]{16}", source):
                    raise ValueError("S-UI 原安装任务编号不合法")
        if mode == "https":
            tls_mode, identity = identify(options.get("tls_identity", ""))
            if "certificate_type" in options and options["certificate_type"] != tls_mode:
                raise ValueError("S-UI 证书类型与 IP/域名不一致")
            ssh_ip = options.get("ssh_ipv4")
            if ssh_ip is not None and (tls_mode != "domain" or identify(ssh_ip)[0] != "ip"):
                raise ValueError("S-UI 证书域名与 SSH IPv4 不匹配")
            normalized = {"access_mode": "https", "tls_identity": identity, "certificate_type": tls_mode}
            if ssh_ip is not None:
                normalized["ssh_ipv4"] = ssh_ip
            if project == "s-ui-https":
                normalized.pop("access_mode")
                if "source_job_id" in options:
                    normalized["source_job_id"] = options["source_job_id"]
            options = normalized
    elif project == "3x-ui-https":
        # Recovery after task history was cleared is allowed only when the API
        # independently verifies the *live* managed localhost installation.
        allowed = {"panel_port", "tls_identity", "source_job_id", "certificate_type", "ssh_ipv4"}
        if set(options) - allowed or not {"panel_port", "tls_identity"} <= set(options):
            raise ValueError("3X-UI HTTPS 升级选项不完整或包含未授权字段")
        mode, identity = identify(options["tls_identity"])
        if "certificate_type" in options and options["certificate_type"] != mode:
            raise ValueError("保存的证书类型与 IP/域名不一致，请重新生成部署方案")
        source = options.get("source_job_id")
        if source is not None and (not isinstance(source, str) or not re.fullmatch(r"[a-f0-9]{16}", source)):
            raise ValueError("3X-UI 原安装任务编号不合法")
        ssh_ip = options.get("ssh_ipv4")
        if ssh_ip is not None and (mode != "domain" or identify(ssh_ip)[0] != "ip"):
            raise ValueError("证书域名与 SSH 服务器公网 IPv4 不匹配")
        options = {"panel_port": validate_port(options["panel_port"]),
                   "tls_identity": identity, "certificate_type": mode}
        if ssh_ip is not None:
            options["ssh_ipv4"] = ssh_ip
        if source is not None:
            options["source_job_id"] = source
    elif options:
        raise ValueError("此项目暂不支持自定义部署选项")
    meta = CATALOG[project]
    eligible, issues = compatibility(project, facts)
    runnable = eligible and meta["deployment"] == "install"
    if meta["deployment"] == "guided":
        issues.append("此项目暂采用人工确认的引导模式；第一阶段不执行远程安装命令")
    if runnable and project == "3x-ui":
        steps = deployment_steps(options["panel_port"])
        if options.get("access_mode") == "https":
            steps = steps + https_steps(options["tls_identity"], options["panel_port"], options.get("ssh_ipv4"))
    elif runnable and project == "3x-ui-https":
        steps = https_steps(options["tls_identity"], options["panel_port"], options.get("ssh_ipv4"))
    elif runnable and project == "s-ui":
        steps = sui_steps(str(facts.get("ARCH", "")))
        if options.get("access_mode") == "https":
            steps += sui_https_steps(options["tls_identity"], options.get("ssh_ipv4"))
    elif runnable and project == "s-ui-https":
        steps = sui_https_steps(options["tls_identity"], options.get("ssh_ipv4"))
    elif runnable and project == "sing-box":
        steps = SINGBOX_STEPS
    elif runnable and project == "wg-easy":
        steps = WGEASY_STEPS
    else:
        steps = []
    return {
        "project": project,
        "name": meta["name"],
        "docs": meta["docs"],
        "risk": meta["risk"],
        "eligible": eligible,
        "executable": runnable,
        "options": options,
        "issues": issues,
        "requires": meta["requires"],
        "steps": [dict(x) for x in steps],
        "warnings": {
            "s-ui": [
                f"从上游 GitHub Releases 固定下载 {SUI_VERSION} 的 amd64/arm64 发行包，并通过已固定 SHA-256 校验，不运行在线最新安装脚本",
                "首次初始化随机管理员账号、强密码和 Web 路径；敏感信息仅保存在 VPS 受权限保护的文件中，部署日志不输出密码",
                "先保持管理 2095 与订阅 2096 都只监听 VPS 本机；HTTPS 通过后才将管理端口切到公网 2095/TCP，订阅 2096 始终不开放",
                "HTTPS 模式按域名/公网 IPv4 自动申请证书：IP 使用独立 Certbot 5.8.0 虚拟环境与专用续期服务（不覆盖系统 Certbot），需公网 TCP 80 验证",
                "证书签发或 HTTPS 验收失败时保留/恢复 S-UI 本机监听，不回退成公网明文 HTTP；云安全组需手动放行管理端口",
                "不会覆盖已有 S-UI；如果失败可能留下需要人工检查的部分目录/服务，不应直接重复执行安装",
            ],
            "s-ui-https": ["仅为已安装且本机运行的受管理 S-UI 签发 IP/域名证书，不重复下载或安装面板", "先验证公网 IPv4 / DNS A 与 TCP 80 可达；IP 证书自动使用独立 Certbot 5.8.0 + 续期定时器，域名使用系统 Certbot",  "HTTPS 配置或验证失败自动恢复 127.0.0.1:2095；订阅 2096 始终本机访问", "需要云厂商手动设置 TCP 2095 入站管理 IP 白名单"],
            "sing-box": ["安装的是内核，不会自动配置对外监听或打开端口", "APT 仓库密钥来自官方 HTTPS 地址，初版尚未固定密钥指纹", "APT 变更不会自动回滚"],
            "wg-easy": ["需预先安装 Docker 且 Docker 网络不可与 10.42.42.0/24 冲突；不会自动修改防火墙", "Web 管理端只绑定 VPS 的 localhost，必须使用 SSH 隧道或安全反代", "容器镜像使用 v15 主版本标签，不是不可变 digest", "首次访问还需设置管理员账户及公网地址"],
            "3x-ui": [f"固定官方 {XUI_VERSION} 安装器 SHA-256 后执行，二进制由上游发布的 .sha256 校验；安装依赖可能需要联网和更改 APT 包", "自动生成账户、密码和随机 Web 路径；只在安装后明确点击查看时读取，不存入 NetDeploy 数据库或任务日志", "先将面板绑定本机 127.0.0.1；选择 HTTPS 时自动按公网 IPv4 / 域名签发证书并验证，成功后才开放公网 HTTPS，失败不开放明文 HTTP", "不会自动覆盖已有安装；失败可能留下部分文件，需要人工检查，不能盲目重试"],
            "3x-ui-https": ["公网 TCP 80 必须允许 Let’s Encrypt HTTP-01 验证（本机空闲不代表云安全组开放）；域名证书要求 DNS A 正确，公网 IP 证书使用 shortlived", "IP 证书有效期约 160 小时，必须保持 netdeploy-certbot-renew.timer 活跃（独立续期）；域名证书使用系统 certbot.timer；失败不开放公网面板",  "公网 HTTPS 管理面板属于高敏感服务，请启用强密码、双因素认证和云防火墙 IP 白名单"],
            "hysteria2": ["需要单独实现 TLS 证书、身份认证和服务器配置"],
        }[project],
    }
