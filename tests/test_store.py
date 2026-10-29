from app.store import Store
from app.catalog import build_plan
from tempfile import TemporaryDirectory
from pathlib import Path

GOOD = {'OS_ID':'ubuntu','ARCH':'x86_64','UID':'0','DOCKER':'yes','COMPOSE':'yes','SYSTEMD':'yes','UDP_51820':'free'}


def test_store_creates_hosts_and_single_approval():
    with TemporaryDirectory() as td:
        s=Store(str(Path(td)/'data.db'))
        host=s.add_host({'name':'vps','hostname':'example.com','port':22,'username':'root'})
        s.save_facts(host['id'],GOOD)
        job=s.new_job(host['id'],'sing-box',build_plan('sing-box',GOOD))
        assert s.job(job['id'])['status']=='planned'
        assert s.approve(job['id']) is True
        assert s.approve(job['id']) is False
        s.log(job['id'],'checking')
        assert 'checking' in s.job(job['id'])['logs']


def test_interrupted_jobs_never_auto_resume():
    with TemporaryDirectory() as td:
        path=str(Path(td)/'state.db')
        s=Store(path)
        host=s.add_host({'name':'vps','hostname':'example.com','port':22,'username':'root'})
        job=s.new_job(host['id'],'sing-box',build_plan('sing-box',GOOD))
        s.approve(job['id'])
        recovered=Store(path)
        assert recovered.job(job['id'])['status']=='interrupted'
