#!/usr/bin/env bash
# NetDeploy AI · interactive Google Cloud / Debian / Ubuntu root password helper.
# Never embed, log, transmit, or accept a password via command-line arguments.
set -euo pipefail
umask 077

usage() {
  cat <<'HELP'
NetDeploy AI · GCP root access helper (run from Google Cloud native SSH / serial console)
Usage:
  sudo bash scripts/gcp-root-setup.sh --password-only
  sudo bash scripts/gcp-root-setup.sh --enable-root-password-ssh

Default / --password-only:
  Interactively set a new local root password (passwd root).
  Does NOT change SSH authentication or restart anything.

--enable-root-password-ssh (high risk, opt-in):
  ALSO enable SSH root password login on Debian/Ubuntu, but only after you
  explicitly confirm cloud firewall restrictions and back up sshd_config.
  Refuses known Google Cloud OS Login=TRUE; verifies sshd -t and effective
  settings; reloads SSH without reboot. Existing session must remain open.
HELP
}

die() { printf '[NetDeploy] %s\n' "$*" >&2; exit 1; }

mode="--password-only"
if [ "$#" -gt 0 ]; then mode="$1"; fi
case "$mode" in
  --help|-h) usage; exit 0 ;;
  --password-only) mode=password ;;
  --enable-root-password-ssh) mode=enable ;;
  *) usage; die "未知参数：仅支持 --password-only 或 --enable-root-password-ssh" ;;
esac

[ "$EUID" -eq 0 ] || die "请从谷歌云已登录的终端使用 sudo bash 执行"
[ -r /etc/os-release ] || die "无法识别目标系统"
# shellcheck disable=SC1091
. /etc/os-release
case "$ID" in ubuntu|debian) ;; *) die "仅支持 Debian / Ubuntu；不会修改其他 Linux 系统" ;; esac
command -v passwd >/dev/null 2>&1 || die "未找到 passwd 命令"
[ -t 0 ] || die "必须在交互式云终端运行，不能通过 curl | bash 或无人值守任务执行"

if [ "$mode" = enable ]; then
  echo
  echo "【高风险】此操作会允许 root 通过密码远程 SSH 登录，扩大暴力破解风险。"
  echo "推荐使用 Google Cloud OS Login / SSH 密钥 + sudo，而不是启用本选项。"
  echo "必须已经在 Google Cloud VPC 防火墙将 TCP 22 来源限制为你自己的管理 IP，"
  echo "并有独立云厂商控制台恢复途径；请保持当前 SSH 窗口不关闭。"
  echo
  echo "如果设置了 Google Cloud OS Login，此方法可能不适用，脚本会拒绝已知启用状态。"
  if command -v curl >/dev/null 2>&1; then
    for key in instance/attributes/enable-oslogin project/attributes/enable-oslogin; do
      value="$(curl --fail --silent --show-error --connect-timeout 2 --max-time 4 \
        -H 'Metadata-Flavor: Google' \
        "http://metadata.google.internal/computeMetadata/v1/$key" 2>/dev/null || true)"
      case "$value" in [Tt][Rr][Uu][Ee]) die "检测到 Google Cloud OS Login 已启用；请继续使用 IAM 管理的 SSH 密钥与 sudo" ;; esac
    done
  fi
  [ -f /etc/ssh/sshd_config ] || die "sshd_config 不存在"
  [ -d /etc/ssh/sshd_config.d ] || die "sshd_config.d 不存在，拒绝自动修改原配置"
  grep -Eq '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config[.]d/\*[.]conf' /etc/ssh/sshd_config ||
    die "未找到标准 sshd_config.d Include，拒绝盲改；请人工检查 sshd 配置"
  sshd_bin="$(command -v sshd || true)"
  if [ -z "$sshd_bin" ] && [ -x /usr/sbin/sshd ]; then sshd_bin=/usr/sbin/sshd; fi
  [ -n "$sshd_bin" ] || die "找不到 sshd，拒绝修改认证配置"
  command -v systemctl >/dev/null 2>&1 || die "没有 systemctl，拒绝自动变更"
  conf=/etc/ssh/sshd_config.d/00-netdeploy-root-password.conf
  [ ! -e "$conf" ] && [ ! -L "$conf" ] || die "已有 NetDeploy 的 SSH 配置文件；请人工检查，不覆盖"
  echo
  echo "仅在你已确认云防火墙限制与恢复方式后继续。"
  read -r -p '输入 ENABLE ROOT PASSWORD SSH 继续（其他输入取消）：' confirmation
  [ "$confirmation" = 'ENABLE ROOT PASSWORD SSH' ] || die "操作已取消，没有修改 SSH 配置"
fi

echo "[NetDeploy] 使用 passwd 交互设置 root 的新密码，不在命令、历史或日志中保存明文。"
passwd root || die "root 密码设置失败"
if [ "$mode" = password ]; then
  echo "[NetDeploy] root 本地密码已更新。SSH 登录策略未更改，也没有自动重启 VPS。"
  exit 0
fi

backup_dir=/var/backups/netdeploy-root-ssh
install -d -m 0700 "$backup_dir"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$backup_dir/sshd_config.$timestamp"
cp -p /etc/ssh/sshd_config "$backup"
chmod 0600 "$backup"

rollback() {
  rm -f "$conf"
  "$sshd_bin" -t >/dev/null 2>&1 || true
  systemctl reload ssh >/dev/null 2>&1 || systemctl reload sshd >/dev/null 2>&1 || true
}
pending=yes
trap 'if [ "$pending" = yes ]; then rollback; fi' EXIT
cat >"$conf" <<'CONFIG'
# NetDeploy AI: explicitly approved password-based root SSH; avoid on public VPS.
PermitRootLogin yes
PasswordAuthentication yes
CONFIG
chmod 0600 "$conf"

if ! "$sshd_bin" -t; then
  die "sshd 配置语法检查失败，已撤销新增配置；备份：$backup"
fi
effective="$("$sshd_bin" -T -C user=root,host=localhost,addr=127.0.0.1 2>/dev/null)" || {
  die "无法检查 sshd 有效认证配置，已撤销新增配置"
}
if ! printf '%s\n' "$effective" | grep -qx 'permitrootlogin yes' ||
   ! printf '%s\n' "$effective" | grep -qx 'passwordauthentication yes'; then
  die "sshd 有效设置仍未开启 root/password（可能被其他配置覆盖），已撤销新增配置"
fi
if ! systemctl reload ssh >/dev/null 2>&1 && ! systemctl reload sshd >/dev/null 2>&1; then
  die "SSH reload 失败，已撤销新增配置；请从云厂商终端复核 systemctl status ssh"
fi

pending=no
trap - EXIT

echo "[NetDeploy] root SSH 密码认证已修改，sshd -t 与有效配置检查通过，未重启 VPS。"
echo "[NetDeploy] 当前云控制台 / SSH 会话保持打开，另开终端从已许可的管理 IP 测试 root SSH。"
echo "[NetDeploy] 如果不能登录，使用云终端执行：rm -f $conf && systemctl reload ssh"
echo "[NetDeploy] sshd_config 备份位于：$backup"
echo "[NetDeploy] 完成测试后建议改回 SSH 密钥 / OS Login，并重新关闭 root 密码 SSH。"
