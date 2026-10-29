"""Pinned, noninteractive S-UI v1.6.6 installer for verified Linux VPS.

Do NOT run upstream's interactive install.sh: it downloads "latest", may
replace sing-box and defaults to a publicly bound plaintext web panel.
NetDeploy uses an immutable GitHub release asset with upstream SHA-256,
creates random credentials and loopback-only listeners *before* starting.
"""
from __future__ import annotations

import re

VERSION = "v1.6.6"
PORT = 2095
SUB_PORT = 2096
ARTIFACTS = {
    "x86_64": ("amd64", "6abe5756cdc1c95dfbcc2042d6f3239b230f91946f11ab0e23eaa78b42ab37e5"),
    "aarch64": ("arm64", "d5b644dc138ee59ea7825c6e323e3757ea400147e930757df208a4f126a78aea"),
    "arm64": ("arm64", "d5b644dc138ee59ea7825c6e323e3757ea400147e930757df208a4f126a78aea"),
}
INSTALL_ROOT = "/usr/local/s-ui"
RESULT_FILE = "/var/lib/netdeploy/s-ui/install-result.env"

SERVICE_UNIT = """[Unit]
Description=NetDeploy s-ui Service (pinned 1.6.6)
After=network.target
Wants=network.target

[Service]
Type=simple
WorkingDirectory=/usr/local/s-ui
ExecStart=/usr/local/s-ui/sui
Restart=on-failure
RestartSec=10s
LimitNOFILE=1048576
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=read-only

[Install]
WantedBy=multi-user.target
"""

PRECHECK = r"""set -eu
test "$(id -u)" = 0
. /etc/os-release
case "$ID" in ubuntu|debian) ;; *) echo 'SUI_UNSUPPORTED_OS: Debian/Ubuntu required' >&2; exit 11;; esac
case "$(uname -m)" in __ARCH__) ;; *) echo 'SUI_UNSUPPORTED_ARCH' >&2; exit 12;; esac
command -v systemctl >/dev/null
test -d /run/systemd/system
command -v ss >/dev/null
test ! -e /usr/local/s-ui
test ! -e /etc/s-ui
test ! -e /etc/systemd/system/s-ui.service
test ! -e /usr/bin/s-ui
test ! -e /var/lib/netdeploy/s-ui/install-result.env
if systemctl list-unit-files --no-legend s-ui.service 2>/dev/null | grep -q '^s-ui[.]service'; then
    echo 'SUI_ALREADY_INSTALLED: refusing to overwrite an existing service' >&2; exit 13
fi
for port in 2095 2096; do
    if ss -Hltn "sport = :$port" | grep -q .; then
        echo "SUI_PORT_IN_USE: TCP $port is occupied; refusing to overwrite" >&2
        exit 14
    fi
done
test "$(df -Pk / | awk 'NR==2 {print $4}')" -ge 600000
echo 'SUI_PREFLIGHT_READY: no existing installation and localhost ports available'
"""

DEPS = r"""set -eu
test "$(id -u)" = 0
if command -v curl >/dev/null && command -v python3 >/dev/null &&
   command -v openssl >/dev/null && command -v sha256sum >/dev/null &&
   command -v tar >/dev/null && test -s /etc/ssl/certs/ca-certificates.crt; then
    python3 -c 'import sqlite3,tarfile,hashlib' >/dev/null
    echo 'SUI_DEPENDENCIES_READY: no package changes needed'
else
    export DEBIAN_FRONTEND=noninteractive
    apt-get -o DPkg::Lock::Timeout=240 update -q
    apt-get -o DPkg::Lock::Timeout=240 install -y -q curl python3 openssl tar ca-certificates
    python3 -c 'import sqlite3,tarfile,hashlib' >/dev/null
    echo 'SUI_DEPENDENCIES_READY'
fi
"""

