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
