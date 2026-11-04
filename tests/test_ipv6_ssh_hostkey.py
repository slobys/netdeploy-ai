"""Unauthenticated IPv6 host-key handshake diagnostics, without remote VPS access.

No real user server, password, trust approval, or arbitrary SSH command runs.
"""
import base64
import hashlib
import socket
import sys
import threading
import time
import types

import pytest

from app import executor as module
from app.executor import (
    SSHConfig, SSHError, SSHExecutor, SSH_SCAN_NEGOTIATION_TIMEOUT,
    classify_hostkey_handshake_error,
)

V6 = "2606:4700:4700::1111"
HOST = {"hostname": V6, "username": "root", "port": 22}


class FakeSocket:
    def __init__(self, calls):
        self.calls = calls
    def settimeout(self, timeout):
        self.calls.append(("socket_timeout", timeout))
    def close(self):
        self.calls.append(("close_socket",))


def _fake_ipv6_scan(monkeypatch, outcome_sequence):
    calls = []
    status = list(outcome_sequence)
    class SSHException(Exception):
        pass
    class PublicKey:
        def asbytes(self):
            return b"synthetic-no-secret-public-key"
        def get_name(self):
            return "ssh-ed25519"
        def get_base64(self):
            return base64.b64encode(self.asbytes()).decode("ascii")
    class Transport:
        def __init__(self, sock):
            self.socket = sock
            self.banner_timeout = None
            calls.append(("transport",))
        def start_client(self, timeout):
            calls.append(("negotiate", timeout, self.banner_timeout))
            next_outcome = status.pop(0)
            if next_outcome:
                raise SSHException(next_outcome)
        def get_remote_server_key(self):
            return PublicKey()
        def close(self):
            calls.append(("close_transport",))
    def connect_to(address, timeout):
        assert address == (V6, 22)
        calls.append(("connect", address, timeout))
        return FakeSocket(calls)
    monkeypatch.setitem(sys.modules, "paramiko", types.SimpleNamespace(
        Transport=Transport, SSHException=SSHException,
    ))
    monkeypatch.setattr(module.socket, "create_connection", connect_to)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    return calls


def test_ipv6_hostkey_scan_receives_bare_ip_and_returns_verified_format(monkeypatch, tmp_path):
    calls = _fake_ipv6_scan(monkeypatch, [None])
    ex = SSHExecutor(SSHConfig(str(tmp_path / "unused"), str(tmp_path / "known_hosts")))
    result = ex.scan_hostkey(HOST)
    expected = base64.b64encode(
        hashlib.sha256(b"synthetic-no-secret-public-key").digest()
    ).decode().rstrip("=")
    assert result["fingerprint"] == "SHA256:" + expected
    assert result["key"].startswith(V6 + " ssh-ed25519 ")
    assert len([x for x in calls if x[0] == "connect"]) == 1
    assert ("negotiate", SSH_SCAN_NEGOTIATION_TIMEOUT, SSH_SCAN_NEGOTIATION_TIMEOUT) in calls
    assert calls.count(("close_socket",)) == 1
    assert calls.count(("close_transport",)) == 1


def test_transient_banner_failure_retries_once_and_does_not_auto_trust(monkeypatch, tmp_path):
    calls = _fake_ipv6_scan(monkeypatch, ["Error reading SSH protocol banner", None])
    ex = SSHExecutor(SSHConfig(str(tmp_path / "unused"), str(tmp_path / "known_hosts")))
    result = ex.scan_hostkey(HOST)
    assert result["key_type"] == "ssh-ed25519"
    assert len([x for x in calls if x[0] == "connect"]) == 2
    assert calls.count(("close_socket",)) == 2
    assert calls.count(("close_transport",)) == 2
    assert not (tmp_path / "known_hosts").exists(), "Fingerprint scan must never auto-trust"


