"""SSH transport with pinned host keys and in-memory password credentials.

SSH command argv and remote scripts are entirely internal. AI responses, user
inputs and saved deployment plans are never used as executable shell commands.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .os_keyring import WindowsCredentialVault, VaultUnavailable

SAFE_HOST = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$")
SAFE_USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$", re.IGNORECASE)


class SSHError(Exception):
    pass


def validate_host(hostname: str, username: str, port: int) -> None:
    if not SAFE_HOST.fullmatch(hostname) or ".." in hostname or hostname.startswith("-"):
        raise ValueError("服务器地址只能使用合法 IPv4 地址或 DNS 名称；暂不支持 IPv6")
    if not SAFE_USER.fullmatch(username) or username.startswith("-"):
        raise ValueError("SSH 用户名不合法")
    if not 1 <= int(port) <= 65535:
        raise ValueError("SSH 端口不合法")


@dataclass
class SSHConfig:
    keyfile: str
    known_hosts: str


class SSHExecutor:
    def __init__(self, config: SSHConfig):
        self.config = config
        self._passwords: dict[int, str] = {}
        self.vault = WindowsCredentialVault(str(Path(config.known_hosts).parent))
        self._credentials_lock = threading.RLock()
        self._known_hosts_lock = threading.RLock()

    def set_password(self, host_id: int, password: str, remember: bool = False) -> None:
        if not password or len(password) > 1024:
            raise ValueError("SSH 密码长度必须在 1 到 1024 字符之间")
        with self._credentials_lock:
            if remember:
                # Require an OS-protected vault; never fall back to plaintext.
                self.vault.set(host_id, password)
            elif self.vault.available:
                self.vault.delete(host_id)
            self._passwords[host_id] = password

    def clear_password(self, host_id: int) -> None:
        with self._credentials_lock:
            if self.vault.available:
                self.vault.delete(host_id)
            self._passwords.pop(host_id, None)

    def password_remembered(self, host_id: int) -> bool:
        return bool(self.vault.get(host_id))

    def credential_ready(self, host: dict) -> bool:
        if host.get("auth_mode", "key") == "password":
            with self._credentials_lock:
                return bool(self._passwords.get(host["id"]) or self.vault.get(host["id"]))
        return Path(self.config.keyfile).is_file()

    def _password(self, host_id: int) -> str:
        with self._credentials_lock:
            password = self._passwords.get(host_id)
            if not password:
                password = self.vault.get(host_id)
        if not password:
            raise SSHError("SSH 密码尚未设置或系统凭据保管库不可用，请在服务器管理中重新输入密码")
        return password

    def _args(self, host: dict) -> list[str]:
        validate_host(host["hostname"], host["username"], int(host["port"]))
        if not Path(self.config.keyfile).is_file():
            raise SSHError("未配置专用 SSH 私钥文件；请参照 README 挂载只读密钥")
        if not Path(self.config.known_hosts).is_file():
            raise SSHError("尚未确认服务器主机公钥，请先在面板验证 SSH 指纹")
        return [
            "ssh", "-F", "/dev/null", "-T", "-p", str(host["port"]), "-i", self.config.keyfile,
            "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "PasswordAuthentication=no",
            "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={self.config.known_hosts}",
            "-o", "GlobalKnownHostsFile=/dev/null", "-o", "ConnectTimeout=8",
            "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2",
            f'{host["username"]}@{host["hostname"]}', "bash", "-se",
        ]

    def run(self, host: dict, script: str, timeout: int = 30) -> str:
        if not isinstance(script, str) or not script:
            raise SSHError("空脚本不可执行")
        validate_host(host["hostname"], host["username"], int(host["port"]))
        if host.get("auth_mode", "key") == "password":
            return self._run_password(host, script, timeout)
        try:
            res = subprocess.run(self._args(host), input=script, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise SSHError(f"执行超时（{timeout}s）") from exc
        except FileNotFoundError as exc:
            raise SSHError("执行器缺少 OpenSSH 客户端") from exc
        # Remote installers may inadvertently include secrets: never show unlimited output.
        output = (res.stdout or "")[-12000:]
        if res.returncode:
            lower = output.lower()
            if "remote host identification has changed" in lower:
                raise SSHError("SSH_HOST_KEY_CHANGED：主机密钥与已保存指纹不匹配。请通过 VPS 云控制台独立确认；不会自动信任或覆盖")
            if "host key verification failed" in lower:
                raise SSHError("SSH_HOST_KEY_UNTRUSTED：主机密钥无法通过已固定指纹校验。请通过独立渠道核实")
            if "permission denied (publickey" in lower:
                raise SSHError("SSH_AUTH_FAILED：专用 SSH 私钥认证被拒绝，请检查公钥是否安装在服务器")
            if "connection refused" in lower:
                raise SSHError("SSH_CONNECTION_REFUSED：SSH 端口拒绝连接，请检查 sshd 监听与云防火墙")
            if "connection timed out" in lower or "operation timed out" in lower:
                raise SSHError("SSH_CONNECT_TIMEOUT：SSH 连接超时，请检查网络与云安全组")
            if "kex_exchange_identification" in lower or "unable to negotiate" in lower:
                raise SSHError("SSH_HANDSHAKE_FAILED：SSH 握手或算法协商失败，请检查 SSH 服务日志")
            raise SSHError(f"远端执行退出代码 {res.returncode}：{output[-1400:]}")
        return output

    def _run_password(self, host: dict, script: str, timeout: int) -> str:
        """Paramiko password authentication; no shell, env, disk or DB password.

        Authentication and execution use the *same* pinned known_hosts file as
        key login. There is intentionally no automatic unknown-key acceptance.
        """
        password = self._password(host["id"])
        if not Path(self.config.known_hosts).is_file():
            raise SSHError("尚未信任 SSH 主机密钥，请先核实 SSH 指纹")
        try:
            import paramiko
        except ImportError as exc:
            raise SSHError("缺少 Paramiko 依赖，请更新安装包并执行 pip install -r requirements.txt") from exc
        client = paramiko.SSHClient()
        deadline = time.monotonic() + timeout
        try:
            client.load_host_keys(self.config.known_hosts)
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            connect_timeout = min(8, max(1, timeout))
            client.connect(
                hostname=host["hostname"], port=int(host["port"]), username=host["username"],
                password=password, look_for_keys=False, allow_agent=False,
                timeout=connect_timeout, auth_timeout=connect_timeout, banner_timeout=connect_timeout,
            )
            transport = client.get_transport()
            if transport is None or not transport.is_active():
                raise SSHError("SSH 会话未建立")
            channel = transport.open_session(timeout=connect_timeout)
            channel.exec_command("bash -se")
            channel.sendall(script.encode("utf-8"))
            channel.shutdown_write()
            output = b""
            while True:
                drained = False
                if channel.recv_ready():
                    output = (output + channel.recv(32768))[-12000:]
                    drained = True
                if channel.recv_stderr_ready():
                    output = (output + channel.recv_stderr(32768))[-12000:]
                    drained = True
                if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                    break
                if time.monotonic() > deadline:
                    raise SSHError(f"执行超时（{timeout}s）")
                if not drained:
                    time.sleep(0.03)
            result = output.decode("utf-8", errors="replace")
            code = channel.recv_exit_status()
            if code:
                raise SSHError(f"退出代码 {code}：{result[-1400:]}")
            return result
        except paramiko.AuthenticationException as exc:
            raise SSHError("SSH_AUTH_FAILED：SSH 密码认证失败，请检查用户名、密码和 sshd 的 PasswordAuthentication 设置") from exc
        except paramiko.BadHostKeyException as exc:
            raise SSHError("SSH_HOST_KEY_CHANGED：服务器返回的主机密钥与已保存指纹不一致。已阻止连接，请在云控制台独立核对，禁止自动覆盖") from exc
        except paramiko.SSHException as exc:
            message = str(exc).lower()
            if "not found in known_hosts" in message or "not found in known hosts" in message:
                raise SSHError("SSH_HOST_KEY_UNTRUSTED：未找到该服务器的已信任主机密钥，请独立核对 SSH 指纹后信任") from exc
            if "incompatible ssh peer" in message or "no matching" in message:
                raise SSHError("SSH_ALGORITHM_MISMATCH：SSH 密钥交换或加密算法不兼容，请查看 VPS sshd 配置") from exc
            raise SSHError("SSH_HANDSHAKE_FAILED：TCP 可能可达，但 SSH 协议握手失败。请检查 sshd 日志、连接限制及算法兼容性") from exc
        except socket.gaierror as exc:
            raise SSHError("SSH_DNS_FAILED：无法解析 VPS 地址，请检查 IP 或域名") from exc
        except ConnectionRefusedError as exc:
            raise SSHError("SSH_CONNECTION_REFUSED：目标 SSH 端口拒绝连接，请检查 sshd 与安全组") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise SSHError("SSH_CONNECT_TIMEOUT：连接或认证超时，请检查服务器负载、网络与安全组") from exc
        except (OSError, EOFError) as exc:
            raise SSHError("SSH_NETWORK_ERROR：SSH 网络连接中断，请检查服务器地址、端口、防火墙及 sshd") from exc
        finally:
            client.close()

    def preflight(self, host: dict) -> dict[str, str]:
        script = """set -eu
