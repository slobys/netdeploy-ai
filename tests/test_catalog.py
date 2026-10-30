from app.catalog import build_plan, compatibility, CATALOG
from app.executor import validate_host
import pytest

GOOD = {"OS_ID":"debian", "ARCH":"x86_64", "UID":"0", "FREE_KB":"3000000", "DOCKER":"yes", "COMPOSE":"yes", "UDP_51820":"free", "SYSTEMD":"yes", "XUI_PRESENT":"no", "SS_AVAILABLE":"yes", "SUI_PRESENT":"no", "DOCKGE_PRESENT":"no", "DOCKGE_TCP_5001":"free"}


def test_catalog_has_four_known_projects():
    assert set(CATALOG) == {"3x-ui", "3x-ui-https", "sing-box", "hysteria2", "wg-easy", "s-ui", "s-ui-https", "dockge"}


def test_supported_recipes_executable():
    assert set(p for p in CATALOG if not CATALOG[p].get('internal') and build_plan(p,GOOD)['executable']) == {'3x-ui','wg-easy','sing-box','s-ui','dockge'}


def test_xui_pinned_install_plan_requires_compatibility():
    from app.three_x_ui import VERSION, INSTALLER_SHA256
    facts=dict(GOOD, OS_ID='ubuntu', OS_VERSION='26.10', DOCKER='no', COMPOSE='no')
    plan=build_plan('3x-ui',facts,{'panel_port':25443})
    assert plan['executable'] is True
    assert plan['options']=={'panel_port':25443}
    assert len(plan['steps'])==5
    scripts='\n'.join(s['script'] for s in plan['steps'])
    assert VERSION in scripts and INSTALLER_SHA256 in scripts
    assert 'XUI_NONINTERACTIVE=1' in scripts
    assert 'XUI_SSL_MODE=none' in scripts
    assert 'XUI_PANEL_PORT=25443' in scripts
    assert 'XUI_ENABLE_FAIL2BAN=false' in scripts
    assert 'bind_local="y"' in scripts
    assert 'systemctl stop x-ui' in scripts
    assert '127.0.0.1:25443' in scripts
    assert 'docker' not in scripts.lower()


@pytest.mark.parametrize('change', [
    {'OS_ID':'alpine'}, {'ARCH':'mips'}, {'UID':'1000'}, {'SYSTEMD':'no'},
    {'XUI_PRESENT':'yes'}, {'XUI_PRESENT':'unknown'}, {'SS_AVAILABLE':'no'},
    {'FREE_KB':'100000'}
])
def test_xui_safely_blocked_if_host_does_not_match(change):
    plan=build_plan('3x-ui',dict(GOOD,**change))
    assert not plan['executable'] and plan['steps']==[]


@pytest.mark.parametrize('bad_port', [0,22,1023,65536,'24443',True,None,24443.5,'$(id)'])
def test_xui_port_rejects_invalid_input(bad_port):
    with pytest.raises(ValueError):
        build_plan('3x-ui', GOOD, {'panel_port':bad_port})


def test_xui_rejects_unknown_options_and_other_projects_reject_custom_options():
    with pytest.raises(ValueError):
        build_plan('3x-ui', GOOD, {'panel_port':24443,'inject':'echo hi'})
    with pytest.raises(ValueError):
        build_plan('wg-easy', GOOD, {'panel_port':24443})


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
        if CATALOG[p].get('internal'): continue  # Internal HTTPS upgrades need a validated live managed installation.
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
