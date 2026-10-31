"""NetDeploy AI API, single-admin prototype. Do not expose directly to public Internet."""
from __future__ import annotations

import os
import re
import ipaddress
import secrets
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pydantic.types import StrictInt

from .three_x_ui import ACCESS_SCRIPT, DEFAULT_PORT, parse_access_result

from .catalog import CATALOG, build_plan
from .executor import SSHConfig, SSHError, SSHExecutor, validate_host
from .store import Store
from .tasks import JobRunner
from .ai import diagnose
from .os_keyring import VaultUnavailable
from .https_upgrade import identify, https_access_script, https_url
from .firewall import (PortRule, FirewallBatch, STATUS_SCRIPT, allow_port_script,
                       allow_ports_script, parse_firewall_batch_output,
                       FirewallToggle, firewall_toggle_script)
from .xui_existing import status_script, parse_status, public_access_script, direct_url
from .s_ui import (PORT as SUI_PORT, STATUS as SUI_STATUS_SCRIPT, ACCESS as SUI_ACCESS_SCRIPT,
                   parse_status as parse_sui_status, parse_access as parse_sui_access)
from .dockge import (PORT as DOCKGE_PORT, STATUS as DOCKGE_STATUS_SCRIPT,
                     parse_status as parse_dockge_status, local_access as dockge_local_access)

