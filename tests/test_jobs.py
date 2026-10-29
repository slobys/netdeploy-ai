from app.tasks import JobRunner, sanitize
from app.store import Store
from app.catalog import build_plan
from tempfile import TemporaryDirectory
from contextlib import closing
from pathlib import Path
from time import sleep

FACTS={'OS_ID':'debian','ARCH':'x86_64','UID':'0','FREE_KB':'1000000','DOCKER':'yes','COMPOSE':'yes','UDP_51820':'free','SYSTEMD':'yes','XUI_PRESENT':'no','SS_AVAILABLE':'yes'}

def wait_for_worker(runner, host_id):
    """Status can become terminal before background writes are fully done."""
    lock = runner._locks[host_id]
    assert lock.acquire(timeout=10), "Background worker did not release its VPS lock"
    lock.release()


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
        wait_for_worker(runner, h['id'])
        assert s.job(j['id'])['status']=='completed'
        assert len(fake.scripts)==len(plan['steps'])
        assert s.job(j['id'])['logs'].count('通过：')==3


def test_xui_install_is_approved_and_runs_only_frozen_steps():
    with TemporaryDirectory() as td:
        store=Store(str(Path(td)/'data.db'))
        host=store.add_host({'name':'xui','hostname':'example.com','username':'root','port':22})
        store.save_facts(host['id'],FACTS)
        plan=build_plan('3x-ui',FACTS,{'panel_port':25443})
        job=store.new_job(host['id'],'3x-ui',plan)
        executor=StubExecutor()
        runner=JobRunner(store,executor)
        try:
            runner.enqueue(job,host,'INVALID CONFIRMATION')
        except ValueError:
            pass
        assert executor.scripts==[]
        runner.enqueue(job,host,'DEPLOY 3x-ui TO example.com')
        for _ in range(100):
            if store.job(job['id'])['status']=='completed':break
            sleep(.01)
        wait_for_worker(runner, host['id'])
        assert store.job(job['id'])['status']=='completed'
        assert executor.scripts==[step['script'] for step in plan['steps']]
        assert len(executor.scripts)==5
        assert 'password=' not in store.job(job['id'])['logs'].lower()


def test_xui_tampered_options_cannot_change_remote_commands():
    with TemporaryDirectory() as td:
        store=Store(str(Path(td)/'data.db'))
        host=store.add_host({'name':'xui','hostname':'example.com','username':'root','port':22})
        store.save_facts(host['id'],FACTS)
        job=store.new_job(host['id'],'3x-ui',build_plan('3x-ui',FACTS,{'panel_port':25443}))
        import sqlite3,json
        with closing(sqlite3.connect(store.path)) as db,db:
            j=store.job(job['id'])
            j['plan']['options']={'panel_port':26500}
            db.execute('UPDATE jobs SET plan_json=? WHERE id=?',(json.dumps(j['plan']),j['id']))
        executor=StubExecutor()
        runner=JobRunner(store,executor)
        runner.enqueue(store.job(job['id']),host,'DEPLOY 3x-ui TO example.com')
        for _ in range(100):
            if store.job(job['id'])['status']=='failed':break
            sleep(.01)
        wait_for_worker(runner, host['id'])
        assert store.job(job['id'])['status']=='failed'
        assert executor.scripts==[]


def test_xui_installed_but_certificate_failed_is_partial_not_reinstalled():
    """If certificate setup fails after step 5, preserve the installed panel."""
    from app.executor import SSHError

    class CertbotFailureExecutor(StubExecutor):
        def run(self, host, script, timeout=30):
            self.scripts.append(script)
            if len(self.scripts) == 7:
                raise SSHError("Certbot not available - test failure")
            return "stage passed\\n"

    with TemporaryDirectory() as td:
        store = Store(str(Path(td) / "data.db"))
        host = store.add_host({'name': 'xui', 'hostname': 'panel.example.com',
                               'username': 'root', 'port': 22})
        store.save_facts(host['id'], FACTS)
        plan = build_plan('3x-ui', FACTS, {
            'panel_port': 24443, 'access_mode': 'https',
            'tls_identity': 'panel.example.com'
        })
        job = store.new_job(host['id'], '3x-ui', plan)
        ssh = CertbotFailureExecutor()
        runner = JobRunner(store, ssh)
        runner.enqueue(job, host, 'DEPLOY 3x-ui TO panel.example.com')
        for _ in range(100):
            if store.job(job['id'])['status'] == 'partial':
                break
            sleep(.01)
        wait_for_worker(runner, host['id'])
        state = store.job(job['id'])
        assert state['status'] == 'partial'
        assert len(ssh.scripts) == 7
        assert state['logs'].count('通过：') == 6
        assert 'HTTPS 未完成' in state['logs']
        assert 'secret' not in state['logs'].lower()


