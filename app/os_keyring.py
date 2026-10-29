"""Optional OS-protected VPS SSH password vault.

Only Windows Credential Locker is enabled in this Alpha. On headless Linux
a secret-service backend is often unavailable; fail closed rather than persist
a root password in a file, database, or user-supplied Python keyring backend.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path


class VaultUnavailable(Exception):
    pass


class WindowsCredentialVault:
    def __init__(self, data_path: str):
        canonical = str(Path(data_path).resolve()).casefold().encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()[:24]
        self.service = f"NetDeployAI/vps/{digest}"

    def _backend(self):
        if sys.platform != "win32":
            raise VaultUnavailable("系统凭据库保存目前仅支持 Windows；Linux/NAS 仍使用内存密码或 SSH 私钥")
        try:
            import keyring
            backend = keyring.get_keyring()
            # Avoid third-party or plaintext backends: require native Windows vault.
            backend_type = type(backend)
            if not (backend_type.__module__ == "keyring.backends.Windows"
                    and backend_type.__name__ == "WinVaultKeyring"):
                raise VaultUnavailable("未检测到受支持的 Windows 凭据保管库")
            return keyring
        except VaultUnavailable:
            raise
        except Exception as exc:
            raise VaultUnavailable("Windows 凭据保管库不可用；请使用临时密码或检查当前用户权限") from exc

    @property
    def available(self) -> bool:
        try:
            self._backend()
            return True
        except VaultUnavailable:
            return False

    def get(self, host_id: int) -> str | None:
        try:
            return self._backend().get_password(self.service, f"host:{host_id}")
        except VaultUnavailable:
            return None
        except Exception:
            return None

    def set(self, host_id: int, password: str) -> None:
        try:
            self._backend().set_password(self.service, f"host:{host_id}", password)
        except VaultUnavailable:
            raise
        except Exception as exc:
            raise VaultUnavailable("凭据保管库写入失败，密码未保存") from exc

    def delete(self, host_id: int) -> None:
        try:
            vault = self._backend()
            if vault.get_password(self.service, f"host:{host_id}") is not None:
                vault.delete_password(self.service, f"host:{host_id}")
        except VaultUnavailable:
            raise
        except Exception as exc:
            raise VaultUnavailable("无法从系统凭据保管库清除密码") from exc