BASE = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("NETDEPLOY_DATA", str(BASE.parent / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
ADMIN_TOKEN = os.getenv("NETDEPLOY_ADMIN_TOKEN", "")
if len(ADMIN_TOKEN) < 24 or ADMIN_TOKEN.startswith("REPLACE_"):
    raise RuntimeError("必须配置长度至少 24 字符的 NETDEPLOY_ADMIN_TOKEN")

store = Store(str(DATA_DIR / "netdeploy.db"))
executor = SSHExecutor(SSHConfig(
    keyfile=os.getenv("NETDEPLOY_SSH_KEY_FILE", "/run/secrets/ssh_key"),
    known_hosts=str(DATA_DIR / "known_hosts"),
))
runner = JobRunner(store, executor)
app = FastAPI(title="NetDeploy AI", version="0.3.25")
LOCAL_AUTO_LOGIN = os.getenv("NETDEPLOY_LOCAL_AUTO_LOGIN", "0") == "1"

@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


def authorized(x_admin_token: str | None = Header(default=None)):
    if x_admin_token is None or not secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="管理员令牌不正确")


class HostCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    hostname: str = Field(min_length=1, max_length=253)
    tls_domain: str | None = Field(default=None, max_length=253)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(default="root", min_length=1, max_length=32)
    auth_mode: Literal["key", "password"] = "key"
    password: str | None = None
    remember_password: bool = False


class HostCredentials(BaseModel):
    auth_mode: Literal["key", "password"]
    password: str | None = None
    remember_password: bool = False


class HostEdit(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    hostname: str = Field(min_length=1, max_length=253)
    tls_domain: str | None = Field(default=None, max_length=253)
    port: StrictInt = Field(ge=1, le=65535)
    username: str = Field(min_length=1, max_length=32)


class DeleteHostConfirmation(BaseModel):
    confirmation: str
    delete_local_history: bool = False


class HostRekeyConfirmation(BaseModel):
    fingerprint: str
    previous_fingerprints: list[str] = Field(min_length=1, max_length=6)
    confirmed_out_of_band: bool = False
    confirmation: str



class TrustKey(BaseModel):
    fingerprint: str
    confirmed_out_of_band: bool = False


class NewJob(BaseModel):
    host_id: int
    project: str
    panel_port: StrictInt | None = Field(default=None, ge=1024, le=65535)
    access_mode: Literal["local", "https", "public"] | None = None
    confirm_public: bool = False
    source_job_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")


class Approval(BaseModel):
    confirmation: str = ''  # Legacy explicit typed phrase remains accepted
    confirmed_risk: bool = False  # Single-click approval after reviewing fixed plan


class DeleteJobConfirmation(BaseModel):
    confirmation: str


def find_host(id: int):
    host = store.host(id)
    if host is None:
        raise HTTPException(status_code=404, detail="服务器不存在")
    return host


def require_password(password: str | None) -> str:
    # Explicit validation prevents a framework validation error from echoing
    # a long secret value in its JSON response.
    if not password or len(password) > 1024:
        raise HTTPException(status_code=422, detail="SSH 密码长度必须在 1 到 1024 字符之间")
    return password


def normalize_tls_domain(raw: str | None, ssh_hostname: str) -> str | None:
    """TLS is optional and independent of the pinned SSH address.

    A configured domain must point to a publicly reachable SSH IPv4 VPS;
    the actual DNS A / public IP match is rechecked in the fixed remote
    ACME preflight before requesting any certificate.
    """
    if raw is None or not raw.strip():
        return None
    mode, domain = identify(raw)
    if mode != "domain":
        raise ValueError("可选证书地址只能填写域名；不填域名时自动使用服务器 IPv4 申请 IP 证书")
    ip_mode, _ = identify(ssh_hostname)
    if ip_mode != "ip":
        raise ValueError("填写证书域名时，SSH 服务器地址请使用公网 IPv4；域名只用于 HTTPS 证书")
    return domain


def tls_identity(host: dict) -> str:
    return host.get("tls_domain") or host["hostname"]


def tls_options(host: dict) -> dict:
    """Freeze separately reviewed TLS identity and SSH IP into plan options."""
    result = {"tls_identity": tls_identity(host)}
    if host.get("tls_domain"):
        result["ssh_ipv4"] = host["hostname"]
    return result


def public_host(host: dict) -> dict:
    # Never return the SSH password or any credential content through this API.
    remembered = getattr(executor, "password_remembered", lambda _id: False)
    return {**host, "credential_ready": executor.credential_ready(host),
            "job_count": store.host_job_count(host["id"]),
            "password_remembered": bool(remembered(host["id"])) if host.get("auth_mode") == "password" else False}


def find_job(id: str):
    job = store.job(id)
    if job is None:
        raise HTTPException(status_code=404, detail="部署任务不存在")
    return job


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "version": "0.3.25", "security": "local-only"}


@app.get("/api/local-session")
def local_session(request: Request, x_netdeploy_local: str | None = Header(default=None)):
    """Opt-in auto-login for a *loopback-only* single-user Windows process.

    Do not expose this listener through any reverse proxy or public port.
    The caller must be local and same-origin; never put the admin token in a
    redirect, URL, HTML, cookie or server log.
    """
    if not LOCAL_AUTO_LOGIN or x_netdeploy_local != "1":
        raise HTTPException(status_code=403, detail="本机免登录模式未启用")
    client = request.client.host if request.client else ""
    host = request.headers.get("host", "").lower()
    allowed_hosts = {"127.0.0.1:8787", "localhost:8787"}
    origin = request.headers.get("origin", "")
    fetch_site = request.headers.get("sec-fetch-site", "")
    if (client not in {"127.0.0.1", "::1"} or host not in allowed_hosts
            or (origin and origin != "http://" + host)
            or (fetch_site and fetch_site != "same-origin")):
        raise HTTPException(status_code=403, detail="仅限本机同源浏览器自动登录")
    return {"token": ADMIN_TOKEN, "mode": "loopback-only"}


@app.get("/api/auth", dependencies=[Depends(authorized)])
def auth():
    return {"ok": True}


@app.get("/api/catalog", dependencies=[Depends(authorized)])
def catalog():
    return CATALOG


@app.get("/api/capabilities", dependencies=[Depends(authorized)])
def capabilities():
    vault = getattr(executor, "vault", None)
    return {"secure_password_storage": bool(getattr(vault, "available", False))}


@app.get("/api/hosts", dependencies=[Depends(authorized)])
def list_hosts():
    return [public_host(host) for host in store.hosts()]


@app.post("/api/hosts", dependencies=[Depends(authorized)])
def create_host(body: HostCreate):
    try:
        validate_host(body.hostname, body.username, body.port)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        domain = normalize_tls_domain(body.tls_domain, body.hostname)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.auth_mode == "password":
        require_password(body.password)
        if body.remember_password and not executor.vault.available:
            raise HTTPException(status_code=422, detail="此设备未启用 Windows 系统凭据保管库，请选择临时密码登录")
    # Do not pass credentials into the database, responses, plan or logs.
    data = body.model_dump(exclude={"password"})
    data["tls_domain"] = domain
    host = store.add_host(data)
    if body.auth_mode == "password":
        try:
            executor.set_password(host["id"], body.password, remember=body.remember_password)
        except VaultUnavailable as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return public_host(host)


@app.put("/api/hosts/{id}", dependencies=[Depends(authorized)])
def edit_host(id: int, body: HostEdit):
    original = find_host(id)
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="服务器名称不能为空")
    try:
        validate_host(body.hostname, body.username, body.port)
        selected_domain = (
            normalize_tls_domain(body.tls_domain, body.hostname)
            if "tls_domain" in body.model_fields_set
            else original.get("tls_domain")
        )
        if selected_domain is not None:
            selected_domain = normalize_tls_domain(selected_domain, body.hostname)
        endpoint_changed = (
            original["hostname"].lower() != body.hostname.lower()
            or int(original["port"]) != body.port
            or original["username"] != body.username
        )
        with store.lock:
            if endpoint_changed and store.host_job_count(id):
                raise ValueError("该 VPS 有部署历史，只能修改名称。若改 IP / 端口 / 账号，请新建服务器以保留旧任务安全记录")
            if endpoint_changed:
                executor.clear_password(id)
            host = store.update_host(id, body.name.strip(), body.hostname.strip(),
                                     body.port, body.username.strip(), selected_domain)
    except (ValueError, VaultUnavailable) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return public_host(host)


