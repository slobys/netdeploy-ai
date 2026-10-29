"""Audited UFW port actions. Never disable the entire firewall by default.

The cloud provider firewall cannot be modified without the provider's own
authorized API; local UFW rules are not a substitute for cloud firewall ACLs.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, StrictInt


class PortRule(BaseModel):
    port: StrictInt = Field(ge=1, le=65535)
    protocol: Literal["tcp", "udp"] = "tcp"
    confirmation: bool = False


class FirewallToggle(BaseModel):
    mode: Literal["disable", "enable"]
    confirmed_risk: bool = False


def firewall_toggle_script(mode: str, ssh_port: int) -> str:
    """Explicit operator action for this VPS's UFW only.

    Disabling intentionally removes the VPS's *host-level* traffic filter, but
    retains UFW rules for re-enabling. Re-enabling first allows the pinned SSH
    port, protecting access when the default incoming policy is deny.
    """
    if mode not in ("disable", "enable"):
        raise ValueError("不支持的 UFW 操作")
    if type(ssh_port) is not int or not 1 <= ssh_port <= 65535:
        raise ValueError("SSH 端口必须是 1–65535 的整数")
    common = """set -eu
test "$(id -u)" = 0
command -v ufw >/dev/null 2>&1 || {
    echo 'UFW_UNAVAILABLE: UFW is not installed; nothing changed' >&2
    exit 71
}
status="$(LC_ALL=C ufw status | sed -n '1p')"
case "$status" in
    'Status: active'|'Status: inactive') ;;
    *) echo 'UFW_STATUS_UNKNOWN: refused an unknown firewall state' >&2; exit 72 ;;
esac
"""
    if mode == "disable":
        return common + """if [ "$status" = 'Status: inactive' ]; then
    echo 'UFW_ALREADY_DISABLED: UFW is already inactive'
    exit 0
fi
# Preserves rules; does not uninstall UFW or change cloud security groups.
ufw --force disable >/dev/null
LC_ALL=C ufw status | grep -Fxq 'Status: inactive' || {
    echo 'UFW_DISABLE_UNVERIFIED: could not confirm disabled state' >&2; exit 73;
}
echo 'UFW_DISABLED: entire VPS host firewall is inactive; cloud ACLs are unchanged'
"""
    return common + f"""if [ "$status" = 'Status: active' ]; then
    echo 'UFW_ALREADY_ENABLED: UFW is already active'
    exit 0
fi
# Explicitly allow the verified SSH port BEFORE enabling a deny-by-default
# firewall. Never remove existing rules or reset the UFW configuration.
ufw allow {ssh_port}/tcp comment 'NetDeploy SSH safeguard' >/dev/null
ufw --force enable >/dev/null
LC_ALL=C ufw status | grep -Fxq 'Status: active' || {{
    echo 'UFW_ENABLE_UNVERIFIED: could not confirm enabled state' >&2; exit 74;
}}
echo 'UFW_ENABLED: host firewall is active; SSH TCP {ssh_port} explicitly allowed'
"""

STATUS_SCRIPT = """set -eu
test "$(id -u)" = 0
if ! command -v ufw >/dev/null 2>&1; then
    echo 'FIREWALL=unavailable'
elif LC_ALL=C ufw status | grep -Fxq 'Status: inactive'; then
    echo 'FIREWALL=inactive'
elif LC_ALL=C ufw status | grep -Fxq 'Status: active'; then
    echo 'FIREWALL=active'
    LC_ALL=C ufw status | sed -n '1,55p'
else
    echo 'FIREWALL=unknown'
fi
"""


def allow_port_script(port: int, protocol: str) -> str:
    """Return only source-defined commands with strictly typed parameters."""
    if type(port) is not int or not (1 <= port <= 65535):
        raise ValueError("端口必须为 1–65535 的整数")
    if protocol not in ("tcp", "udp"):
        raise ValueError("协议只能是 tcp 或 udp")
    return f"""set -eu
test "$(id -u)" = 0
if ! command -v ufw >/dev/null 2>&1; then
    echo 'UFW_UNAVAILABLE: no supported UFW firewall to modify'
elif LC_ALL=C ufw status | grep -Fxq 'Status: inactive'; then
    echo 'UFW_INACTIVE: system firewall inactive; no rule needed'
else
    LC_ALL=C ufw status | grep -Fxq 'Status: active' || {{
        echo 'UFW_STATUS_UNKNOWN: refusing to modify unknown firewall state' >&2
        exit 71
    }}
    # Repeating an already-added allow rule is idempotent. Never disable or
    # reset UFW and never add broad all-ports access.
    ufw allow {port}/{protocol} comment 'NetDeploy approved port' >/dev/null
    echo 'UFW_ALLOWED: {port}/{protocol} (cloud security group must be checked separately)'