def test_repeated_banner_failure_reports_ssh_not_tcp_diagnostic(monkeypatch, tmp_path):
    calls = _fake_ipv6_scan(monkeypatch, ["Error reading SSH protocol banner"] * 2)
    ex = SSHExecutor(SSHConfig(str(tmp_path / "unused"), str(tmp_path / "known_hosts")))
    with pytest.raises(SSHError, match="SSH_BANNER_FAILED"):
        ex.scan_hostkey(HOST)
    assert len([x for x in calls if x[0] == "connect"]) == 2


@pytest.mark.parametrize("error,expected", [
    ("Incompatible ssh peer (no acceptable kex algorithm)", "SSH_ALGORITHM_MISMATCH"),
    ("Invalid SSH identification string", "SSH_PROTOCOL_UNEXPECTED"),
    ("Connection reset by peer", "SSH_HANDSHAKE_INTERRUPTED"),
    ("Error reading SSH protocol banner", "SSH_BANNER_FAILED"),
    ("Unexpected remote error", "SSH_HANDSHAKE_FAILED"),
])
def test_redacted_diagnostic_codes_are_not_untrusted_server_messages(error, expected):
    diagnosis, transient = classify_hostkey_handshake_error(ValueError(error))
    assert diagnosis.startswith(expected)
    assert error not in diagnosis
    if expected in ("SSH_ALGORITHM_MISMATCH", "SSH_PROTOCOL_UNEXPECTED"):
        assert transient is False


def test_algorithm_mismatch_never_retries_or_reduces_cryptographic_security(
    monkeypatch, tmp_path,
):
    calls = _fake_ipv6_scan(monkeypatch, ["Incompatible ssh peer (no acceptable host key)"])
    ex = SSHExecutor(SSHConfig(str(tmp_path / "unused"), str(tmp_path / "known_hosts")))
    with pytest.raises(SSHError, match="SSH_ALGORITHM_MISMATCH"):
        ex.scan_hostkey(HOST)
    assert len([x for x in calls if x[0] == "connect"]) == 1
    assert calls.count(("close_socket",)) == 1


@pytest.mark.skipif(not socket.has_ipv6, reason="IPv6 stack unavailable")
def test_real_paramiko_ipv6_loopback_key_exchange_uses_af_inet6(monkeypatch, tmp_path):
    """Real socket+Paramiko KEX on ::1; test-only validation exception for loopback.

    No external address is contacted. The VPS-facing global-address validator
    remains enabled in production.
    """
    import paramiko

    # Unittest-only exception for ::1; public SSH validation in product is unchanged.
    monkeypatch.setattr(module, "validate_host", lambda *_args: None)
    server_key = paramiko.RSAKey.generate(2048)
    listener = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        listener.bind(("::1", 0))
        listener.listen(1)
        listener.settimeout(10)
    except OSError:
        listener.close()
        pytest.skip("Local IPv6 loopback unavailable")

    port = listener.getsockname()[1]
    failures = []
    accepted = threading.Event()
    def server():
        conn = None
        transport = None
        try:
            conn, peer = listener.accept()
            accepted.set()
            assert conn.family == socket.AF_INET6
            transport = paramiko.Transport(conn)
            transport.add_server_key(server_key)
            transport.start_server(server=paramiko.ServerInterface())
            time.sleep(0.4)
        except Exception as exc:
            failures.append(str(type(exc).__name__))
        finally:
            if transport:
                transport.close()
            if conn:
                conn.close()
    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    try:
        ex = SSHExecutor(SSHConfig(str(tmp_path / "unused"), str(tmp_path / "known_hosts")))
        scan = ex.scan_hostkey({"hostname": "::1", "username": "root", "port": port})
        assert scan["key_type"] == "ssh-rsa"
        assert scan["key"].startswith(f"[::1]:{port} ssh-rsa ")
        assert accepted.wait(2)
        assert not (tmp_path / "known_hosts").exists()
    finally:
        listener.close()
        thread.join(timeout=3)