@app.delete("/api/hosts/{id}", dependencies=[Depends(authorized)])
def delete_host(id: int, body: DeleteHostConfirmation):
    host = find_host(id)
    if body.confirmation != f"DELETE VPS {id}":
        raise HTTPException(status_code=409, detail="确认语句错误；删除只清理本地 VPS 记录，不会卸载远端软件")
    try:
        with store.lock:
            if store.has_active_endpoint_jobs(host["hostname"], host["port"]):
                # All records at a shared endpoint have a common trust pin.
                raise ValueError("该 SSH 地址还有执行中或排队任务，禁止删除服务器")
            count = store.host_job_count(id)
            if count and not body.delete_local_history:
                raise ValueError(f"此 VPS 有 {count} 条部署历史，请明确同意删除历史记录与日志")
            executor.clear_password(id)
            result = store.delete_host(id, body.delete_local_history)
    except (ValueError, VaultUnavailable) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {**result, "hostkey_retained": True}


@app.put("/api/hosts/{id}/credentials", dependencies=[Depends(authorized)])
def update_credentials(id: int, body: HostCredentials):
    find_host(id)
    if body.auth_mode == "password":
        require_password(body.password)
    try:
        # Preserve existing facts when merely refreshing the same password
        # login method. A different auth mode still invalidates cached facts.
        host = store.update_auth(id, body.auth_mode)
        if body.auth_mode == "password":
            executor.set_password(id, body.password, remember=body.remember_password)
        else:
            executor.clear_password(id)
    except VaultUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return public_host(host)


@app.post("/api/hosts/{id}/fingerprint", dependencies=[Depends(authorized)])
def fingerprint(id: int):
    host = find_host(id)
    try:
        data = executor.scan_hostkey(host)
        saved = getattr(executor, "pinned_hostkeys", lambda _host: [])(host)
        return {
            "fingerprint": data["fingerprint"],
            "key_type": data.get("key_type", "ssh-ed25519"),
            "previous_fingerprints": saved,
            "changed": bool(saved and data["fingerprint"] not in
                            [entry["fingerprint"] for entry in saved]),
            "shared_host_count": len(store.endpoint_hosts(host["hostname"], host["port"])),
            "warning": "扫描值未经身份认证，VPS 重装后必须在云厂商独立控制台重新核对新指纹；无法自动接受变更。",
        }
    except SSHError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/hosts/{id}/trust", dependencies=[Depends(authorized)])
def trust(id: int, body: TrustKey):
    host = find_host(id)
    if not body.confirmed_out_of_band:
        raise HTTPException(status_code=422, detail="必须确认已通过独立渠道核实主机指纹")
    if not re.fullmatch(r"SHA256:[A-Za-z0-9+/=]{24,80}", body.fingerprint):
        raise HTTPException(status_code=422, detail="指纹格式不正确")
    try:
        return executor.trust_hostkey(host, body.fingerprint)
    except SSHError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/hosts/{id}/rekey", dependencies=[Depends(authorized)])