fi
"""

# Batch operations are capped to bound SSH execution time and accidental
# exposure. Every field is strictly typed; arbitrary shell is never accepted.
class FirewallPort(BaseModel):
    port: StrictInt = Field(ge=1, le=65535)
    protocol: Literal["tcp", "udp"] = "tcp"


class FirewallBatch(BaseModel):
    rules: list[FirewallPort] = Field(min_length=1, max_length=20)
    confirmation: bool = False


def allow_ports_script(rules: list[FirewallPort]) -> str:
    """Generate a single audited SSH command with per-rule result markers.

    Validate the *whole* request before changing anything. A failure to
    allow one rule does not hide the outcome of other rules; no unsafe
    attempt is made to roll back successfully applied firewall rules.
    """
    if not rules or len(rules) > 20:
        raise ValueError("每次只能放行 1–20 个端口")
    seen: set[tuple[int, str]] = set()
    ordered: list[tuple[int, str]] = []
    for item in rules:
        if not isinstance(item, FirewallPort):
            raise ValueError("端口规则必须包含已校验的端口和协议")
        key = (item.port, item.protocol)
        if key in seen:
            raise ValueError(f"重复规则：{item.port}/{item.protocol}，请移除重复端口")
        seen.add(key)
        ordered.append(key)
        # Defense-in-depth (Pydantic StrictInt and Literal also validate).
        allow_port_script(item.port, item.protocol)
    body = [
        "set -eu",
        'test "$(id -u)" = 0',
        'if ! command -v ufw >/dev/null 2>&1; then',
        "    echo 'ND_FIREWALL=unavailable'",
    ]
    for port, protocol in ordered:
        body.append(f"    echo 'ND_RULE {port}/{protocol} skipped'")
    body.extend([
        "elif LC_ALL=C ufw status | grep -Fxq 'Status: inactive'; then",
        "    echo 'ND_FIREWALL=inactive'",
    ])
    for port, protocol in ordered:
        body.append(f"    echo 'ND_RULE {port}/{protocol} skipped'")
    body.extend([
        "elif LC_ALL=C ufw status | grep -Fxq 'Status: active'; then",
        "    echo 'ND_FIREWALL=active'",
    ])
    for item in rules:
        port, protocol = item.port, item.protocol
        body.extend([
            f"    if ufw allow {port}/{protocol} comment 'NetDeploy approved port' >/dev/null 2>&1; then",
            f"        echo 'ND_RULE {port}/{protocol} allowed'",
            "    else",
            f"        echo 'ND_RULE {port}/{protocol} failed'",
            "    fi",
        ])
    body.extend([
        "else",
        "    echo 'UFW_STATUS_UNKNOWN: refusing to modify unknown firewall state' >&2",
        "    exit 71",
        "fi",
    ])
    return "\n".join(body) + "\n"


def parse_firewall_batch_output(raw: str, rules: list[FirewallPort]) -> dict:
    """Refuse to treat unverified/partial remote responses as full success."""
    lines = raw.splitlines()
    if not lines or lines[0] not in {
        "ND_FIREWALL=active", "ND_FIREWALL=inactive", "ND_FIREWALL=unavailable"
    }:
        raise ValueError("远端防火墙状态无法核验，部分端口可能已经修改，请检查 VPS")
    mode = lines[0].split("=", 1)[1]
    results = []
    expected = [f"{item.port}/{item.protocol}" for item in rules]
    seen = {}
    for line in lines[1:]:
        match = re.fullmatch(r"ND_RULE (\d{1,5})/(tcp|udp) (allowed|failed|skipped)", line)
        if not match:
            raise ValueError("远端放行结果无法完整核对，请检查 VPS 实际 UFW 规则")
        key, status = f"{int(match[1])}/{match[2]}", match[3]
        if key in seen or key not in expected:
            raise ValueError("远端放行结果与已批准端口不一致，请检查 VPS")
        seen[key] = status
    if set(seen) != set(expected):
        raise ValueError("远端未返回全部端口结果，请人工核对实际 UFW 规则")
    if (mode == "active" and any(x == "skipped" for x in seen.values())) or (
        mode != "active" and any(x != "skipped" for x in seen.values())
    ):
        raise ValueError("远端 UFW 状态与返回的端口结果不一致，请人工核对")
    for item in rules:
        results.append({
            "port": item.port, "protocol": item.protocol,
            "status": seen[f"{item.port}/{item.protocol}"],
        })
    allowed = sum(x["status"] == "allowed" for x in results)
    failed = sum(x["status"] == "failed" for x in results)
    skipped = len(results) - allowed - failed
    return {
        "mode": mode, "results": results,
        "allowed": allowed, "failed": failed,
        "skipped": skipped, "partial": failed > 0,
    }


def acme_ufw_script() -> str:
    """ACME port must remain allowed for scheduled HTTP-01 renewals."""
    return allow_port_script(80, "tcp").replace(
        "NetDeploy approved port", "NetDeploy ACME renewals"
    ).replace(
        "UFW_ALLOWED: 80/tcp (cloud security group must be checked separately)",
        "UFW_ACME_READY: 80/tcp allowed for issuance and scheduled renewals; cloud firewall still needs inbound TCP 80"
    )