DOWNLOAD = r"""set -eu
umask 077
install -d -m 700 /var/lib/netdeploy/s-ui
file='/var/lib/netdeploy/s-ui/__ASSET__'
temp="$(mktemp '/var/lib/netdeploy/s-ui/.download.XXXXXXXX')"
trap 'rm -f "$temp"' EXIT
curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error \
    --retry 3 --connect-timeout 15 --max-time 240 \
    'https://github.com/alireza0/s-ui/releases/download/__VERSION__/__ASSET__' -o "$temp"
printf '%s  %s\n' '__DIGEST__' "$temp" | sha256sum -c - >/dev/null
test "$(stat -c %s "$temp")" -ge 1000000
# Confirm expected archive root and reject unsafe tar members (links and
# traversal included) before placing ANY files in /usr/local.
python3 - "$temp" <<'PY'
import pathlib, sys, tarfile
p = pathlib.Path(sys.argv[1])
with tarfile.open(p, "r:gz") as tf:
    entries = tf.getmembers()
    if not entries or len(entries) > 4096:
        raise SystemExit("SUI_ARCHIVE_INVALID: member count")
    names = set()
    total = 0
    for item in entries:
        parts = pathlib.PurePosixPath(item.name).parts
        if not parts or parts[0] != "s-ui" or any(
            x in {"", ".", ".."} for x in parts
        ) or item.name.startswith("/") or not (item.isdir() or item.isfile()):
            raise SystemExit("SUI_ARCHIVE_UNSAFE: unexpected paths or links")
        if item.name in names:
            raise SystemExit("SUI_ARCHIVE_DUPLICATE: refusing overwritten entries")
        names.add(item.name)
        total += item.size
    if "s-ui/sui" not in names or total > 400_000_000:
        raise SystemExit("SUI_ARCHIVE_INVALID: expected binary or size")
PY
install -m 600 "$temp" "$file"
echo 'SUI_ASSET_VERIFIED: official pinned release and SHA-256 checked'
"""

