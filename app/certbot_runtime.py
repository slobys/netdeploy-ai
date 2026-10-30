"""Isolated Certbot for Let's Encrypt short-lived public IPv4 certificates.

The distro's apt Certbot 4.x can remain installed and continue renewing
unrelated certificates. NetDeploy IP certificates use a separate venv,
config/renewal tree and dedicated 4-hour systemd timer. Domain certificates
continue to use the existing OS Certbot installation.
"""
from __future__ import annotations

IP_CERTBOT_VERSION = "5.8.0"  # Published wheel, compatible with Debian 13/Python 3.13.
IP_CERTBOT_VENV = "/opt/netdeploy-certbot/venv"
IP_CERTBOT_BIN = f"{IP_CERTBOT_VENV}/bin/certbot"
IP_CONFIG_DIR = "/etc/netdeploy/letsencrypt"
IP_WORK_DIR = "/var/lib/netdeploy/certbot"
IP_LOG_DIR = "/var/log/netdeploy/certbot"
IP_RENEW_TIMER = "netdeploy-certbot-renew.timer"


def cert_root(mode: str) -> str:
    if mode == "ip":
        return IP_CONFIG_DIR
    if mode == "domain":
        return "/etc/letsencrypt"
    raise ValueError("Unknown certificate mode")


def renew_timer(mode: str) -> str:
    if mode == "ip":
        return IP_RENEW_TIMER
    if mode == "domain":
        return "certbot.timer"
    raise ValueError("Unknown certificate mode")


def certbot_command(mode: str) -> str:
    if mode == "ip":
        return (f"{IP_CERTBOT_BIN} --config-dir {IP_CONFIG_DIR} "
                f"--work-dir {IP_WORK_DIR} --logs-dir {IP_LOG_DIR}")
    if mode == "domain":
        return "certbot"
    raise ValueError("Unknown certificate mode")


