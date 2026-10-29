"""Audited UFW port actions. Never disable the entire firewall by default.

The cloud provider firewall cannot be modified without the provider's own
authorized API; local UFW rules are not a substitute for cloud firewall ACLs.
"""
from __future__ import annotations

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


def acme_ufw_script() -> str:
    """ACME port must remain allowed for scheduled HTTP-01 renewals."""
    return allow_port_script(80, "tcp").replace(
        "NetDeploy approved port", "NetDeploy ACME renewals"
    ).replace(
        "UFW_ALLOWED: 80/tcp (cloud security group must be checked separately)",
        "UFW_ACME_READY: 80/tcp allowed for issuance and scheduled renewals; cloud firewall still needs inbound TCP 80"
    )