CONFIGURE = r"""set -eu
umask 077
test "$(id -u)" = 0
test ! -e /usr/local/s-ui
test ! -e /etc/systemd/system/s-ui.service
archive='/var/lib/netdeploy/s-ui/__ASSET__'
test -s "$archive"
printf '%s  %s\n' '__DIGEST__' "$archive" | sha256sum -c - >/dev/null
stage="$(mktemp -d '/var/lib/netdeploy/s-ui/.unpack.XXXXXXXX')"
trap 'rm -rf "$stage"' EXIT
# Extract regular files only; do not follow archive symlinks or paths.
python3 - "$archive" "$stage" <<'PY'
import os, pathlib, sys, tarfile
archive, root = sys.argv[1:]
base = pathlib.Path(root)
with tarfile.open(archive, "r:gz") as tf:
    members = tf.getmembers()
    if not members or len(members) > 4096:
        raise SystemExit("SUI_ARCHIVE_INVALID")
    seen = set()
    total = 0
    for member in members:
        parts = pathlib.PurePosixPath(member.name).parts
        if not parts or parts[0] != "s-ui" or member.name.startswith("/") or any(
            x in {"", ".", ".."} for x in parts
        ) or not (member.isdir() or member.isfile()) or member.name in seen:
            raise SystemExit("SUI_ARCHIVE_UNSAFE")
        seen.add(member.name)
        total += member.size
    if "s-ui/sui" not in seen or total > 400_000_000:
        raise SystemExit("SUI_ARCHIVE_INVALID")
    for member in members:
        dest = base.joinpath(*pathlib.PurePosixPath(member.name).parts)
        if member.isdir():
            dest.mkdir(parents=True, exist_ok=True, mode=0o700)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            src = tf.extractfile(member)
            if src is None:
                raise SystemExit("SUI_ARCHIVE_UNREADABLE")
            with src, open(dest, "xb") as output:
                while chunk := src.read(1024*1024):
                    output.write(chunk)
            # Preserve only the upstream executable bit, never setuid/gid.
            dest.chmod(0o700 if member.mode & 0o111 else 0o600)
PY
test -s "$stage/s-ui/sui"
install -m 700 "$stage/s-ui/sui" "$stage/sui-verified"
"$stage/sui-verified" -v >/dev/null
mv "$stage/s-ui" /usr/local/s-ui
chmod 700 /usr/local/s-ui/sui
# Default admin/admin must never be exposed, even for a moment:
# the account initialization must happen before enabling the service.
# On a fresh S-UI installation, "sui migrate" deliberately does nothing
# when the database is absent. Instead "sui admin -username" initializes
# the schema and changes the default admin before the service ever starts.
# CLI flags may not propagate failures to exit codes; DB is read back below.
test ! -e /usr/local/s-ui/db/s-ui.db
username="nd_$(openssl rand -hex 6)"
password="$(openssl rand -hex 24)"
base_path="$(openssl rand -hex 12)"
sub_path="$(openssl rand -hex 12)"
test -n "$username" && test -n "$password" && test -n "$base_path" && test -n "$sub_path"
/usr/local/s-ui/sui admin -username "$username" -password "$password" >/dev/null 2>&1
test -f /usr/local/s-ui/db/s-ui.db
/usr/local/s-ui/sui setting -port 2095 -path "/$base_path/" -subPort 2096 \
  -subPath "/$sub_path/" >/dev/null 2>&1
SUI_INIT_USERNAME="$username" SUI_INIT_WEBPATH="/$base_path/" \
SUI_INIT_SUBPATH="/$sub_path/" python3 - <<'PY'
import os, sqlite3
name = os.environ["SUI_INIT_USERNAME"]
path = os.environ["SUI_INIT_WEBPATH"]
sub = os.environ["SUI_INIT_SUBPATH"]
db = sqlite3.connect("/usr/local/s-ui/db/s-ui.db", timeout=10)
try:
    db.execute("BEGIN IMMEDIATE")
    for k, val in (("webListen", "127.0.0.1"), ("subListen", "127.0.0.1")):
        rows = db.execute("SELECT id FROM settings WHERE key=?", (k,)).fetchall()
        if len(rows) > 1:
            raise RuntimeError("SUI_DB_DUPLICATE_SETTING")
        if rows:
            db.execute("UPDATE settings SET value=? WHERE id=?", (val, rows[0][0]))
        else:
            db.execute("INSERT INTO settings(key,value) VALUES(?,?)", (k,val))
    db.commit()
    expected = {
        "webListen": "127.0.0.1", "subListen": "127.0.0.1",
        "webPort": "2095", "subPort": "2096",
        "webPath": path, "subPath": sub,
    }
    current = dict(db.execute("SELECT key,value FROM settings"))
    for k, val in expected.items():
        if current.get(k) != val:
            raise RuntimeError("SUI_SETTING_MISSING: " + k)
    user = db.execute("SELECT username,password FROM users ORDER BY id LIMIT 1").fetchone()
    if not user or user[0] != name or not user[1] or user[1] == "admin":
        raise RuntimeError("SUI_ADMIN_NOT_SET: refusing default credentials")
finally:
    db.close()
PY
install -d -m 700 /var/lib/netdeploy/s-ui
record='/var/lib/netdeploy/s-ui/install-result.env'
test ! -e "$record"
{
 printf 'SUI_PANEL_PORT=2095\n'
 printf 'SUI_WEB_BASE_PATH=%s\n' "$base_path"
 printf 'SUI_SUB_PORT=2096\n'
 printf 'SUI_USERNAME=%s\n' "$username"
 printf 'SUI_PASSWORD=%s\n' "$password"
} > "$record"
chmod 600 "$record"
cat > /etc/systemd/system/s-ui.service <<'NETDEPLOY_SUI_SERVICE'
__SERVICE_UNIT__
NETDEPLOY_SUI_SERVICE
chmod 644 /etc/systemd/system/s-ui.service
systemctl daemon-reload
echo 'SUI_CONFIGURED: random admin, private web path and localhost-only listeners; secrets kept on VPS'
"""

