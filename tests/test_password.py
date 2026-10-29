"""SSH password support must not weaken host-key verification or leak credentials."""
import json
import sqlite3
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.executor import SSHConfig, SSHError, SSHExecutor
from app.store import Store

TOKEN = 'test-only-' + 'a' * 32
HEAD = {'X-Admin-Token': TOKEN}


def test_password_host_api_redaction_and_reentry(monkeypatch, tmp_path):
    executor = SSHExecutor(SSHConfig(str(tmp_path / 'missing-key'), str(tmp_path / 'known_hosts')))
    monkeypatch.setattr(main, 'executor', executor)
    client = TestClient(main.app)
    password = 'very-unique-vps-password-!42'
    body = {'name': 'Password VPS', 'hostname': '192.0.2.3', 'port': 2222, 'username': 'root',
            'auth_mode': 'password', 'password': password}
    created = client.post('/api/hosts', headers=HEAD, json=body)
    assert created.status_code == 200, created.text
    host = created.json()
    assert host['credential_ready'] is True
    assert host['auth_mode'] == 'password'
    assert password not in created.text
    hosts = client.get('/api/hosts', headers=HEAD).text
    assert password not in hosts
    assert password not in Path(main.store.path).read_bytes().decode('utf-8', 'ignore')
    assert executor._password(host['id']) == password

    # Recreate executor to simulate process restart, without modifying host metadata.
    fresh = SSHExecutor(SSHConfig(str(tmp_path / 'missing-key'), str(tmp_path / 'known_hosts')))
    monkeypatch.setattr(main, 'executor', fresh)
    assert any(h['id'] == host['id'] and not h['credential_ready']
               for h in client.get('/api/hosts', headers=HEAD).json())
    failed = client.post(f'/api/hosts/{host["id"]}/preflight', headers=HEAD)
    assert failed.status_code == 422
    assert '重新输入密码' in failed.text
    missing = client.put(f'/api/hosts/{host["id"]}/credentials', headers=HEAD,
                         json={'auth_mode': 'password'})
    assert missing.status_code == 422
    renewed = client.put(f'/api/hosts/{host["id"]}/credentials', headers=HEAD,
                         json={'auth_mode': 'password', 'password': 'new-password'})
    assert renewed.status_code == 200
    assert renewed.json()['credential_ready'] is True
    assert 'new-password' not in renewed.text
    switched = client.put(f'/api/hosts/{host["id"]}/credentials', headers=HEAD,
                          json={'auth_mode': 'key'})
    assert switched.status_code == 200
    assert switched.json()['auth_mode'] == 'key'
    assert switched.json()['credential_ready'] is False
    with pytest.raises(SSHError):
        fresh._password(host['id'])


def test_password_requires_password_and_administrator():
    c = TestClient(main.app)
    body = {'name': 'No pass', 'hostname': 'example.com', 'auth_mode': 'password'}
    assert c.post('/api/hosts', json={**body, 'password':'test'}).status_code == 401
    assert c.post('/api/hosts', headers=HEAD, json=body).status_code == 422
    long_secret = 'DISTINCT_MARKER' + 'z'*1030
    rejected = c.post('/api/hosts', headers=HEAD, json={**body, 'password': long_secret})
    assert rejected.status_code == 422
    assert 'DISTINCT_MARKER' not in rejected.text


