# NetDeploy AI · v0.1.2 Alpha

> 一个以 VPS 为优先方向的 AI 辅助网络项目部署面板。2026-10-29 第一阶段原型（Windows SSH 主机指纹扫描修复）。 **不是生产稳定版，不要用重要 VPS 直接试错。**

![Status](https://img.shields.io/badge/stage-alpha-blue) ![Tests](https://img.shields.io/badge/stage-local--tests%20only-orange)

## 已有功能

- 独立响应式 Web 面板（项目中心、VPS 设备、环境检测、部署任务、日志）
- **新增 SSH 密码/私钥双模式**；Ed25519/ECDSA/RSA 主机指纹独立核对，拒绝自动信任未知主机；密码只保存在服务端运行内存，不写磁盘
- Linux 发行版 / CPU 架构 / root / 空间 / Docker / systemd / UDP 端口预检
- **sing-box**：Debian/Ubuntu 通过官方签名 APT 源安装**内核**（并不自动生成服务端配置）
- **wg-easy**：Docker Compose 部署 v15，管理端绑定 VPS localhost:51821；仍需首次账号/公网 IP 设置
- **3X-UI / Hysteria2**：界面、Skills 和部署引导就绪，尚不开放一键安装
- 自动展示 SSH 脚本 + 手动确认审批 + 执行中状态、步骤级日志 + 防重复任务
- 可选隔离 Codex Worker：只读分析脱敏日志，不能执行服务器命令

## 先在本机预览（无需 Docker 和 SSH 私钥）

需要 Python 3.12+：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export NETDEPLOY_ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(40))')"
export NETDEPLOY_DATA="$(pwd)/data"
uvicorn app.main:app --host 127.0.0.1 --port 8787 --workers 1
```

浏览器访问 `http://127.0.0.1:8787`，登录时使用上述管理员令牌（请先记下来）。**预览不需要配置 SSH；真实连接使用面板填写的密码或专用密钥，都必须先核对 SSH 主机指纹。** Windows 使用 PowerShell 时需要分别调整 `source`、`export` 的语法。

## Windows 11：从 GitHub 克隆、双击启动与更新（推荐）