def rekey_host(id: int, body: HostRekeyConfirmation):
    host = find_host(id)
    if not body.confirmed_out_of_band:
        raise HTTPException(status_code=409, detail="必须独立登录 VPS 云控制台核对新的 SHA256 主机指纹")
    if not re.fullmatch(r"SHA256:[A-Za-z0-9+/=]{24,80}", body.fingerprint):
        raise HTTPException(status_code=422, detail="新指纹格式不合法")
    if body.confirmation != f"REKEY {host['hostname']}:{host['port']}":
        raise HTTPException(status_code=409, detail="SSH 信任确认信息与当前 VPS 地址及端口不匹配")
    try:
        with store.lock:
            if store.has_active_endpoint_jobs(host["hostname"], host["port"]):
                raise ValueError("此 IP/端口还有执行中的部署任务，禁止重置 SSH 信任")
            result = executor.rekey_host(
                host, body.fingerprint, body.previous_fingerprints,
                on_verified=lambda: store.invalidate_endpoint_trust(
                    host["hostname"], int(host["port"])
                ),
            )
    except (SSHError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {**result, "old_plans_invalidated": True}


@app.post("/api/hosts/{id}/preflight", dependencies=[Depends(authorized)])
def preflight(id: int):
    host = find_host(id)
    try:
        facts = executor.preflight(host)
        return store.save_facts(id, facts)
    except (ValueError, SSHError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def read_existing_xui(host: dict) -> dict:
    """Read-only inspection under pinned SSH trust; no saved passwords returned."""
    if not executor.credential_ready(host):
        raise HTTPException(status_code=409, detail="SSH 登录凭据不可用，请先检查本机凭据库")
    try:
        raw = executor.run(host, status_script(tls_identity(host)), timeout=26)
        return parse_status(raw)
    except (SSHError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"无法读取现有 3X-UI 状态：{exc}") from exc


@app.get("/api/hosts/{id}/3x-ui", dependencies=[Depends(authorized)])
def xui_status(id: int):
    """Existing installation status never requires a deployment approval."""
    host = find_host(id)
    return read_existing_xui(host)


@app.get("/api/hosts/{id}/3x-ui/access", dependencies=[Depends(authorized)])
def xui_existing_access(id: int):
    """Only an explicit authenticated click can retrieve initial credentials."""
    host = find_host(id)
    status = read_existing_xui(host)
    if not status["installed"]:
        raise HTTPException(status_code=409, detail="此 VPS 尚未安装 3X-UI")
    if status["service"] != "active":
        raise HTTPException(status_code=409, detail="3X-UI 服务未启动，请先在 VPS 上检查 systemctl status x-ui")
    if not status["managed"]:
        raise HTTPException(
            status_code=409,
            detail="已检测到 3X-UI，但没有可安全读取的原始安装凭据。请在 VPS 控制台执行 x-ui settings 查看或更新登录设置；不会重装或猜测密码",
        )
    port = status["port"]
    try:
        if status["access_mode"] == "https":
            script = public_access_script(tls_identity(host), port)
        elif status["access_mode"] == "local":
            script = ACCESS_SCRIPT
        else:
            raise ValueError("管理面板的当前监听或 HTTPS 证书尚未验证，不能生成不安全的直连地址")
        result = parse_access_result(executor.run(host, script, timeout=26), port)
    except (SSHError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=f"无法安全读取安装时的面板信息：{exc}") from exc
    if status["access_mode"] == "https":
        result["direct_url"] = direct_url(tls_identity(host), port, result["web_path"])
        result["access_mode"] = "https"
    else:
        result["ssh_tunnel"] = (
            f"ssh -N -p {host['port']} -L {port}:127.0.0.1:{port} "
            f"{host['username']}@{host['hostname']}"
        )
        result["access_mode"] = "local"
    result["initial_credentials_only"] = True
    return result


def read_existing_sui(host: dict) -> dict:
    """Status-only; the admin password is never retrieved by this action."""
    if not executor.credential_ready(host):
        raise HTTPException(status_code=409, detail="SSH 登录凭据不可用，请先验证可信 VPS")
    try:
        return parse_sui_status(executor.run(host, SUI_STATUS_SCRIPT, timeout=25))
    except (SSHError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"无法读取 S-UI 当前状态：{exc}") from exc


@app.get("/api/hosts/{id}/s-ui", dependencies=[Depends(authorized)])
def sui_status(id: int):
    return read_existing_sui(find_host(id))


@app.get("/api/hosts/{id}/s-ui/access", dependencies=[Depends(authorized)])
def sui_access(id: int):
    """Explicit user action; no credentials in stored plan, task logs or AI."""
    host = find_host(id)
    status = read_existing_sui(host)
    if not status["installed"]:
        raise HTTPException(status_code=409, detail="尚未安装 S-UI")
    if status["service"] != "active" or not status["managed"] or status["access_mode"] not in {"local", "https"}:
        raise HTTPException(status_code=409, detail="S-UI 的本机监听或可信 HTTPS 尚未验证；不会提供不安全的直连地址")
    try:
        result = parse_sui_access(executor.run(host, SUI_ACCESS_SCRIPT, timeout=35), host)
    except (SSHError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="无法安全读取 S-UI 初始凭据；请在 VPS 控制台检查安装记录") from exc
    if result["access_mode"] != status["access_mode"] or (
        result["access_mode"] == "https" and result.get("certificate_identity") != status.get("identity")
    ):
        raise HTTPException(status_code=409, detail="S-UI 的 HTTPS 身份或监听在检查时发生变化，请刷新后重试")
    return result


def read_existing_dockge(host: dict) -> dict:
    """Only read current Dockge state through trusted SSH, never Docker secrets."""
    if not executor.credential_ready(host):
        raise HTTPException(status_code=409, detail="SSH 登录凭据不可用，请先验证可信 VPS")
    try:
        return parse_dockge_status(executor.run(host, DOCKGE_STATUS_SCRIPT, timeout=35))
    except (SSHError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"无法验证 Dockge Apps 运行与本机端口状态：{exc}") from exc


@app.get("/api/hosts/{id}/dockge", dependencies=[Depends(authorized)])
def dockge_status(id: int):
    return read_existing_dockge(find_host(id))


@app.get("/api/hosts/{id}/dockge/access", dependencies=[Depends(authorized)])
def dockge_access(id: int):
    """Explicit action; refuse any untrusted or public HTTP management access."""
    host = find_host(id)
    status = read_existing_dockge(host)
    if not status["installed"]:
        raise HTTPException(status_code=409, detail="此 VPS 尚未安装 Dockge Apps")
    if not status["managed"] or status["service"] != "active" or status["access_mode"] not in {"local", "public"}:
        raise HTTPException(status_code=409, detail="Dockge Apps 访问端口或监听状态未通过安全校验")
    return dockge_local_access(host, status)


@app.get("/api/hosts/{id}/firewall", dependencies=[Depends(authorized)])
def firewall_status(id: int):
    host = find_host(id)
    if not executor.credential_ready(host):
        raise HTTPException(status_code=409, detail="SSH 登录凭据不可用；请先连接可信 VPS")
    try:
        raw = executor.run(host, STATUS_SCRIPT, timeout=25)
    except (SSHError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"无法检查 UFW 状态：{exc}") from exc
    if raw.startswith("FIREWALL=active"):
        mode = "active"
    elif raw.startswith("FIREWALL=inactive"):
        mode = "inactive"
    elif raw.startswith("FIREWALL=unavailable"):
        mode = "unavailable"
    else:
        mode = "unknown"
    return {"status": mode, "details": raw[:4000],
            "cloud_notice": "此处仅管理 VPS 内的 UFW；云厂商安全组需要单独放行端口"}


@app.post("/api/hosts/{id}/firewall/allow", dependencies=[Depends(authorized)])
def firewall_allow(id: int, body: PortRule):
    host = find_host(id)
    if not body.confirmation:
        raise HTTPException(status_code=409, detail="请明确确认放行指定协议/端口")
    if not executor.credential_ready(host):
        raise HTTPException(status_code=409, detail="SSH 登录凭据不可用；请先连接可信 VPS")
    try:
        script = allow_port_script(body.port, body.protocol)
        with store.lock:
            if store.has_active_endpoint_jobs(host["hostname"], host["port"]):
                raise ValueError("VPS 正在执行部署任务，请先检查任务完成状态再修改端口")
            result = executor.run(host, script, timeout=40)
    except (SSHError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"放行端口失败：{exc}") from exc
    mode = "active" if "UFW_ALLOWED" in result else "inactive_or_unavailable"
    return {"ok": True, "port": body.port, "protocol": body.protocol,
            "mode": mode, "message": result.strip()[:800],
            "cloud_notice": "本机规则已处理，但云服务器安全组仍需另行允许对应入站端口"}


@app.post("/api/hosts/{id}/firewall/allow-batch", dependencies=[Depends(authorized)])
def firewall_allow_batch(id: int, body: FirewallBatch):
    """Apply up to 20 fully validated UFW rules in one trusted SSH session."""
    host = find_host(id)
    if not body.confirmation:
        raise HTTPException(status_code=409, detail="请确认批量放行所列出的端口")
    if not executor.credential_ready(host):
        raise HTTPException(status_code=409, detail="SSH 登录凭据不可用；请先验证可信 VPS")
    # Every rule and duplicate is rejected *before* connecting to the VPS.
    try:
        script = allow_ports_script(body.rules)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with store.lock:
        if store.has_active_endpoint_jobs(host["hostname"], host["port"]):
            raise HTTPException(status_code=409, detail="服务器存在执行中的部署任务，请先完成再修改端口")
        try:
            raw = executor.run(host, script, timeout=min(300, 30 + 12 * len(body.rules)))
        except (SSHError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"批量端口操作未能完整验证，可能有部分端口已生效；请先检查 VPS 的 UFW 规则：{exc}",
            ) from exc
    try:
        outcome = parse_firewall_batch_output(raw, body.rules)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "ok": outcome["failed"] == 0,
        **outcome,
        "cloud_notice": "仅更改 VPS 本机 UFW；云厂商安全组仍需分别允许对应入站端口",
    }


@app.post("/api/hosts/{id}/firewall/toggle", dependencies=[Depends(authorized)])
def firewall_toggle(id: int, body: FirewallToggle):
    """Explicit opt-in; does not disable or edit the provider's cloud ACLs."""
    host = find_host(id)
    if not body.confirmed_risk:
        raise HTTPException(status_code=409, detail="关闭整个 VPS 防火墙存在公网暴露风险，必须明确确认此操作")
    if not executor.credential_ready(host):
        raise HTTPException(status_code=409, detail="SSH 登录凭据不可用，拒绝修改防火墙")
    try:
        script = firewall_toggle_script(body.mode, int(host["port"]))
        with store.lock:
            if store.has_active_endpoint_jobs(host["hostname"], host["port"]):
                raise ValueError("当前服务器有部署中的任务，不能切换整个 UFW 状态")
            raw = executor.run(host, script, timeout=35)
    except (SSHError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"防火墙切换失败，状态未确认：{exc}") from exc
    expected = "inactive" if body.mode == "disable" else "active"
    try:
        verified = executor.run(host, STATUS_SCRIPT, timeout=20)
    except (SSHError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"命令已执行，但无法重新读取 UFW 状态：{exc}") from exc
    if not verified.startswith(f"FIREWALL={expected}"):
        raise HTTPException(status_code=409, detail="UFW 状态与目标不一致，请检查 VPS 控制台，不要连续重复操作")
    return {"ok": True, "mode": expected, "message": raw.strip()[:500],
            "cloud_notice": "仅更改 VPS 的 UFW 状态，云厂商安全组不受此操作影响"}


def job_recipe_changed(job: dict) -> bool:
    """Compare the stored, immutable script to the current reviewed recipe.

    Historical failures can originate from older scripts, not the currently
    running server. This read-only comparison must not alter the remote VPS,
    rewrite stored job history or automatically approve an updated plan.
    """
    host = store.host(job["host_id"])
    if not host or not host.get("facts"):
        return True
    saved = job.get("plan") or {}
    if saved.get("trust_epoch", 0) != host.get("trust_epoch", 0):
        return True
    try:
        current = build_plan(job["project"], host["facts"], saved.get("options"))
    except (ValueError, KeyError, TypeError):
        return True
    return current["steps"] != saved.get("steps") or current["executable"] != saved.get("executable")


def plan_needs_refresh(job: dict) -> bool:
    return job["status"] == "planned" and job_recipe_changed(job)


def public_job(job: dict) -> dict:
    return {
        **job,
        "needs_refresh": plan_needs_refresh(job),
        "historical_script": (
            job["status"] in {"failed", "partial", "interrupted"} and
            job_recipe_changed(job)
        ),
    }


@app.get("/api/jobs", dependencies=[Depends(authorized)])
def list_jobs():
    return [public_job(job) for job in store.jobs()]


def approval_baseline(facts: dict) -> dict:
    """Freeze safety-relevant facts, excluding free space's volatile exact value.

    Free space is still checked against the project's minimum when approving.
    All other observed fields are retained (including newly introduced flags),
    so they cannot silently change without a fresh deployment plan.
    """
    return {key: value for key, value in facts.items() if key != "FREE_KB"}


@app.post("/api/jobs", dependencies=[Depends(authorized)])
def new_job(body: NewJob):
    host = find_host(body.host_id)
    if body.project not in CATALOG:
        raise HTTPException(status_code=404, detail="不支持的项目")
    if not executor.credential_ready(host):
        raise HTTPException(status_code=409, detail="SSH 登录凭据不可用，请在服务器管理中设置登录方式")
    # Always refresh read-only facts when creating a new plan; cached results
    # from older app versions and program restarts cannot be silently reused.
    try:
        facts = executor.preflight(host)
    except (ValueError, SSHError) as exc:
        raise HTTPException(status_code=422, detail=f"自动环境检测失败：{exc}") from exc
    host = store.save_facts(host["id"], facts)
    options = None
    if body.project == "3x-ui":
        if body.source_job_id:
            raise HTTPException(status_code=422, detail="新安装不接受已有任务编号")
        if host["facts"].get("XUI_PRESENT") == "yes":
            raise HTTPException(status_code=409, detail="3X-UI 已安装，此处不再创建安装审批计划；请直接查看服务器上的现有面板信息")
        options = {"panel_port": body.panel_port if body.panel_port is not None else DEFAULT_PORT}
        if body.access_mode == "https":
            options.update({"access_mode": "https", **tls_options(host)})
        if options["panel_port"] == host["port"]:
            raise HTTPException(status_code=422, detail="面板端口不能与 VPS SSH 端口相同")
    elif body.project == "s-ui":
        if body.panel_port is not None or body.source_job_id:
            raise HTTPException(status_code=422, detail="S-UI 使用固定管理端口 2095，初次安装不能提供原任务编号")
        if host["port"] == SUI_PORT:
            raise HTTPException(status_code=422, detail="S-UI 管理端口 2095 与 SSH 端口相同，请先检查 VPS")
        if host["facts"].get("SUI_PRESENT") != "no":
            raise HTTPException(status_code=409, detail="S-UI 已安装或冲突检查不完整，请先查看现有面板；禁止覆盖重装")
        access_mode = body.access_mode or "https"
        options = {"access_mode": access_mode}
        if access_mode == "https":
            options.update(tls_options(host))
    elif body.project == "s-ui-https":
        if body.panel_port is not None or body.access_mode:
            raise HTTPException(status_code=422, detail="已安装 S-UI HTTPS 续接不允许覆盖端口或访问模式")
        if body.source_job_id:
            source = find_job(body.source_job_id)
            if source["plan"].get("trust_epoch", 0) != host.get("trust_epoch", 0):
                raise HTTPException(status_code=409, detail="原 S-UI 任务属于重装前的 VPS")
            if source["project"] != "s-ui" or source["host_id"] != host["id"] or source["status"] not in {"completed", "partial"}:
                raise HTTPException(status_code=409, detail="S-UI 原安装任务未完成，无法继续 HTTPS")
            if source["status"] == "completed" and source["plan"].get("options", {}).get("access_mode") == "https":
                raise HTTPException(status_code=409, detail="该 S-UI 原任务已经完成 HTTPS")
        existing = read_existing_sui(host)
        if (not existing["installed"] or not existing["managed"] or existing["service"] != "active"
                or existing["access_mode"] != "local"):
            raise HTTPException(status_code=409, detail="只允许对已验证且本机监听的 S-UI 继续配置 HTTPS；不会覆盖未知设置")
        options = {**tls_options(host)}
        if body.source_job_id:
            options["source_job_id"] = body.source_job_id
    elif body.project in {"dockge", "dockge-access"}:
        if body.source_job_id:
            raise HTTPException(status_code=422, detail="Dockge Apps 端口配置不接受原安装任务编号")
        host_port = body.panel_port if body.panel_port is not None else secrets.randbelow(40000) + 20000
        if host_port == int(host["port"]):
            raise HTTPException(status_code=422, detail="Dockge Apps 管理端口不能和 SSH 端口相同")
        mode = body.access_mode or "local"
        if mode not in {"public", "local"}:
            raise HTTPException(status_code=422, detail="Dockge Apps 不支持该访问方式")
        if mode == "public":
            if not body.confirm_public:
                raise HTTPException(status_code=422, detail="公网直连需要明确确认 Docker 高权限、HTTP 风险及管理员初始化状态")
            try:
                ipv4 = ipaddress.ip_address(host["hostname"])
                if not isinstance(ipv4, ipaddress.IPv4Address) or not ipv4.is_global:
                    raise ValueError("not public")
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="公网直连要求 SSH 主机地址为公网 IPv4；请先更新服务器地址") from exc
        if body.project == "dockge":
            if host["facts"].get("DOCKGE_PRESENT") != "no":
                raise HTTPException(status_code=409, detail="检测到已有原版 Dockge、Dockge Apps 或不完整安装；不会重装或覆盖数据")
        else:
            current_dockge = read_existing_dockge(host)
            if (not current_dockge["installed"] or not current_dockge["managed"] or
                    current_dockge["service"] != "active" or
                    current_dockge["access_mode"] not in {"local", "public"}):
                raise HTTPException(status_code=409, detail="只允许修改已运行且端口已验证的受管理 Dockge Apps")
        options = {"panel_port": host_port, "access_mode": mode, "public_confirmed": bool(body.confirm_public)}
    elif body.project == "3x-ui-https":
        if body.access_mode or body.panel_port is not None:
            raise HTTPException(status_code=422, detail="现有面板的 HTTPS 升级端口由服务器实际配置决定，不能手工覆盖")
        if body.source_job_id:
            source = find_job(body.source_job_id)
            if source["plan"].get("trust_epoch", 0) != host.get("trust_epoch", 0):
                raise HTTPException(status_code=409, detail="原 3X-UI 任务属于重装前的系统，不能用来升级当前 VPS")
            if source["project"] != "3x-ui" or source["host_id"] != host["id"] or source["status"] not in {"completed", "partial"}:
                raise HTTPException(status_code=409, detail="原始安装任务不匹配，请从服务器控制台检查当前面板")
            if source["status"] == "completed" and source["plan"].get("options", {}).get("access_mode") == "https":
                raise HTTPException(status_code=409, detail="此原始任务已经完成 HTTPS，请直接查看现有面板")
            if store.completed_https_upgrade(host["id"], source["id"]):
                raise HTTPException(status_code=409, detail="已有完成的 HTTPS 升级任务，请查看面板")
            options = {"panel_port": source["plan"]["options"]["panel_port"],
                       **tls_options(host), "source_job_id": source["id"]}
        else:
            # A task history cleanup must not force a reinstall. Only an
            # independently verified, managed, localhost-bound live service
            # can be the origin of a standalone HTTPS recovery plan.
            existing = read_existing_xui(host)
            if (not existing["installed"] or not existing["managed"] or
                    existing["service"] != "active" or existing["access_mode"] != "local"):
                raise HTTPException(status_code=409, detail="只有已运行、安装记录可验证且仍本机监听的 3X-UI 才能直接继续 HTTPS；不会覆盖未知配置")
            options = {"panel_port": existing["port"], **tls_options(host)}
    elif body.panel_port is not None or body.access_mode or body.source_job_id:
        raise HTTPException(status_code=422, detail="此项目不支持 HTTPS 部署参数")
    try:
        plan = build_plan(body.project, host["facts"], options)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=422, detail="证书标识、端口或部署参数不合法") from exc
    plan["hostname"] = host["hostname"]
    plan["host_id"] = host["id"]
    plan["trust_epoch"] = host.get("trust_epoch", 0)
    plan["preflight_baseline"] = approval_baseline(host["facts"])
    return store.new_job(host["id"], body.project, plan)