. /etc/os-release
printf 'OS_ID=%s\\n' "${ID:-unknown}"
printf 'OS_VERSION=%s\\n' "${VERSION_ID:-unknown}"
printf 'ARCH=%s\\n' "$(uname -m)"
printf 'UID=%s\\n' "$(id -u)"
printf 'FREE_KB=%s\\n' "$(df -Pk / | awk 'NR==2 { print $4 }')"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then echo DOCKER=yes; else echo DOCKER=no; fi
if docker compose version >/dev/null 2>&1; then echo COMPOSE=yes; else echo COMPOSE=no; fi
if command -v systemctl >/dev/null 2>&1; then echo SYSTEMD=yes; else echo SYSTEMD=no; fi
if command -v ss >/dev/null 2>&1; then echo SS_AVAILABLE=yes; else echo SS_AVAILABLE=no; fi
if [ -d /usr/local/x-ui ] || [ -d /etc/x-ui ] || command -v x-ui >/dev/null 2>&1 || (command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files --no-legend x-ui.service 2>/dev/null | grep -q '^x-ui[.]service'); then echo XUI_PRESENT=yes; else echo XUI_PRESENT=no; fi
if ! command -v ss >/dev/null 2>&1; then echo UDP_51820=unknown; elif ss -Hlun | grep -Eq '(^|[[:space:]])[^[:space:]]*:51820([[:space:]]|$)'; then echo UDP_51820=busy; else echo UDP_51820=free; fi
"""
        result = {}
        for line in self.run(host, script, 35).splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k in {"OS_ID", "OS_VERSION", "ARCH", "UID", "FREE_KB", "DOCKER", "COMPOSE", "SYSTEMD", "UDP_51820", "SS_AVAILABLE", "XUI_PRESENT"}:
                    result[k] = v.strip()[:80]
        if not {"OS_ID", "ARCH", "UID"} <= result.keys():
            raise SSHError("设备预检信息不完整")
        return result

    def scan_hostkey(self, host: dict) -> dict[str, str]:
        """Read the SSH server host key using Paramiko, on Windows and Linux.

        No password, user login, ssh-keyscan or ssh-keygen is required here.
        The handshake is *unauthenticated* until the human compares the
        returned fingerprint with the VPS provider console.
        """
        validate_host(host["hostname"], host["username"], int(host["port"]))
        try:
            import paramiko
        except ImportError as exc:
            raise SSHError("缺少 Paramiko，请执行 py -m pip install -r requirements.txt") from exc

        address = host["hostname"]
        port = int(host["port"])
        sock = None
        transport = None
        try:
            sock = socket.create_connection((address, port), timeout=8)
            sock.settimeout(8)
            transport = paramiko.Transport(sock)
            transport.start_client(timeout=8)
            key = transport.get_remote_server_key()
            if key is None:
                raise SSHError("已连接 SSH 端口，但服务器没有提供主机公钥，请检查 SSH 服务配置")
            key_type = key.get_name()
            supported = {"ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256",
                         "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521"}
            if key_type not in supported:
                raise SSHError(f"暂不支持该 SSH 主机密钥类型：{key_type}")
            public_key = key.asbytes()
            digest = base64.b64encode(hashlib.sha256(public_key).digest()).decode("ascii").rstrip("=")
            host_token = address if port == 22 else f"[{address}]:{port}"
            return {
                "key": f"{host_token} {key_type} {key.get_base64()}",
                "fingerprint": f"SHA256:{digest}",
                "key_type": key_type,
            }
        except socket.gaierror as exc:
            raise SSHError("无法解析服务器地址，请检查 VPS IP 或域名是否填写正确") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise SSHError(f"SSH 连接超时（{address}:{port}）：请检查云防火墙、安全组及 SSH 端口是否放行") from exc
        except ConnectionRefusedError as exc:
            raise SSHError(f"SSH 端口拒绝连接（{address}:{port}）：请确认 sshd 已启动并监听此端口") from exc
        except (paramiko.SSHException, EOFError) as exc:
            raise SSHError("SSH 握手失败：端口已响应，但不是可正常协商的 SSH 服务；请检查 sshd 和服务器日志") from exc
        except OSError as exc:
            raise SSHError(f"无法连接 SSH 端口（{address}:{port}）：请检查本机网络、服务器 IP 和防火墙") from exc
        finally:
            if transport is not None:
                transport.close()
            if sock is not None:
                sock.close()

    def trust_hostkey(self, host: dict, confirmed_fingerprint: str) -> dict:
        """Pin only an out-of-band verified host key; never replace an old key."""
        scanned = self.scan_hostkey(host)
        if scanned["fingerprint"] != confirmed_fingerprint:
            raise SSHError("指纹不匹配：服务器主机密钥可能已变化，禁止信任")
        try:
            import paramiko
        except ImportError as exc:
            raise SSHError("缺少 Paramiko，请执行 py -m pip install -r requirements.txt") from exc

        path = Path(self.config.known_hosts)
        host_token = host["hostname"] if host["port"] == 22 else f'[{host["hostname"]}]:{host["port"]}'
        with self._known_hosts_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(mode=0o600, exist_ok=True)
            os.chmod(path, 0o600)
            keys = paramiko.HostKeys()
            try:
                keys.load(str(path))
            except (OSError, ValueError, paramiko.SSHException) as exc:
                raise SSHError("无法读取已有 SSH 主机密钥记录，请检查 data/known_hosts 文件") from exc
            pinned = keys.lookup(host_token)
            if pinned is not None:
                # Re-confirming an already pinned key is safe and must not
                # append a duplicate. A different key (including another
                # algorithm) is never silently accepted or replaced.
                trusted_key = pinned.get(scanned["key_type"])
                scanned_base64 = scanned["key"].split(None, 2)[2]
                if trusted_key is not None and trusted_key.get_base64() == scanned_base64:
                    return {"fingerprint": scanned["fingerprint"], "already_trusted": True}
                raise SSHError(
                    "已有主机密钥记录，但与当前服务器公钥不一致，禁止从面板覆盖。"
                    "若 VPS 已重装，请在独立可信渠道核实后手工修复 data/known_hosts"
                )
            with path.open("a", encoding="utf-8") as stream:
                stream.write(scanned["key"] + "\n")
        return {"fingerprint": scanned["fingerprint"], "already_trusted": False}