VALIDATE = r"""set -eu
test "$(id -u)" = 0
record='/var/lib/netdeploy/s-ui/install-result.env'
test -f "$record" && test "$(stat -c %a "$record")" = 600
systemctl enable s-ui >/dev/null
systemctl start s-ui >/dev/null
ready=no
for n in $(seq 1 18); do
    if systemctl is-active --quiet s-ui &&
       ss -Hltn 'sport = :2095' | awk '{print $4}' | grep -Fxq '127.0.0.1:2095'; then
        ready=yes
        break
    fi
    sleep 1
done
if [ "$ready" != yes ]; then
    systemctl disable --now s-ui >/dev/null 2>&1 || true
    echo 'SUI_LOCAL_LISTENER_MISSING: public exposure refused; inspect systemd and webListen' >&2
    exit 46
fi
path="$(sed -n 's/^SUI_WEB_BASE_PATH=//p' "$record")"
printf '%s' "$path" | grep -Eq '^[a-f0-9]{24}$'
code="$(curl --proto '=http' --noproxy '*' --silent --output /dev/null \
  --write-out '%{http_code}' --max-time 10 "http://127.0.0.1:2095/$path/")" || {
    systemctl disable --now s-ui >/dev/null 2>&1 || true
    echo 'SUI_LOCAL_HTTP_FAILED: service stopped' >&2
    exit 47
}
case "$code" in 200|301|302|303|307|308|401) ;;
*) systemctl disable --now s-ui >/dev/null 2>&1 || true
   echo 'SUI_HTTP_STATUS_INVALID: service stopped' >&2; exit 48 ;;
esac
echo 'SUI_LOCAL_READY: S-UI pinned version active on 127.0.0.1:2095; SSH tunnel required'
"""

STATUS = r"""set -eu
test "$(id -u)" = 0
if test ! -x /usr/local/s-ui/sui; then
    echo 'SUI_INSTALLED=no'
    exit 0
fi
echo 'SUI_INSTALLED=yes'
if systemctl is-active --quiet s-ui; then echo 'SUI_SERVICE=active'; else echo 'SUI_SERVICE=inactive'; fi
if test -f /var/lib/netdeploy/s-ui/install-result.env &&
   test "$(stat -c %a /var/lib/netdeploy/s-ui/install-result.env)" = 600; then
    echo 'SUI_MANAGED=yes'
else
    echo 'SUI_MANAGED=no'
fi
if ss -Hltn 'sport = :2095' | awk '{print $4}' | grep -Fxq '127.0.0.1:2095'; then
    echo 'SUI_ACCESS=local'
else
    echo 'SUI_ACCESS=unverified'
fi
"""

ACCESS = r"""set -eu
test "$(id -u)" = 0
test -x /usr/local/s-ui/sui
test -f /var/lib/netdeploy/s-ui/install-result.env
test "$(stat -c %a /var/lib/netdeploy/s-ui/install-result.env)" = 600
systemctl is-active --quiet s-ui
ss -Hltn 'sport = :2095' | awk '{print $4}' | grep -Fxq '127.0.0.1:2095'
record='/var/lib/netdeploy/s-ui/install-result.env'
# Only audited, generated alphanumeric entries are accepted.
username="$(sed -n 's/^SUI_USERNAME=//p' "$record")"
password="$(sed -n 's/^SUI_PASSWORD=//p' "$record")"
path="$(sed -n 's/^SUI_WEB_BASE_PATH=//p' "$record")"
test "$(grep -c '^SUI_USERNAME=' "$record")" = 1
test "$(grep -c '^SUI_PASSWORD=' "$record")" = 1
test "$(grep -c '^SUI_WEB_BASE_PATH=' "$record")" = 1
printf '%s' "$username" | grep -Eq '^nd_[a-f0-9]{12}$'
printf '%s' "$password" | grep -Eq '^[a-f0-9]{48}$'
printf '%s' "$path" | grep -Eq '^[a-f0-9]{24}$'
code="$(curl --proto '=http' --noproxy '*' --silent --output /dev/null \
 --write-out '%{http_code}' --max-time 10 "http://127.0.0.1:2095/$path/")"
case "$code" in 200|301|302|303|307|308|401) ;; *) exit 49;; esac
printf 'SUI_PANEL_PORT=2095\nSUI_USERNAME=%s\nSUI_PASSWORD=%s\nSUI_WEB_BASE_PATH=%s\n' \
 "$username" "$password" "$path"
"""