@app.get("/api/jobs/{id}", dependencies=[Depends(authorized)])
def get_job(id: str):
    return public_job(find_job(id))


@app.delete("/api/jobs/{id}", dependencies=[Depends(authorized)])
def delete_job(id: str, body: DeleteJobConfirmation):
    """Remove history only; does not uninstall or touch remote services."""
    find_job(id)
    if body.confirmation != f"DELETE {id}":
        raise HTTPException(status_code=409, detail="请确认只删除本地记录，不影响 VPS 软件")
    try:
        if not store.delete_job(id):
            raise HTTPException(status_code=404, detail="任务不存在")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "deleted_id": id, "remote_unmodified": True}


@app.post("/api/jobs/{id}/approve", dependencies=[Depends(authorized)])
def approve_job(id: str, body: Approval):
    job = find_job(id)
    host = find_host(job["host_id"])
    # Host identity is part of the immutable approval context.
    if job["plan"].get("trust_epoch", 0) != host.get("trust_epoch", 0):
        raise HTTPException(status_code=409, detail="服务器已重装或 SSH 信任已更新，旧部署方案已失效，请重新生成")
    if not host["facts"]:
        raise HTTPException(status_code=409, detail="缺少环境预检结果")
    # Recheck preflight before approving: changing host may invalidate the plan.
    try:
        current = executor.preflight(host)
    except (ValueError, SSHError) as exc:
        raise HTTPException(status_code=409, detail=f"二次预检失败：{exc}") from exc
    # A deployment's original safety snapshot must survive any later refresh
    # of the host record. Legacy plans without this snapshot must be recreated.
    baseline = job["plan"].get("preflight_baseline")
    if not isinstance(baseline, dict):
        raise HTTPException(status_code=409, detail="旧版部署计划缺少安全快照，请重新生成部署计划")
    latest_safety = approval_baseline(current)
    changed_keys = sorted(
        key for key in set(baseline) | set(latest_safety)
        if key not in baseline or key not in latest_safety or baseline[key] != latest_safety[key]
    )
    if changed_keys:
        store.save_facts(host["id"], current)
        raise HTTPException(
            status_code=409,
            detail=f"服务器关键环境已变化（{', '.join(changed_keys)}），请重新生成部署计划",
        )
    # Recheck minimum free space and all project-specific gates against the
    # *new* values. A changing FREE_KB value is safe only above the threshold.
    try:
        fresh_plan = build_plan(job["project"], current, job["plan"].get("options"))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=f"部署方案参数不再有效：{exc}") from exc
    if not fresh_plan["executable"]:
        store.save_facts(host["id"], current)
        reasons = "；".join(fresh_plan["issues"])
        raise HTTPException(status_code=409, detail=f"二次环境检测未通过：{reasons}。请解决后重新生成部署计划")
    if fresh_plan["steps"] != job["plan"].get("steps"):
        raise HTTPException(status_code=409, detail="执行模板与已审批计划不一致，请重新生成部署计划")
    # Store the latest non-secret free-space reading, so the runner's second
    # deterministic plan build uses the same checked facts.
    if current != host["facts"]:
        store.save_facts(host["id"], current)
        host["facts"] = current
    if not body.confirmed_risk and body.confirmation != runner.approval_text(job, host):
        raise HTTPException(status_code=409, detail="请确认已阅读固定部署方案与高权限风险")
    try:
        # The server derives the legacy phrase after a deliberate one-click
        # confirmation; the user must never type or copy it repeatedly.
        verified_phrase = runner.approval_text(job, host)
        runner.enqueue(job, host, verified_phrase)
        return {"ok": True, "job_id": id, "status": "queued"}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/jobs/{id}/access", dependencies=[Depends(authorized)])
