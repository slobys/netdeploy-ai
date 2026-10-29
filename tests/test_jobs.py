from app.tasks import JobRunner, sanitize
from app.store import Store
from app.catalog import build_plan
from tempfile import TemporaryDirectory
from pathlib import Path
from time import sleep

FACTS={'OS_ID':'debian','ARCH':'x86_64','UID':'0','FREE_KB':'1000000','DOCKER':'yes','COMPOSE':'yes','UDP_51820':'free','SYSTEMD':'yes'}

class StubExecutor:
    def __init__(self):self.scripts=[]
    def run(self,host,script,timeout=30):
        self.scripts.append(script)
        return 'done\n'


def test_job_approval_and_audited_execution():
    with TemporaryDirectory() as td:
        s=Store(str(Path(td)/'data.db'))
        h=s.add_host({'name':'vps','hostname':'example.com','username':'root','port':22})
        s.save_facts(h['id'],FACTS)
        plan=build_plan('sing-box',FACTS)
        j=s.new_job(h['id'],'sing-box',plan)
        fake=StubExecutor()
        runner=JobRunner(s,fake)
        runner.enqueue(j,h,'DEPLOY sing-box TO example.com')
        for _ in range(50):
            if s.job(j['id'])['status']=='completed':break
            sleep(.02)
        assert s.job(j['id'])['status']=='completed'
        assert len(fake.scripts)==len(plan['steps'])
        assert s.job(j['id'])['logs'].count('通过：')==3


def test_secret_redaction():
    assert 'my-secret' not in sanitize('password=my-secret')
    assert 'oops' not in sanitize('token: oops')


def test_modified_database_plan_cannot_execute_commands():
    with TemporaryDirectory() as td:
        s=Store(str(Path(td)/'data.db'))
        h=s.add_host({'name':'vps','hostname':'example.com','username':'root','port':22})
        s.save_facts(h['id'], FACTS)
        plan=build_plan('sing-box', FACTS)
        j=s.new_job(h['id'],'sing-box',plan)
        # Simulate malformed/tampered stored recipe (attacker having write access to DB).
        import sqlite3,json
        with sqlite3.connect(s.path) as db:
            job=s.job(j['id'])
            job['plan']['steps'][0]['script']='echo MALICIOUS'
            db.execute('UPDATE jobs SET plan_json=? WHERE id=?',(json.dumps(job['plan']),j['id']))
        fake=StubExecutor()
        runner=JobRunner(s,fake)
        runner.enqueue(s.job(j['id']),h,'DEPLOY sing-box TO example.com')
        for _ in range(100):
            if s.job(j['id'])['status']=='failed':break
            sleep(.01)
        assert s.job(j['id'])['status']=='failed'
        assert fake.scripts==[]
