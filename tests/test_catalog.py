from app.catalog import build_plan, compatibility, CATALOG
from app.executor import validate_host
import pytest

GOOD = {"OS_ID":"debian", "ARCH":"x86_64", "UID":"0", "FREE_KB":"3000000", "DOCKER":"yes", "COMPOSE":"yes", "UDP_51820":"free", "SYSTEMD":"yes"}


def test_catalog_has_four_known_projects():
    assert set(CATALOG) == {"3x-ui", "sing-box", "hysteria2", "wg-easy"}


def test_only_two_recipes_executable():
    assert set(p for p in CATALOG if build_plan(p,GOOD)['executable']) == {'wg-easy','sing-box'}


def test_incompatible_distro_blocks_package_install():
    plan = build_plan('sing-box', dict(GOOD, OS_ID='alpine'))
    assert not plan['executable']
    assert not plan['steps']


def test_missing_docker_blocks_wg_easy():
    plan = build_plan('wg-easy', dict(GOOD, DOCKER='no'))
    assert not plan['eligible'] and not plan['executable']


def test_non_root_blocks_install():
    plan=build_plan('sing-box',dict(GOOD, UID='1000'))
    assert not plan['executable']


def test_failed_guard_has_no_remote_steps():
    for p in CATALOG:
        x=build_plan(p, dict(GOOD, ARCH='mips'))
        assert not x['executable'] and not x['steps']


@pytest.mark.parametrize('hostname,username,port',[
    ('-evil.com','root',22),('example.com;id','root',22),('example..com','root',22),
    ('safe.com','root;id',22),('safe.com','root',65536),('safe.com','root',0),
    ('10.0.0.1 | bash','root',22)
])
def test_rejects_host_shell_injection(hostname,username,port):
    with pytest.raises(ValueError):validate_host(hostname,username,port)


def test_accepts_normal_hostnames():
    validate_host('example.com','root',22)
    validate_host('203.0.113.11','ubuntu',2200)


def test_shell_scripts_are_fixed_and_contain_no_user_input():
    p=build_plan('wg-easy',GOOD)
    assert p['steps']
    assert all('NETDEPLOY' in s['script'] or 'docker' in s['script'] for s in p['steps'])
    assert '127.0.0.1:51821' in p['steps'][1]['script']