def test_password_transport_uses_pinned_known_hosts_and_never_falls_back(monkeypatch, tmp_path):
    known = tmp_path / 'known_hosts'
    known.write_text('example.com ssh-ed25519 AAAA\n')
    seen = {}
    class Channel:
        def exec_command(self,command):seen['command']=command
        def sendall(self,data):seen['script']=data
        def shutdown_write(self):pass
        def recv_ready(self):return False
        def recv_stderr_ready(self):return False
        def exit_status_ready(self):return True
        def recv_exit_status(self):return 0
    class Transport:
        def is_active(self):return True
        def open_session(self,timeout):return Channel()
    class Client:
        def load_host_keys(self,path):seen['pinned']=path
        def set_missing_host_key_policy(self,policy):seen['policy']=policy
        def connect(self,**kw):seen['connect']=kw
        def get_transport(self):return Transport()
        def close(self):seen['closed']=True
    class RejectPolicy:pass
    class AuthenticationException(Exception):pass
    class BadHostKeyException(Exception):pass
    class SSHException(Exception):pass
    monkeypatch.setitem(sys.modules,'paramiko', types.SimpleNamespace(
        SSHClient=Client, RejectPolicy=RejectPolicy, AuthenticationException=AuthenticationException,
        BadHostKeyException=BadHostKeyException, SSHException=SSHException))
    executor=SSHExecutor(SSHConfig(str(tmp_path/'missing-key'),str(known)))
    host={'id':9,'hostname':'example.com','username':'root','port':22,'auth_mode':'password'}
    executor.set_password(9, 'ExamplePass')
    assert executor.run(host,'echo ready',timeout=5)==''
    assert seen['script']==b'echo ready'
    assert seen['command']=='bash -se'
    assert seen['pinned']==str(known)
    assert isinstance(seen['policy'], RejectPolicy)
    assert seen['connect']['password']=='ExamplePass'
    assert seen['connect']['allow_agent'] is False
    assert seen['connect']['look_for_keys'] is False
    assert seen['closed'] is True


def test_password_transport_requires_verified_fingerprint(tmp_path):
    ex=SSHExecutor(SSHConfig(str(tmp_path/'key'), str(tmp_path/'missing-hosts')))
    host={'id':11,'hostname':'example.com','username':'root','port':22,'auth_mode':'password'}
    ex.set_password(11, 'test')
    with pytest.raises(SSHError,match='主机密钥'):
        ex.run(host,'echo test')


def fake_paramiko_scan(monkeypatch, host_key_type="ecdsa-sha2-nistp256", public=b"sample-public-key"):
    """Mock the unauthenticated SSH handshake, never SSH login or shell."""
    import base64
    from app import executor as mod
    seen = {}
    class FakeSocket:
        def settimeout(self, seconds): seen["socket_timeout"] = seconds
        def close(self): seen["socket_closed"] = True
    sock = FakeSocket()
    def connect_to(address, timeout):
        seen["address"] = address
        seen["connect_timeout"] = timeout
        return sock
    class Key:
        def get_name(self): return host_key_type
        def asbytes(self): return public
        def get_base64(self): return base64.b64encode(public).decode("ascii")
    class Transport:
        def __init__(self, connection): assert connection is sock
        def start_client(self, timeout): seen["handshake_timeout"] = timeout
        def get_remote_server_key(self): return Key()
        def close(self): seen["transport_closed"] = True
    class SSHException(Exception): pass
    monkeypatch.setattr(mod.socket, "create_connection", connect_to)
    monkeypatch.setitem(sys.modules, "paramiko", types.SimpleNamespace(
        Transport=Transport, SSHException=SSHException,
    ))
    return seen


def test_hostkey_scan_without_openssh_tools(monkeypatch, tmp_path):
    import hashlib, base64
    from app import executor as mod
    seen=fake_paramiko_scan(monkeypatch)
    def must_not_execute(*args, **kw):
        raise AssertionError("scan must not require ssh-keyscan or ssh-keygen")
    monkeypatch.setattr(mod.subprocess, "run", must_not_execute)
    ex=SSHExecutor(SSHConfig(str(tmp_path/'key'),str(tmp_path/'known_hosts')))
    data=ex.scan_hostkey({'hostname':'example.com','username':'root','port':22})
    expected=base64.b64encode(hashlib.sha256(b'sample-public-key').digest()).decode('ascii').rstrip('=')
    assert data['fingerprint']=='SHA256:'+expected
    assert data['key_type']=='ecdsa-sha2-nistp256'
    assert data['key'].startswith('example.com ecdsa-')
    assert seen['address']==('example.com',22)
    assert seen['socket_closed'] is True and seen['transport_closed'] is True


