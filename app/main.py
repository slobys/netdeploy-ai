"""NetDeploy AI API, single-admin prototype. Do not expose directly to public Internet."""
from __future__ import annotations

import os
import re
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
from .firewall import PortRule, STATUS_SCRIPT, allow_port_script

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
app = FastAPI(title="NetDeploy AI", version="0.3.5")
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
    access_mode: Literal["local", "https"] | None = None
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
    return {"ok": True, "version": "0.3.5", "security": "local-only"}


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
    if body.auth_mode == "password":
        require_password(body.password)
        if body.remember_password and not executor.vault.available:
            raise HTTPException(status_code=422, detail="此设备未启用 Windows 系统凭据保管库，请选择临时密码登录")
    # Do not pass credentials into the database, responses, plan or logs.
    host = store.add_host(body.model_dump(exclude={"password"}))
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
                                     body.port, body.username.strip())
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
        raise HTTPException(status_code=409, detail="必须输入对应的 VPS 地址及端口确认语句")
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


@app.get("/api/jobs", dependencies=[Depends(authorized)])
def list_jobs():
    return store.jobs()


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
        options = {"panel_port": body.panel_port if body.panel_port is not None else DEFAULT_PORT}
        if body.access_mode == "https":
            options.update({"access_mode": "https", "tls_identity": host["hostname"]})
        if options["panel_port"] == host["port"]:
            raise HTTPException(status_code=422, detail="面板端口不能与 VPS SSH 端口相同")
    elif body.project == "3x-ui-https":
        if not body.source_job_id or body.access_mode or body.panel_port is not None:
            raise HTTPException(status_code=422, detail="HTTPS 升级必须引用已完成的 3X-UI 安装任务")
        source = find_job(body.source_job_id)
        if source["plan"].get("trust_epoch", 0) != host.get("trust_epoch", 0):
            raise HTTPException(status_code=409, detail="原 3X-UI 部署任务属于重装前的系统，请先在新 VPS 上重新部署")
        if source["project"] != "3x-ui" or source["host_id"] != host["id"] or source["status"] not in {"completed", "partial"}:
            raise HTTPException(status_code=409, detail="无法核实对应的原 3X-UI 安装任务")
        if (source["status"] == "completed" and
                source["plan"].get("options", {}).get("access_mode") == "https"):
            raise HTTPException(status_code=409, detail="该 3X-UI 安装任务已经使用 HTTPS 部署")
        if store.completed_https_upgrade(host["id"], source["id"]):
            raise HTTPException(status_code=409, detail="该任务已完成 HTTPS 升级，请打开原 3X-UI 任务")
        options = {"panel_port": source["plan"]["options"]["panel_port"],
                   "tls_identity": host["hostname"], "source_job_id": source["id"]}
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
    return find_job(id)


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