def steps(arch: str) -> list[dict]:
    if arch not in ARTIFACTS:
        raise ValueError("S-UI 目前仅支持已验证的 x86_64/aarch64 目标")
    upstream_arch, digest = ARTIFACTS[arch]
    name = f"s-ui-linux-{upstream_arch}.tar.gz"
    common = {"__ARCH__": arch, "__VERSION__": VERSION, "__ASSET__": name, "__DIGEST__": digest}
    def render(script: str) -> str:
        for old, new in common.items():
            script = script.replace(old, new)
        return script
    return [
        {"label": "检查 root / systemd / 已安装 S-UI 与面板端口", "script": render(PRECHECK), "timeout": 35},
        {"label": "检查/安装下载、校验和 SQLite 配置依赖", "script": DEPS, "timeout": 540},
        {"label": f"下载并校验官方 {VERSION} 发行包 SHA-256", "script": render(DOWNLOAD), "timeout": 300},
        {"label": "安全解包、随机初始化管理员并强制本机监听（敏感输出隐藏）",
         "script": render(CONFIGURE).replace("__SERVICE_UNIT__", SERVICE_UNIT.rstrip()), "timeout": 180},
        {"label": "启动并验证 127.0.0.1:2095，本机 SSH 隧道访问",
         "script": VALIDATE, "timeout": 80},
    ]


def parse_status(raw: str) -> dict:
    values = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    if values.get("SUI_INSTALLED") == "no":
        return {"installed": False, "service": "absent", "managed": False, "access_mode": "unavailable"}
    if values.get("SUI_INSTALLED") != "yes":
        raise ValueError("无法确认 S-UI 是否安装")
    return {
        "installed": True, "service": values.get("SUI_SERVICE", "unknown"),
        "managed": values.get("SUI_MANAGED") == "yes",
        "access_mode": "local" if values.get("SUI_ACCESS") == "local" else "unverified",
        "port": PORT,
    }


def parse_access(raw: str, host: dict) -> dict:
    values = {}
    for line in raw.splitlines():
        if "=" not in line:
            raise ValueError("S-UI 访问记录格式不正确")
        key, val = line.split("=", 1)
        if key in values:
            raise ValueError("重复的 S-UI 凭据字段")
        values[key] = val
    if values.get("SUI_PANEL_PORT") != str(PORT):
        raise ValueError("安装记录与固定面板端口不一致")
    username = values.get("SUI_USERNAME", "")
    password = values.get("SUI_PASSWORD", "")
    path = values.get("SUI_WEB_BASE_PATH", "")
    if not (re.fullmatch(r"nd_[a-f0-9]{12}", username)
            and re.fullmatch(r"[a-f0-9]{48}", password)
            and re.fullmatch(r"[a-f0-9]{24}", path)):
        raise ValueError("无法安全读取 S-UI 登录信息")
    sshport = int(host["port"])
    user, hostname = host["username"], host["hostname"]
    return {
        "username": username, "password": password,
        "port": PORT,
        "local_url": f"http://127.0.0.1:{PORT}/{path}/",
        "ssh_tunnel": f"ssh -N -p {sshport} -L {PORT}:127.0.0.1:{PORT} {user}@{hostname}",
        "access_mode": "local",
        "initial_credentials_only": True,
    }
