"""Safe one-approval Docker Engine + Compose bootstrap for Dockge Apps.

Tests are offline: no apt, systemd, Docker, SSH or VPS changes are executed.
"""
import shutil
import subprocess
import sys

import pytest

from app.catalog import build_plan
from app.docker_runtime import (
    PRISTINE, ENV_CHECK, OS_GUARD, DOWNLOAD_OFFICIAL, RUN_OFFICIAL,
    extra_steps, setup_mode,
)
from app.executor import SSHExecutor


BASE = {
    "OS_ID":"debian", "OS_VERSION":"13", "ARCH":"x86_64", "UID":"0",
    "FREE_KB":"6500000", "DOCKER":"no", "COMPOSE":"no",
    "DOCKER_SETUP":"clean", "GIT_AVAILABLE":"no", "SYSTEMD":"yes",
    "SS_AVAILABLE":"yes", "DOCKGE_PRESENT":"no", "DOCKGE_TCP_5001":"free",
}


def test_pristine_vps_combines_full_bootstrap_and_dockge_with_one_approval():
    plan = build_plan("dockge", BASE)
    assert plan["eligible"] and plan["executable"] and plan["issues"] == []
    assert len(plan["steps"]) == 8
    assert plan["options"] == {}
    labels = [step["label"] for step in plan["steps"]]
    assert "Docker" in labels[0]
    assert "Docker Engine" in labels[2] and "Compose v2" in labels[2]
    assert "Dockge" in labels[-1]
    combined = "\n".join(step["script"] for step in plan["steps"])
    assert "https://get.docker.com" in combined
    assert "sh -n" in combined and "--dry-run" in combined
    assert 'sh "$script"' in combined
    assert "sha256sum -c --status" in combined
    assert "docker-compose-plugin" in combined
    assert "docker compose version" in combined
    assert "docker buildx version" in combined
    assert "docker compose" in combined
    assert "DOCKGE_APPS_READY" in combined
    assert "curl --proto '=https'" in combined
    assert "https://get.docker.com" in DOWNLOAD_OFFICIAL
    assert "netdeploy_docker_pristine" in RUN_OFFICIAL
    assert "netdeploy_docker_pristine" in combined
    assert "ND_DOCKER_APT_REMOVAL_BLOCKED" in combined
    for forbidden in ("curl -fsSL https://get.docker.com | bash",
                      "curl | bash", "ufw disable", "apt-get purge",
                      "docker system prune", "docker compose down",
                      "docker volume rm", "rm -rf /var/lib/docker",
                      "apt-get remove", "docker-compose-linux-x86_64"):
        assert forbidden not in combined
    assert "Docker" in " ".join(plan["warnings"])


def test_existing_healthy_docker_is_not_reinstalled():
    facts = dict(BASE, DOCKER="yes", COMPOSE="yes",
                 DOCKER_SETUP="ready", GIT_AVAILABLE="yes")
    plan = build_plan("dockge", facts)
    assert plan["executable"]
    assert len(plan["steps"]) == 4
    assert plan["steps"][0]["label"].startswith("检查 Docker")
    assert "apt-get" not in "\n".join(s["script"] for s in plan["steps"])


def test_compose_only_installs_cli_plugin_not_a_new_engine():
    facts = dict(BASE, DOCKER="yes", COMPOSE="no",
                 DOCKER_SETUP="compose", GIT_AVAILABLE="yes")
    plan = build_plan("dockge", facts)
    assert plan["executable"] and len(plan["steps"]) == 7
    setup = "\n".join(s["script"] for s in plan["steps"][:3])
    assert "docker-compose-plugin" in setup
    assert "docker-buildx-plugin" in setup
    assert "docker-ce docker-ce-cli" not in setup
    assert "docker info" in setup
    assert "ND_DOCKER_EXISTING_ENGINE_UNSUPPORTED" in setup
    assert "ND_DOCKER_ENGINE_CHANGE_BLOCKED" in setup
    assert "apt-get -s" in setup
    assert "download.docker.com/linux/$ID/gpg" not in setup