# This whole script runs only with root after an explicit, reviewed SSH plan.
# Never removes OS certbot or rewrites certbot.timer, /usr/bin/certbot, or
# /etc/letsencrypt. A previous interrupted venv pip install can be resumed.
IP_BOOTSTRAP = r"""set -eu
test "$(id -u)" = 0
test -d /run/systemd/system || {
    echo 'ND_CERTBOT_SYSTEMD_REQUIRED: renewal needs systemd timers' >&2; exit 31;
}
export DEBIAN_FRONTEND=noninteractive
base='/opt/netdeploy-certbot'
venv='__VENV__'
client='__CLIENT__'
config='__CONFIG__'
work='__WORK__'
logs='__LOGS__'
service='/etc/systemd/system/netdeploy-certbot-renew.service'
timer='/etc/systemd/system/netdeploy-certbot-renew.timer'
# Refuse untrusted redirections. Do not overwrite a third-party venv or unit.
for target in "$base" "$venv" "$client" "$config" "$work" "$logs" "$service" "$timer"; do
    if test -L "$target"; then
        echo 'ND_CERTBOT_SYMLINK_CONFLICT: unmanaged symlink detected; no changes made' >&2; exit 35
    fi
done
if test -e "$base" && ! test -f "$base/.netdeploy-managed"; then
    echo 'ND_CERTBOT_DIR_CONFLICT: reserved /opt directory is not NetDeploy-managed' >&2; exit 35
fi
for unit in "$service" "$timer"; do
    if test -e "$unit" && ! grep -Fxq '# NetDeploy managed isolated IP Certbot' "$unit"; then
        echo 'ND_CERTBOT_UNIT_CONFLICT: existing renewal service not owned by NetDeploy' >&2; exit 35
    fi
done

# Only this venv's executable matters; the system's apt 4.0.0 does NOT count.
ready=no
if test -x "$client" && "$client" --help all 2>/dev/null | grep -Fq -- '--ip-address' &&
   "$client" --help all 2>/dev/null | grep -Fq -- '--preferred-profile'; then
    ready=yes
    echo 'NETDEPLOY_CERTBOT_READY: isolated IP-capable Certbot already present'
fi
if test "$ready" = no; then
    # Debian 13's apt certbot 4.0.0 is too old. Its package remains untouched.
    # APT lock waits for the system owner rather than forcibly deleting locks.
    if ! test -x "$venv/bin/python" || ! test -x "$venv/bin/pip"; then
        apt-get -o DPkg::Lock::Timeout=240 update -q
        apt-get -o DPkg::Lock::Timeout=240 install -y -q python3-venv ca-certificates
    fi
    install -d -m 755 "$base"
    touch "$base/.netdeploy-managed"
    chmod 600 "$base/.netdeploy-managed"
    if ! test -x "$venv/bin/pip"; then
        python3 -m venv "$venv" || {
            echo 'ND_CERTBOT_VENV_FAILED: Python venv unavailable (install python3-venv)' >&2; exit 31;
        }
    fi
    if ! test -x "$venv/bin/pip"; then
        echo 'ND_CERTBOT_PIP_MISSING: venv pip unavailable' >&2; exit 31
    fi
    # Official PyPI, fixed public Certbot release, only binary wheels.
    # Do not modify system Python, apt packages, or unrelated certificate trees.
    if ! env -u PIP_EXTRA_INDEX_URL PIP_CONFIG_FILE=/dev/null \
        "$venv/bin/pip" install --no-input --disable-pip-version-check \
        --only-binary=:all: --index-url https://pypi.org/simple \
        'certbot==__VERSION__'; then
        echo 'ND_CERTBOT_PYPI_FAILED: isolated Certbot download/install failed; retry after network fix' >&2; exit 31
    fi
fi
test -x "$client"
"$client" --help all | grep -Fq -- '--ip-address' || {
    echo 'ND_CERTBOT_IP_UNSUPPORTED: isolated Certbot does not support --ip-address' >&2; exit 31;
}
"$client" --help all | grep -Fq -- '--preferred-profile' || {
    echo 'ND_CERTBOT_PROFILE_UNSUPPORTED: isolated Certbot lacks shortlived profile' >&2; exit 31;
}

# Isolate state so apt 4.x's certbot.timer does not try to renew IP lineages.
for target in /etc/netdeploy /var/lib/netdeploy /var/log/netdeploy; do
    if test -L "$target"; then
        echo 'ND_CERTBOT_PARENT_SYMLINK: reserved parent directory is a symlink' >&2; exit 35
    fi
done
install -d -m 700 "$config" "$work" "$logs"
cat > "$service" <<'UNIT'
# NetDeploy managed isolated IP Certbot
[Unit]
Description=NetDeploy isolated IP certificate renewal (separate from OS Certbot)
Documentation=https://certbot.eff.org/

[Service]
Type=oneshot
ExecStart=__CLIENT__ renew --non-interactive --quiet --config-dir __CONFIG__ --work-dir __WORK__ --logs-dir __LOGS__
UNIT
cat > "$timer" <<'TIMER'
# NetDeploy managed isolated IP Certbot
[Unit]
Description=Renew NetDeploy short-lived IP certificates every four hours

[Timer]
OnCalendar=*-*-* 00,04,08,12,16,20:15:00
RandomizedDelaySec=15m
Persistent=true
AccuracySec=5m
Unit=netdeploy-certbot-renew.service

[Install]
WantedBy=timers.target
TIMER
chmod 644 "$service" "$timer"
systemctl daemon-reload
systemctl list-unit-files --no-legend netdeploy-certbot-renew.timer |
    grep -q '^netdeploy-certbot-renew[.]timer' || {
    echo 'ND_CERTBOT_TIMER_MISSING: isolated renewal timer not installed' >&2; exit 33;
}
echo 'NETDEPLOY_CERTBOT_READY: dedicated Certbot 5.3+ supports public IP certificates; separate renewal timer configured'
"""

for _key, _value in {
    "__VENV__": IP_CERTBOT_VENV, "__CLIENT__": IP_CERTBOT_BIN,
    "__CONFIG__": IP_CONFIG_DIR, "__WORK__": IP_WORK_DIR,
    "__LOGS__": IP_LOG_DIR, "__VERSION__": IP_CERTBOT_VERSION,
}.items():
    IP_BOOTSTRAP = IP_BOOTSTRAP.replace(_key, _value)