def test_hostkey_scan_nonstandard_port_and_no_password(monkeypatch, tmp_path):
    seen=fake_paramiko_scan(monkeypatch, host_key_type='ssh-ed25519')
    ex=SSHExecutor(SSHConfig(str(tmp_path/'key'),str(tmp_path/'known_hosts')))
    data=ex.scan_hostkey({'hostname':'192.0.2.7','username':'root','port':2222,'auth_mode':'password','id':1})
    assert data['key_type']=='ssh-ed25519'
    assert data['key'].startswith('[192.0.2.7]:2222 ssh-ed25519 ')
    assert seen['address']==('192.0.2.7',2222)
    assert ex._passwords=={}


def test_hostkey_scan_connection_refused_diagnostic(monkeypatch, tmp_path):
    from app import executor as mod
    def refuse(address,timeout): raise ConnectionRefusedError(111,'refused')
    monkeypatch.setattr(mod.socket,'create_connection',refuse)
    monkeypatch.setitem(sys.modules,'paramiko',types.SimpleNamespace(SSHException=type('SSHException',(Exception,),{})))
    ex=SSHExecutor(SSHConfig(str(tmp_path/'key'),str(tmp_path/'known_hosts')))
    with pytest.raises(SSHError,match='端口拒绝连接'):
        ex.scan_hostkey({'hostname':'example.com','username':'root','port':22})


def test_hostkey_scan_timeout_diagnostic(monkeypatch, tmp_path):
    from app import executor as mod
    def expire(address,timeout): raise TimeoutError()
    monkeypatch.setattr(mod.socket,'create_connection',expire)
    monkeypatch.setitem(sys.modules,'paramiko',types.SimpleNamespace(SSHException=type('SSHException',(Exception,),{})))
    ex=SSHExecutor(SSHConfig(str(tmp_path/'key'),str(tmp_path/'known_hosts')))
    with pytest.raises(SSHError,match='连接超时'):
        ex.scan_hostkey({'hostname':'example.com','username':'root','port':22})


def test_hostkey_trust_requires_matching_fingerprint_and_no_duplicate(monkeypatch, tmp_path):
    from app import executor as mod
    import base64, hashlib
    key_type='ssh-ed25519'
    public=b'sample-public-key'
    fp='SHA256:'+base64.b64encode(hashlib.sha256(public).digest()).decode().rstrip('=')
    class FakeKeys:
        def __init__(self):self.current={}
        def load(self, filename):
            raw=Path(filename).read_text()
            self.current={line.split()[0]:True for line in raw.splitlines() if line.strip()}
        def lookup(self, name):return self.current.get(name)
    fake_paramiko_scan(monkeypatch,host_key_type=key_type,public=public)
    # fake_paramiko_scan swaps paramiko for handshake; attach an independent
    # HostKeys implementation to the same namespace.
    sys.modules['paramiko'].HostKeys=FakeKeys
    ex=SSHExecutor(SSHConfig(str(tmp_path/'key'),str(tmp_path/'known_hosts')))
    host={'hostname':'example.com','username':'root','port':22}
    with pytest.raises(SSHError,match='指纹不匹配'):
        ex.trust_hostkey(host,'SHA256:'+'B'*43)
    assert not (tmp_path/'known_hosts').exists()
    result=ex.trust_hostkey(host,fp)
    assert result['fingerprint']==fp
    assert (tmp_path/'known_hosts').read_text().startswith('example.com ssh-ed25519 ')
    with pytest.raises(SSHError,match='已有主机密钥记录'):
        ex.trust_hostkey(host,fp)


def test_db_migrates_legacy_hosts_schema(tmp_path):
    db=tmp_path/'legacy.db'
    with sqlite3.connect(db) as c:
        c.execute("""CREATE TABLE hosts(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
          hostname TEXT NOT NULL, port INTEGER NOT NULL, username TEXT NOT NULL,
          facts_json TEXT, checked_at TEXT, created_at TEXT NOT NULL)""")
        c.execute("INSERT INTO hosts(name,hostname,port,username,created_at) VALUES ('Old','example.com',22,'root','now')")
    store=Store(str(db))
    assert store.hosts()[0]['auth_mode']=='key'
    assert store.hosts()[0]['hostname']=='example.com'