def test_git_only_install_preserves_docker():
    facts = dict(BASE, DOCKER="yes", COMPOSE="yes",
                 DOCKER_SETUP="ready", GIT_AVAILABLE="no")
    plan = build_plan("dockge", facts)
    assert plan["executable"] and len(plan["steps"]) == 7
    setup = "\n".join(s["script"] for s in plan["steps"][:3])
    assert "apt-get" in setup and "git" in setup
    assert "docker-ce docker-ce-cli" not in setup
    assert "docker buildx version" in setup


@pytest.mark.parametrize("change", [
    {"DOCKER_SETUP":"blocked"},
    {"DOCKER_SETUP":"missing"},
    {"DOCKER_SETUP":None},
    {"DOCKER":"yes","COMPOSE":"no","DOCKER_SETUP":"blocked"},
    {"DOCKER":"no","COMPOSE":"yes","DOCKER_SETUP":"clean"},
    {"DOCKER":"yes","COMPOSE":"yes","DOCKER_SETUP":"blocked"},
    {"DOCKGE_PRESENT":"yes"},
    {"DOCKGE_TCP_5001":"busy"},
    {"SYSTEMD":"no"},
    {"OS_ID":"alpine"},
    {"OS_VERSION":"11"},
    {"FREE_KB":"3500000"},
    {"ARCH":"mips"},
])
def test_unknown_conflicting_or_unsupported_docker_never_installs(change):
    plan = build_plan("dockge", {**BASE, **change})
    assert not plan["executable"]
    assert not plan["steps"]
    assert plan["issues"]


def test_prereq_metadata_does_not_accept_user_shell_options():
    for value in ({"auto_install":"curl|bash"}, {"docker_script":"id"},
                  {"docker_version":"latest"}, {"docker_setup":"fresh"}):
        with pytest.raises(ValueError):
            build_plan("dockge", BASE, value)


def test_read_only_preflight_reports_docker_install_state():
    class Fake:
        def run(self, host, script, timeout):
            assert "netdeploy_docker_pristine" in script
            assert "DOCKER_SETUP=clean" in script
            return ("OS_ID=debian\nOS_VERSION=13\nARCH=x86_64\nUID=0\n"
                    "DOCKER=no\nCOMPOSE=no\nDOCKER_SETUP=clean\n"
                    "GIT_AVAILABLE=no\nSS_AVAILABLE=yes\n"
                    "DOCKGE_PRESENT=no\nDOCKGE_TCP_5001=free\nFREE_KB=7000000\n"
                    "SYSTEMD=yes\n")
    facts = SSHExecutor.preflight(Fake(), {"hostname":"203.0.113.11"})
    assert facts["DOCKER_SETUP"] == "clean"
    assert facts["DOCKER"] == "no"
    assert facts["COMPOSE"] == "no"


def test_setup_mode_is_derived_from_detected_facts_not_user_flags():
    assert setup_mode(BASE) == "fresh"
    assert setup_mode(dict(BASE, DOCKER_SETUP="blocked")) == "blocked"
    assert setup_mode(dict(BASE, DOCKER="yes", COMPOSE="yes",
                           DOCKER_SETUP="ready", GIT_AVAILABLE="yes")) == "ready"
    assert setup_mode(dict(BASE, DOCKER="yes", COMPOSE="yes",
                           DOCKER_SETUP="ready", GIT_AVAILABLE="no")) == "git"
    assert len(extra_steps(BASE)) == 4
    with pytest.raises(ValueError):
        extra_steps(dict(BASE, DOCKER_SETUP="blocked"))


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"),
                    reason="Generated remote Bash requires Linux Bash")
def test_every_generated_step_parses_as_bash():
    versions = (
        BASE,
        dict(BASE, DOCKER="yes", COMPOSE="no", DOCKER_SETUP="compose"),
        dict(BASE, DOCKER="yes", COMPOSE="yes", DOCKER_SETUP="ready", GIT_AVAILABLE="no"),
    )
    for facts in versions:
        for stage in build_plan("dockge", facts)["steps"]:
            r = subprocess.run(["bash", "-n"], input=stage["script"],
                               capture_output=True, text=True)
            assert r.returncode == 0, (stage["label"], r.stderr)
    for raw in (PRISTINE, ENV_CHECK, OS_GUARD, DOWNLOAD_OFFICIAL, RUN_OFFICIAL):
        r = subprocess.run(["bash", "-n"], input=raw, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
