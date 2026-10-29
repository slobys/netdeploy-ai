"""NetDeploy AI API, single-admin prototype. Do not expose directly to public Internet."""
from __future__ import annotations

import os
import re
import secrets
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
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
app = FastAPI(title="NetDeploy AI", version="0.2.1")

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


class HostCredentials(BaseModel):
    auth_mode: Literal["key", "password"]
    password: str | None = None


class TrustKey(BaseModel):
    fingerprint: str
    confirmed_out_of_band: bool = False


class NewJob(BaseModel):
    host_id: int
    project: str
    panel_port: StrictInt | None = Field(default=None, ge=1024, le=65535)


class Approval(BaseModel):
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
    return {**host, "credential_ready": executor.credential_ready(host)}


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
    return {"ok": True, "version": "0.2.1", "security": "local-only"}


@app.get("/api/auth", dependencies=[Depends(authorized)])
def auth():
    return {"ok": True}


@app.get("/api/catalog", dependencies=[Depends(authorized)])
def catalog():
    return CATALOG


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
    # Do not pass credentials into the database, responses, plan or logs.
    host = store.add_host(body.model_dump(exclude={"password"}))
    if body.auth_mode == "password":
        executor.set_password(host["id"], body.password)
    return public_host(host)


@app.put("/api/hosts/{id}/credentials", dependencies=[Depends(authorized)])
def update_credentials(id: int, body: HostCredentials):
    find_host(id)
    if body.auth_mode == "password":
        require_password(body.password)
    try:
        host = store.update_auth(id, body.auth_mode)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    executor.clear_password(id)
    if body.auth_mode == "password":
        executor.set_password(id, body.password)
    return public_host(host)


@app.post("/api/hosts/{id}/fingerprint", dependencies=[Depends(authorized)])
def fingerprint(id: int):
    host = find_host(id)
    try:
        data = executor.scan_hostkey(host)
        return {"fingerprint": data["fingerprint"], "key_type": data.get("key_type", "ssh-ed25519"),
                "warning": "SSH 握手获取的主机密钥未经身份验证，必须先在 VPS 云控制台独立核对指纹。"}
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


@app.post("/api/hosts/{id}/preflight", dependencies=[Depends(authorized)])
def preflight(id: int):
    host = find_host(id)
    try:
        facts = executor.preflight(host)
        return store.save_facts(id, facts)
    except (ValueError, SSHError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
    if not host["facts"]:
        raise HTTPException(status_code=409, detail="请先对服务器执行 SSH 环境检测")
    if body.project != "3x-ui" and body.panel_port is not None:
        raise HTTPException(status_code=422, detail="仅 3X-UI 支持设置管理面板端口")
    options = {"panel_port": body.panel_port if body.panel_port is not None else DEFAULT_PORT} if body.project == "3x-ui" else None
    if options and options["panel_port"] == host["port"]:
        raise HTTPException(status_code=422, detail="3X-UI 面板端口不能与 VPS SSH 端口相同")
    try:
        plan = build_plan(body.project, host["facts"], options)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    plan["hostname"] = host["hostname"]
    plan["host_id"] = host["id"]
    plan["preflight_baseline"] = approval_baseline(host["facts"])
    return store.new_job(host["id"], body.project, plan)


@app.get("/api/jobs/{id}", dependencies=[Depends(authorized)])
def get_job(id: str):
    return find_job(id)


@app.post("/api/jobs/{id}/approve", dependencies=[Depends(authorized)])
def approve_job(id: str, body: Approval):
    job = find_job(id)
    host = find_host(job["host_id"])
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
    try:
        runner.enqueue(job, host, body.confirmation)
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
    if job["project"] != "3x-ui" or job["status"] != "completed":
        raise HTTPException(status_code=409, detail="只有已完成的 3X-UI 部署任务可查看登录信息")
    host = find_host(job["host_id"])
    port = (job["plan"].get("options") or {}).get("panel_port")
    if not executor.credential_ready(host):
        raise HTTPException(status_code=409, detail="SSH 凭据已经失效，请重新输入 VPS SSH 密码")
    try:
        result = parse_access_result(executor.run(host, ACCESS_SCRIPT, timeout=25), port)
    except (SSHError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"无法安全读取 3X-UI 登录信息：{exc}") from exc
    result["ssh_tunnel"] = (
        f"ssh -N -p {host['port']} -L {port}:127.0.0.1:{port} "
        f"{host['username']}@{host['hostname']}"
    )
    return result


@app.post("/api/jobs/{id}/diagnose", dependencies=[Depends(authorized)])
def diagnose_job(id: str):
    job = find_job(id)
    host = find_host(job["host_id"])
    try:
        return {"message": diagnose(job, host["facts"] or {})}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
