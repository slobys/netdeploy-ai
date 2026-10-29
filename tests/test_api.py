from fastapi.testclient import TestClient
from app import main

TOKEN = 'test-only-' + 'a' * 32
HEAD = {'X-Admin-Token':TOKEN}
GOOD = {"OS_ID":"debian","ARCH":"x86_64","UID":"0","FREE_KB":"3333333","DOCKER":"yes","COMPOSE":"yes","SYSTEMD":"yes","UDP_51820":"free"}


class FakeSSH:
    def __init__(self):self.passwords={}
    def set_password(self,host_id,password):self.passwords[host_id]=password
    def clear_password(self,host_id):self.passwords.pop(host_id,None)
    def credential_ready(self,host):return host.get('auth_mode','key')=='key' or host['id'] in self.passwords
    def preflight(self,host):return dict(GOOD)
    def scan_hostkey(self,host):return {'fingerprint':'SHA256:'+'A'*43}
    def trust_hostkey(self,host,fingerprint):return {'fingerprint':fingerprint}
    def run(self,host,script,timeout=30):return 'command OK'


def test_api_auth_and_preflight_plans(monkeypatch):
    fake=FakeSSH()
    monkeypatch.setattr(main,'executor',fake)
    monkeypatch.setattr(main.runner,'executor',fake)
    c=TestClient(main.app)
    assert c.get('/api/hosts').status_code == 401
    assert c.get('/api/auth',headers=HEAD).status_code == 200
    host=c.post('/api/hosts',headers=HEAD,json={'name':'test','hostname':'example.com','port':22,'username':'root'}).json()
    assert host['facts'] is None
    assert c.post('/api/jobs',headers=HEAD,json={'host_id':host['id'],'project':'wg-easy'}).status_code==409
    assert c.post(f'/api/hosts/{host["id"]}/preflight',headers=HEAD).status_code==200
    plan=c.post('/api/jobs',headers=HEAD,json={'host_id':host['id'],'project':'wg-easy'}).json()
    assert plan['plan']['executable'] is True
    assert plan['status']=='planned'
    wrong=c.post(f'/api/jobs/{plan["id"]}/approve',headers=HEAD,json={'confirmation':'Yes'})
    assert wrong.status_code==409
    guided=c.post('/api/jobs',headers=HEAD,json={'host_id':host['id'],'project':'hysteria2'}).json()
    assert not guided['plan']['executable']
    denied=c.post(f'/api/jobs/{guided["id"]}/approve',headers=HEAD,json={'confirmation':f'DEPLOY hysteria2 TO example.com'})
    assert denied.status_code==409


def test_security_headers_and_static_serve():
    c=TestClient(main.app)
    res=c.get('/')
    assert res.status_code==200
    assert 'NetDeploy AI' in res.text
    assert res.headers['x-frame-options']=='DENY'
    assert res.headers['cache-control']=='no-store'
    assert c.get('/static/app.js').status_code==200