def test_existing_xui_https_upgrade_executes_only_certificate_steps():
    """Reconstructed source-controlled upgrade must not rerun 3X-UI installer."""
    with TemporaryDirectory() as td:
        store = Store(str(Path(td) / "data.db"))
        host = store.add_host({'name':'xui','hostname':'panel.example.com',
                               'username':'root','port':22})
        facts = dict(FACTS, XUI_PRESENT='yes')
        store.save_facts(host['id'], facts)
        options = {'panel_port': 24443, 'tls_identity':'panel.example.com',
                   'source_job_id':'a'*16}
        plan = build_plan('3x-ui-https', facts, options)
        assert plan['options']['certificate_type'] == 'domain'
        job = store.new_job(host['id'], '3x-ui-https', plan)
        ssh = StubExecutor()
        runner = JobRunner(store, ssh)
        runner.enqueue(job, host, 'DEPLOY 3x-ui-https TO panel.example.com')
        for _ in range(100):
            if store.job(job['id'])['status'] == 'completed':
                break
            sleep(.01)
        wait_for_worker(runner, host['id'])
        assert store.job(job['id'])['status'] == 'completed'
        assert len(ssh.scripts) == 4
        assert all('/var/lib/netdeploy/3x-ui/install-' not in x for x in ssh.scripts)


def test_certificate_mode_tampering_blocks_execution():
    """A changed certificate mode must never bypass audited script checks."""
    with TemporaryDirectory() as td:
        store = Store(str(Path(td) / 'data.db'))
        host = store.add_host({'name':'xui','hostname':'panel.example.com',
                               'username':'root','port':22})
        store.save_facts(host['id'], FACTS)
        plan = build_plan('3x-ui', FACTS, {'panel_port':24443,
            'access_mode':'https','tls_identity':'panel.example.com'})
        job = store.new_job(host['id'], '3x-ui', plan)
        import json, sqlite3
        with closing(sqlite3.connect(store.path)) as db, db:
            saved = store.job(job['id'])
            saved['plan']['options']['certificate_type'] = 'ip'
            db.execute('UPDATE jobs SET plan_json=? WHERE id=?',
                       (json.dumps(saved['plan']),job['id']))
        ssh = StubExecutor()
        runner = JobRunner(store, ssh)
        runner.enqueue(store.job(job['id']), host,
                       'DEPLOY 3x-ui TO panel.example.com')
        for _ in range(100):
            if store.job(job['id'])['status'] == 'failed':
                break
            sleep(.01)
        wait_for_worker(runner, host['id'])
        assert store.job(job['id'])['status'] == 'failed'
        assert ssh.scripts == []


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
        with closing(sqlite3.connect(s.path)) as db, db:
            job=s.job(j['id'])
            job['plan']['steps'][0]['script']='echo MALICIOUS'
            db.execute('UPDATE jobs SET plan_json=? WHERE id=?',(json.dumps(job['plan']),j['id']))
        fake=StubExecutor()
        runner=JobRunner(s,fake)
        runner.enqueue(s.job(j['id']),h,'DEPLOY sing-box TO example.com')
        for _ in range(100):
            if s.job(j['id'])['status']=='failed':break
            sleep(.01)
        wait_for_worker(runner, h['id'])
        assert s.job(j['id'])['status']=='failed'
        assert fake.scripts==[]
