"""Optional HTTPS domain bound to a VPS SSH IPv4, with safe SQLite migration.

All API and script tests are offline, fake SSH only; no CA or VPS is contacted.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import main
from app.store import Store

HEAD={"X-Admin-Token":"test-only-"+"a"*32}
FACTS={
    "OS_ID":"ubuntu","OS_VERSION":"26.10","ARCH":"x86_64",
    "UID":"0","FREE_KB":"3200000","DOCKER":"no","COMPOSE":"no",
    "SYSTEMD":"yes","SS_AVAILABLE":"yes","UDP_51820":"free",
    "XUI_PRESENT":"no",
}


@pytest.fixture()
def app_vps(tmp_path, monkeypatch):
    db=Store(str(tmp_path/"data.sqlite"))
    class SSH:
        class Vault:
            available=False
        vault=Vault()
        def credential_ready(self,host):return True
        def preflight(self,host):return FACTS.copy()
        def password_remembered(self,host_id):return False
        def run(self,host,script,timeout=30):
            return ("XUI_EXISTS=yes\nXUI_SERVICE=active\nXUI_MANAGED=yes\n"
                    "XUI_PORT=8443\nXUI_LISTENER=local\n")
    ssh=SSH()
    monkeypatch.setattr(main,"store",db)
    monkeypatch.setattr(main,"executor",ssh)
    client=TestClient(main.app)
    return client,db,ssh


def add(client, domain=None, ip="45.32.35.195"):
    return client.post("/api/hosts",headers=HEAD,json={
        "name":"JP VPS", "hostname":ip, "port":22,"username":"root",
        "auth_mode":"key","tls_domain":domain,
    })


def test_ip_ssh_with_optional_domain_and_without_domain(app_vps):
    client,db,_=app_vps
    first=add(client," PANEL.EXAMPLE.COM. ")
    assert first.status_code==200,first.text
    data=first.json()
    assert data["hostname"]=="45.32.35.195"
    assert data["tls_domain"]=="panel.example.com"
    assert data["credential_ready"] is True
    assert db.host(data["id"])["tls_domain"]=="panel.example.com"
    assert "password" not in data

    second=add(client, None, "45.32.35.196")
    assert second.status_code==200,second.text
    assert second.json()["tls_domain"] is None


@pytest.mark.parametrize("bad", [
    "https://ts.example.com", "45.32.35.195", "example..com", "x.local",
    "evil;rm -rf /", "-bad.example.com", "foo_bar.example.com",
])
def test_invalid_tls_domain_fails_without_creating_host(app_vps, bad):
    client,db,_=app_vps
    count=len(db.hosts())
    response=add(client,bad)
    assert response.status_code==422,response.text
    assert len(db.hosts())==count


def test_domain_requires_ssh_public_ipv4(app_vps):
    client,db,_=app_vps
    response=add(client,"ts.example.com",ip="host.example.com")
    assert response.status_code==422
    assert "SSH" in response.text
    assert not db.hosts()


@pytest.mark.parametrize(("domain","mode","identity"),[
    (None,"ip","45.32.35.195"),("panel.example.com","domain","panel.example.com")
])
def test_https_identity_from_vps_record_and_fixed_script(app_vps,domain,mode,identity):
    client,db,_=app_vps
    host=add(client,domain).json()
    job=client.post("/api/jobs",headers=HEAD,json={
        "host_id":host["id"],"project":"3x-ui",
        "access_mode":"https","panel_port":8443,
    })
    assert job.status_code==200,job.text
    plan=job.json()["plan"]
    assert plan["executable"] is True and len(plan["steps"])==9
    assert plan["options"]["tls_identity"]==identity
    assert plan["options"]["certificate_type"]==mode
    if domain:
        assert plan["options"]["ssh_ipv4"]=="45.32.35.195"
        preflight=plan["steps"][5]["script"]
        assert 'test "$public_ip" = "45.32.35.195"' in preflight
        assert 'getent ahostsv4 "panel.example.com"' in preflight
        issue=plan["steps"][7]["script"]
        assert '-d "panel.example.com"' in issue
        assert "--ip-address" not in issue
        assert "--SSH_IP__" not in preflight
    else:
        assert "ssh_ipv4" not in plan["options"]
        issue=plan["steps"][7]["script"]
        assert '--ip-address "45.32.35.195"' in issue


def test_edit_tls_domain_without_changing_ssh_endpoint_but_invalidate_old_pending(app_vps):
    client,db,_=app_vps
    host=add(client).json()
    job=client.post("/api/jobs",headers=HEAD,json={
        "host_id":host["id"],"project":"3x-ui","panel_port":8443,
        "access_mode":"https",
    }).json()
    res=client.put(f"/api/hosts/{host['id']}",headers=HEAD,json={
        "name":"JP VPS renamed","hostname":host["hostname"],
        "port":host["port"],"username":"root","tls_domain":"panel.example.com",
    })
    assert res.status_code==200,res.text
    assert res.json()["tls_domain"]=="panel.example.com"
    assert res.json()["trust_epoch"]==host["trust_epoch"]
    assert res.json()["hostname"]==host["hostname"]
    assert db.job(job["id"])["status"]=="invalidated"
    assert db.job(job["id"])["plan"]["options"]["tls_identity"]=="45.32.35.195"
    another=client.post("/api/jobs",headers=HEAD,json={
        "host_id":host["id"],"project":"3x-ui","panel_port":8443,
        "access_mode":"https",
    })
    assert another.status_code==200
    assert another.json()["plan"]["options"]["tls_identity"]=="panel.example.com"


def test_edit_without_domain_field_preserves_existing_domain(app_vps):
    client,db,_=app_vps
    host=add(client,"panel.example.com").json()
    edit=client.put(f"/api/hosts/{host['id']}",headers=HEAD,json={
        "name":"JP VPS 02","hostname":host["hostname"],"port":22,"username":"root"
    })
    assert edit.status_code==200
    assert edit.json()["tls_domain"]=="panel.example.com"


def test_tls_domain_change_during_running_job_blocked(app_vps):
    client,db,_=app_vps
    host=add(client).json()
    job=db.new_job(host["id"],"sing-box",{"steps":[]})
    db.set_status(job["id"],"running")
    response=client.put(f"/api/hosts/{host['id']}",headers=HEAD,json={
        "name":"JP VPS","hostname":host["hostname"],"port":22,
        "username":"root","tls_domain":"panel.example.com",
    })
    assert response.status_code==409
    assert db.host(host["id"])["tls_domain"] is None


def test_sqlite_host_migration_keeps_old_host_and_jobs(tmp_path):
    dbfile=tmp_path/"old.sqlite"
    c=sqlite3.connect(dbfile)
    c.executescript("""
      CREATE TABLE hosts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, hostname TEXT NOT NULL,
        port INTEGER NOT NULL, username TEXT NOT NULL,
        auth_mode TEXT DEFAULT 'key',trust_epoch INTEGER DEFAULT 0,
        facts_json TEXT,checked_at TEXT, created_at TEXT NOT NULL
      );
      INSERT INTO hosts(name,hostname,port,username,auth_mode,created_at)
      VALUES('Old JP','45.32.35.195',22,'root','key','2026-10-01');
    """)
    c.close()
    migrated=Store(str(dbfile))
    old=migrated.host(1)
    assert old is not None
    assert old["hostname"]=="45.32.35.195"
    assert old["tls_domain"] is None
    assert migrated.update_host(1,old["name"],old["hostname"],22,"root","panel.example.com")["tls_domain"]=="panel.example.com"


def test_existing_https_only_plan_uses_optional_domain_not_ssh_ip(app_vps):
    client,db,ssh=app_vps
    host=add(client,"panel.example.com").json()
    ssh.preflight=lambda _host: {**FACTS,"XUI_PRESENT":"yes"}
    ssh.run=lambda _host,_script,timeout=26: (
        "XUI_EXISTS=yes\nXUI_SERVICE=active\nXUI_MANAGED=yes\n"
        "XUI_PORT=8443\nXUI_LISTENER=local\n"
    )
    job=client.post("/api/jobs",headers=HEAD,json={
        "host_id":host["id"],"project":"3x-ui-https",
    })
    assert job.status_code==200,job.text
    plan=job.json()["plan"]
    assert len(plan["steps"])==4
    assert plan["options"]["tls_identity"]=="panel.example.com"
    assert plan["options"]["ssh_ipv4"]=="45.32.35.195"
    assert plan["options"]["certificate_type"]=="domain"
    assert '-d "panel.example.com"' in plan["steps"][2]["script"]
    assert 'getent ahostsv4 "panel.example.com"' in plan["steps"][0]["script"]


def test_existing_verified_https_access_url_prefers_optional_domain(app_vps):
    client,db,ssh=app_vps
    host=add(client,"panel.example.com").json()
    seen=[]
    def fake_run(_host,script,timeout=26):
        seen.append(script)
        if "XUI_EXISTS=" in script:
            return ("XUI_EXISTS=yes\nXUI_SERVICE=active\nXUI_MANAGED=yes\n"
                    "XUI_PORT=8443\nXUI_LISTENER=https\n")
        assert "--connect-to 'panel.example.com:8443:127.0.0.1:8443'" in script
        return ("XUI_USERNAME=AdminInitial89\nXUI_PASSWORD=InitialSecretPassword88\n"
                "XUI_PANEL_PORT=8443\nXUI_WEB_BASE_PATH=SecretRoute123\n")
    ssh.run=fake_run
    result=client.get(f"/api/hosts/{host['id']}/3x-ui/access",headers=HEAD)
    assert result.status_code==200,result.text
    assert result.json()["direct_url"]=="https://panel.example.com:8443/SecretRoute123"
    assert result.json()["access_mode"]=="https"
    assert "ssh_tunnel" not in result.json()
    assert all("root@panel.example.com" not in script for script in seen)