def job_access(id: str):
    """Explicit, one-time-style read of upstream-generated credentials.

    Never persist the returned password or include it in task logs/AI input.
    Authenticated localhost API response is marked no-store by middleware.
    """
    job = find_job(id)
    if job["project"] != "3x-ui" or job["status"] not in {"completed", "partial"}:
        raise HTTPException(status_code=409, detail="只有已完成安装或 HTTPS 部分失败的 3X-UI 任务可核验登录信息")
    host = find_host(job["host_id"])
    port = (job["plan"].get("options") or {}).get("panel_port")
    if job["plan"].get("trust_epoch", 0) != host.get("trust_epoch", 0):
        raise HTTPException(status_code=409, detail="此部署记录属于服务器重装前的系统，不能再读取原登录信息")
    if not executor.credential_ready(host):
        raise HTTPException(status_code=409, detail="SSH 凭据不可用，请在服务器管理中重新设置")
    upgrade = store.completed_https_upgrade(host["id"], job["id"])
    identity = None
    if job["status"] == "completed" and job["plan"].get("options", {}).get("access_mode") == "https":
        identity = job["plan"]["options"]["tls_identity"]
    elif upgrade is not None and upgrade["plan"]["options"]["panel_port"] == port:
        identity = upgrade["plan"]["options"]["tls_identity"]
    script = https_access_script(identity, port) if identity else ACCESS_SCRIPT
    try:
        result = parse_access_result(executor.run(host, script, timeout=25), port)
    except (SSHError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="无法验证远端面板或 TLS 证书，请检查服务、证书有效期和自动续期") from exc
    if identity:
        result["direct_url"] = https_url(identity, port, result["web_path"])
        result["access_mode"] = "https"
    else:
        result["ssh_tunnel"] = (
            f"ssh -N -p {host['port']} -L {port}:127.0.0.1:{port} "
            f"{host['username']}@{host['hostname']}"
        )
        result["access_mode"] = "local"
    return result


@app.post("/api/jobs/{id}/diagnose", dependencies=[Depends(authorized)])
def diagnose_job(id: str):
    job = find_job(id)
    host = find_host(job["host_id"])
    try:
        return {"message": diagnose(job, host["facts"] or {})}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