**首次安装：** 先安装 [Git for Windows](https://git-scm.com/downloads/win) 与 Python 3.12+，然后在 PowerShell 执行：

```powershell
git clone https://github.com/slobys/netdeploy-ai.git
cd netdeploy-ai
.\Start-NetDeploy.bat
```

首次启动会在本地创建 `.venv`、安装依赖、生成独立的管理员令牌并保存在 **不纳入 Git 的** `.env`，令牌只在首次生成时显示，请妥善保管。浏览器打开 `http://127.0.0.1:8787`。后续双击 `Start-NetDeploy.bat` 即可启动。

**更新：** 先在运行服务的窗口按 `Ctrl+C` 停止服务，再双击 `Update-NetDeploy.bat`；该脚本只允许对 `main` 分支做 fast-forward 更新，更新前自动备份 `data/` 到本地 `backups/`，保留 `.env`、`data/`、`secrets/`。更新成功后双击 `Start-NetDeploy.bat`。脚本不会自动更新 GitHub 仓库，也不会把 VPS 密码上传 GitHub。

**已使用 v0.1.2 ZIP 的用户：** 现有的解压目录**没有 `.git`，不能直接执行 `git pull`**。一次性迁移操作：

1. 停止旧版服务，不要删除旧目录。
2. 在桌面上用 `git clone https://github.com/slobys/netdeploy-ai.git netdeploy-ai-git` 克隆到新目录。
3. 从旧的 `netdeploy-ai\data` 复制整个 `data` 文件夹到新目录 `netdeploy-ai-git`（如旧目录已有 `.env`，也复制过去；如已有密钥文件 `secrets/ssh_key`，将其安全复制过去）。
4. 运行新目录的 `Start-NetDeploy.bat`，使用原来管理员令牌登录；若旧版管理员令牌只保存在 PowerShell 会话变量中，启动脚本会产生新令牌，旧 VPS 和部署任务仍留在数据库。
5. 确认新目录工作正常后，才决定是否备份/移除旧目录。此后只在 **Git 克隆目录** 使用 `Update-NetDeploy.bat`。

如需手动更新，也可以在已停止服务的 Git 克隆目录执行 `git pull --ff-only origin main`。不过推荐使用更新脚本，以便自动检查状态并备份数据。**不可运行 `git reset --hard` 来强制覆盖当前配置。**

## Docker Compose 安装（更适合 NAS / Linux）

准备：Python 无需安装；需要 Docker 与 Docker Compose v2。**请先使用快照/临时 VPS 测试。**

```bash
# 1. 进入项目目录
cd netdeploy-ai
mkdir -p data secrets

# 2. 配置管理员和内部 Worker Token
cp .env.example .env
python3 - <<'PY'
from pathlib import Path
import secrets
p=Path('.env')
s=p.read_text()
s=s.replace('REPLACE_WITH_A_RANDOM_SECRET_AT_LEAST_24_CHARS', secrets.token_urlsafe(40))
s=s.replace('REPLACE_WITH_ANOTHER_RANDOM_SECRET_AT_LEAST_24_CHARS', secrets.token_urlsafe(40))
p.write_text(s)
PY

# 3. 若要使用密码登录，跳过私钥配置。
# 若选择私钥登录，则复制专用密钥（不要复制个人主密钥），并提前添加公钥授权：
# install -m 0600 ~/.ssh/netdeploy_ed25519 secrets/ssh_key

# 容器以 UID 10001 运行，需要写 data；密钥登录时还需可读取只读私钥
sudo chown -R 10001:10001 data
# 仅使用私钥登录时：sudo chown 10001:10001 secrets/ssh_key

# 4. 启动主控制台
sudo docker compose up -d --build
```

默认只允许 Docker 宿主机访问 `http://127.0.0.1:8787`，不直接向公网开放。局域网电脑使用 SSH 隧道，例如：

```bash
ssh -L 8787:127.0.0.1:8787 your-nas-user@YOUR_NAS_HOST
```

然后在电脑浏览器打开 `http://127.0.0.1:8787`。如果希望长期局域网直连，可在配好 HTTPS、登录和访问限制的反向代理之后开放，**不要直接把 8787 映射到公网**。

### 令牌在哪里？

`.env` 文件的 `NETDEPLOY_ADMIN_TOKEN`，只能由管理员保管，不能上传 GitHub。面板只把令牌保存在浏览器当前标签的 sessionStorage。

## 真实 VPS 连接（新增密码登录）

1. 面板 → **添加 VPS**，输入名称、IP、SSH 端口、用户（当前部署要求 root）。选择 **SSH 密码登录**，输入 VPS 的 SSH 密码；高级用户也可以选择 **SSH 私钥登录**。
2. 点击 **SSH 指纹**。在云厂商的独立网页控制台核对扫描出来的指纹，不能因为网页上显示了一个指纹就直接信任。面板根据扫描出的密钥类型自动提示对应命令，例如：
   ```bash
   ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256
   # 如果显示 RSA：改为 /etc/ssh/ssh_host_rsa_key.pub
   # 如果显示 ECDSA：改为 /etc/ssh/ssh_host_ecdsa_key.pub
   ```
3. 确认指纹一致后信任，再点 **环境检测**。连接成功后可以在项目中心生成部署计划。
4. 如曾经添加过密钥登录的 VPS，**无需删除服务器**：点击该 VPS 右侧的 **登录方式** → 选择密码登录 → 填入密码 → 保存，随后重新进行环境检测。
5. 预检通过、用户审阅脚本后，才允许输入确认语句执行部署。主机密钥变更禁止自动覆盖。

**密码保管说明：** 密码不写入数据库、配置文件、日志或浏览器持久存储，只在当前 API 进程的内存中保留。服务重启、容器重建或多个 API worker 分离时，密码会丢失；面板显示“需设置凭据”，点击 **登录方式** 重新输入即可。初版仅支持单个 Uvicorn worker。不要把管理员 HTTP API 暴露到公网；远程访问请使用可信 SSH 隧道或 HTTPS 反向代理。

**如果 SSH 指纹无法读取：** 这发生在登录认证之前，不是密码错误。v0.1.2 使用 Paramiko 完成 SSH 握手扫描，不依赖 Windows 的 `ssh-keyscan` / `ssh-keygen`，并对端口拒绝、超时、DNS 错误和协议握手失败分别报错。仍需检查 VPS SSH 地址、端口、云厂商安全组以及 sshd。Windows 用户可运行：

```powershell
Test-NetConnection -ComputerName YOUR_VPS_IP -Port 22
```

如果 `TcpTestSucceeded` 为 `False`，请检查云厂商安全组、远端 sshd 与防火墙；若为 `True` 但扫描失败，请在 VPS 云控制台检查 sshd 日志和算法支持。**面板运行在 NAS / Docker 时，应从该设备而非个人电脑检查连通性。** 不建议为排障关闭 SSH 主机密钥校验。

**如果密码认证失败：** 检查用户名/密码，以及 `/etc/ssh/sshd_config` 中的 `PasswordAuthentication`、`PermitRootLogin`（一些云厂商默认禁止 root 密码 SSH）。优先选择非 root 账户和受限授权；此 Alpha 受控安装步骤仍要求 root，不能通过界面自动绕过服务器认证限制。

### wg-easy 初始设置

部署后 Web 只绑定目标 VPS 的 127.0.0.1:51821，因此在自己的电脑执行：

```bash
ssh -L 51821:127.0.0.1:51821 root@YOUR_VPS_IP
```

然后在自己电脑访问 `http://127.0.0.1:51821` 完成 wg-easy 首次账户与公网地址配置。需要自行在云防火墙开放 UDP 51820，Web 管理端不应直接暴露公网。现阶段**安装成功不代表 WireGuard 客户端已经连通**。

### sing-box 安装后

系统只安装程序，不会生成对外代理节点；请根据官方文档创建合法配置、执行 `sing-box check`，完成 TLS、认证和服务端口方案后再启动。面板不会自动降低系统防火墙安全性。

## 可选 Codex AI 诊断

必须具有可用的 Codex 运行身份/凭据。只有需要 AI 诊断时才启动隔离服务：

```bash
# 将可用的 CODEX_API_KEY 写入 .env 后
sudo docker compose --profile ai up -d --build
```

AI 进程在独立容器运行，**无 SSH 密钥、数据库、API 管理令牌或 Docker Socket**，只通过受认证的内网接口接收脱敏设备信息和日志。此 Alpha 的 SDK 实际登录/运行情况**尚未在目标环境验收**；如果 Worker 不可用，普通部署功能保持可用。

## 单元测试

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

## 项目结构

```text
app/
  main.py             FastAPI API 与管理员权限检查
  catalog.py          唯一许可的固定部署脚本和兼容性判定
  executor.py         SSH 验证/远程预检/受控命令执行
  store.py            SQLite 持久化
  tasks.py            审批、状态管理、运行队列、日志
  ai.py               发送脱敏内容给隔离 Codex Worker
  ai_worker.py        可选只读 Codex SDK 容器服务
  static/              响应式 Web 前端
skills/<project>/SKILL.md   4 个工作流说明
Dockerfile / Dockerfile.ai / compose.yaml
requirements.txt / requirements-dev.txt
docs/ARCHITECTURE.md / ROADMAP.md / SECURITY.md
tests/                    自动化测试
```

## 项目边界与注意事项

- **Alpha 不是无人工干预的一键安装**。root VPS 变更仍需审批，不允许直接执行 Codex 生成的 shell。
- 第一阶段「自动部署」只对通过了环境检查的 **sing-box 核心安装、wg-easy 容器部署**开放。3X-UI、Hysteria2 仍是引导模式。
- SSH 支持密码或专用私钥登录；两种方式都必须固定主机密钥。密码仅驻留当前 API 进程内存，服务重启后需重新输入。
- 暂时没有自动快照、回滚、幂等断点恢复。任务超时/重启必须手工核对 VPS 结果后再操作。
- `CODEX_API_KEY` 属于可选的 AI Worker 环境变量，不应发送给 VPS 或写进 Skills 文件。
- Docker、APT、网络和 DNS 在你实际的 VPS 中可能受到防火墙、权限或系统版本限制，必须测试。

参见 [架构](docs/ARCHITECTURE.md)、[安全边界](docs/SECURITY.md)、[阶段计划](docs/ROADMAP.md)。


## v0.1.2 修复说明

- 修复 Windows 对外部 `ssh-keyscan` 工具的依赖。密码模式继续使用 Paramiko；SSH 握手阶段读取主机公钥无需先登录、无需密码。
- 校验/记录主机密钥改用 Paramiko 的 `HostKeys`，非 22 端口使用 `[host]:port` 格式；仍需在可信渠道对照 SHA256 指纹。
- 连接失败时面板给出端口检测命令和明确的网络/握手诊断。
- **更新时保留旧版 `data/` 目录和原管理员 `NETDEPLOY_ADMIN_TOKEN`，否则登录和 VPS 列表可能丢失。** 仍未经过真实 VPS 验收。
