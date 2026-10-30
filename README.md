# NetDeploy AI · v0.3.20 Alpha

> 一个以 VPS 为优先方向的 AI 辅助网络项目部署面板。2026-10-29 第一阶段原型（Windows SSH 主机指纹扫描修复）。 **不是生产稳定版，不要用重要 VPS 直接试错。**

![Status](https://img.shields.io/badge/stage-alpha-blue) ![Tests](https://img.shields.io/badge/stage-local--tests%20only-orange)

## 📖 中文在线文档

[在线使用手册](https://slobys.github.io/netdeploy-ai/) · [Windows 安装](https://slobys.github.io/netdeploy-ai/installation.html) · [首次部署](https://slobys.github.io/netdeploy-ai/quick-start.html) · [Google Cloud / root 密码](https://slobys.github.io/netdeploy-ai/google-cloud.html) · [常见问题](https://slobys.github.io/netdeploy-ai/troubleshooting.html)

参考 NaiLink 的文档使用方式，新建独立的 GitHub Pages 中文手册，包含手机适配、章节导航、搜索和复制命令。仓库 `.github/workflows/docs.yml` 随 main 自动构建发布；首次需要在仓库 **Settings → Pages → Source → GitHub Actions** 启用 Pages。站点未启用前可先阅读 [文档源码](docs/site/README.md)。

**谷歌云 root 密码操作：** 仅推荐交互执行 `sudo passwd root`，不在公共教程中固定密码。附加 [GCP root 辅助脚本](scripts/gcp-root-setup.sh) 默认不启用密码 SSH；可选模式属于高风险操作，请先阅读 [Google Cloud 专题](https://slobys.github.io/netdeploy-ai/google-cloud.html)。

## v0.3.20：项目中心也启用紧凑布局（Alpha）

修复「项目中心」中项目卡片仍然固定四列、固定高度、第五个项目单独换行，以及重复显示「项目中心 / 精选部署项目」的体验问题。

- 「项目中心」与首页「精选部署项目」统一使用**紧凑、自适应项目卡片**，宽屏可将现有五个项目同排展示，窄屏自动换列。图标、分类、说明、状态和部署/方案按钮均保留，卡片高度由内容决定。
- 在「项目中心」仅保留顶层「项目中心」标题，并显示实际可选项目数；隐藏重复的「精选部署项目」次级标题和无意义的「查看全部项目」自跳转按钮。返回总览时保留首页精选标题及查看全部入口。
- 兼容六种主题色、明暗模式及标准/舒适/大字三种阅读字号；无需修改已有 VPS、SSH 设置或部署任务。新增切换页面及五项目按钮回归测试。

## v0.3.19：首页精选项目紧凑排版（Alpha）

针对首页「精选部署项目」卡片高度过高、短项目说明留白过多和第 5 个项目单独换行的问题，首页改为紧凑自适应网格：**宽屏自动将现有 5 个项目安排在一行**；窗口变窄时依容器宽度自动换列，不再固定四列。每张卡片取消 240px/267px 高度限制，收紧图标、内边距与说明间距，状态和操作按钮依然完整可点击。

- v0.3.19 首先优化首页总览；v0.3.20 起「项目中心」也同步采用紧凑卡片。
- 继续兼容深色/浅色、六种主题配色，以及「标准 / 舒适 / 大字」三档字体；文字需要换行时卡片自动增高，不截断操作按钮。
- `node tests/ui_smoke.cjs` 覆盖五项渲染、操作按钮未丢失、首页与项目中心的展示模式切换及自适应网格样式。

## v0.3.18：修复 Debian 13 的 IP 证书签发（Alpha）

已确认 Debian 13 APT 默认 Certbot 4.0.0 不支持 `--ip-address`，导致新装 3X-UI / S-UI 的证书阶段退出 31。新版**不会因为系统存在旧 Certbot 就跳过升级**：IP 证书改用独立的 Python venv 安装经过版本固定的官方 **Certbot 5.8.0**，原有系统 Certbot、`certbot.timer` 和 `/etc/letsencrypt` 完全保留。

- IP 证书：专用 `/opt/netdeploy-certbot/venv/bin/certbot` + 独立配置 `/etc/netdeploy/letsencrypt` + `netdeploy-certbot-renew.timer` 每 4 小时检查短期证书，避免系统 4.0.0 意外处理 IP 证书。外部 Python 包固定从官方 PyPI 下载，仅安装到隔离虚拟环境。
- 域名证书：继续使用发行版的 Certbot 与原来的 `certbot.timer`，不改动已有网站的证书及续期服务。
- 用户真实 VPS 已完成 3X-UI 5/9 步并因 Certbot 4.0 失败时，**不需要重装 3X-UI、不需要卸载 Debian Certbot**。更新本机 NetDeploy 后，进入已安装面板 → **继续完成 HTTPS** → 重新生成、审核 4 步证书方案，即会自动补齐新版 Certbot。
- 安装依赖需要 VPS 能访问官方 PyPI（TCP 443），Let’s Encrypt HTTP-01 签发需要云平台放行公网 TCP 80，安装成功后公网面板管理端口仍需设置云安全组。`UFW_UNAVAILABLE` 只说明服务器没装 UFW，并非证书失败的根因。
- 测试覆盖 Debian 13 旧版 Certbot、模拟 PyPI 安装失败后重试、隔离配置/定时器、3X-UI/S-UI IP 与域名安全回退。尚未在用户真实 VPS 上完成新证书实测，先在可恢复的测试 VPS 验收。

## v0.3.17：全界面舒适字号与阅读模式（Alpha）

针对浅色主题截图中小字难读的问题，统一提升导航、概览统计、项目卡片、辅助说明、按钮、表单、服务器管理、SSH 指纹、端口与证书向导的字体层级，采用 12–27px 的语义化字号体系和更舒适的行距。页面默认采用 **「舒适」** 字号，主要正文 14.5px、卡片说明 13–13.5px、卡片标题约 16px、统计数字约 27px，替代之前大量 9–11px 的微小字号。

- 「◐ 主题 → 阅读字号」新增 **标准 / 舒适 / 大字** 三档；立刻生效、自动保存到本机浏览器，刷新无需再调整；默认舒适（已有主题颜色、深浅选择保持不变）。
- 大字模式通过 CSS 字号变量统一扩展（约 +15%），自动增高卡片、换行长文字，兼容移动端、弹窗和窄屏侧边栏；浏览器不允许存储时仍可当次切换。
- 字号偏好不写入后台数据库、不会重启 VPS 或影响 SSH；支持跨标签页偏好同步、拒绝未识别的浏览器存储值。静态测试覆盖各字号、菜单交互及主要页面组件。

## v0.3.16：个性化外观主题（Alpha）

控制台顶栏增加 **「◐ 主题」**：支持经典蓝（保留原样）、极光紫、海洋青、翡翠绿、玫瑰粉、暖日橙六种配色，支持 **明亮 / 暗黑 / 跟随系统** 三种外观。主题作用于所有服务器卡片、部署项目、状态、表单、SSH 指纹和配置弹窗，兼容手机端。

- 即时切换，无需重新加载或中断部署；选择只写入本机浏览器 localStorage 的 UI 偏好，与 SSH 令牌、VPS 数据隔离，不会同步到其他设备。
- 「跟随系统」会根据 Windows/macOS 的深浅模式自动变化；默认仍是「经典蓝 · 暗黑」，保持原用户的使用习惯。
- 修复页面初次加载的主题闪烁，保证主题生效顺序；考虑弱视可读性、键盘操作、窄屏按钮和减少动画偏好。
- 可运行 `node tests/theme_smoke.cjs` 独立检查颜色/模式选择、刷新恢复、系统跟随、浏览器存储不可用和交互，无需外部依赖。

## v0.3.15：S-UI 自动 IP/域名 HTTPS（Alpha）

S-UI v1.6.6 新安装在原有 5 个安全安装阶段后，默认**自动继续 4 个证书阶段**：① 验证公网 IPv4 / 域名 A 与 80/TCP；② 检查 Certbot 与续期能力；③ 申请 IP 短期证书或域名证书，并配置 S-UI 专属续期钩子；④ 原生配置 S-UI TLS、验收 HTTPS 直连、成功后精准放行 UFW 2095/TCP。订阅 2096/TCP 始终仅 VPS 本机监听。

- **填写 HTTPS 域名 → 域名证书；不填域名 → 公网 IPv4 证书**，不要求反复选择证书类型；IP 证书需要支持 shortlived 的新版 Certbot 与自动续期。
- 只有证书、续期、TCP 2095 真实 TLS 连接验证全部通过后才提供 `https://IP或域名:2095/随机路径/`；**失败不会开放公网明文 HTTP**，已安装面板保持/恢复本机模式。
- 旧 S-UI 已安装且仍本机监听时，点击“继续完成 HTTPS”仅生成 4 步证书配置计划，不重复安装面板；重试仍需审批。公网 TCP 80 和管理 2095 还需云厂商安全组按需放行。
- 密码只在用户主动查看时经可信 SSH 读取；项目版本 `v0.3.15` 与在线使用文档同步。仅通过本地/CI 模拟测试，未在真实 VPS 上验收，请先备份测试机。

## 已有功能

- 响应式 Web 工作台（VPS 管理优先显示在首页首屏，直接编辑/删除/指纹重核验/连接检测；动画与明确的操作反馈）
- **SSH 密码/私钥双模式**；Ed25519/ECDSA/RSA 指纹严格固定；Windows 可选把 SSH 密码保存到操作系统凭据库（不写应用数据库/日志），更新后自动恢复
- Linux 发行版 / CPU 架构 / root / 空间 / Docker / systemd / UDP 端口 / 已有 x-ui / ss 工具预检
- **sing-box**：Debian/Ubuntu 通过官方签名 APT 源安装**内核**（并不自动生成服务端配置）
- **wg-easy**：Docker Compose 部署 v15，管理端绑定 VPS localhost:51821；仍需首次账号/公网 IP 设置
- **3X-UI**：固定安装器校验、新安装自动按公网 IPv4/域名选择相应 HTTPS 证书；已安装面板只升级证书、绝不覆盖现有程序（Alpha）
- **VPS 连续引导**：SSH 只填公网 IPv4，可选填写 HTTPS 域名，添加后在一个窗口完成指纹、连接检测和选择软件
- **Hysteria2**：界面、Skills 和部署引导就绪，尚不开放一键安装
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

**Windows 一条命令安装 / 更新 / 启动（v0.3.1，推荐）：** 先安装 Git for Windows 和 Python 3.12+。在普通 PowerShell 窗口复制以下**一整行**，即可自动在桌面创建或复用 `netdeploy-ai-git`，安全拉取 `main`，准备依赖、启动本机服务并打开默认浏览器：

```powershell
$repo=Join-Path ([Environment]::GetFolderPath('Desktop')) 'netdeploy-ai-git'; if(-not(Test-Path $repo)){git clone https://github.com/slobys/netdeploy-ai.git $repo; if($LASTEXITCODE -ne 0){throw 'Git clone failed'}}; $start=Join-Path $repo 'scripts\QuickStart-Windows.ps1'; powershell.exe -NoProfile -ExecutionPolicy Bypass -File $start
```

- **第一次运行**：自动在 Windows 桌面创建 Git 工作目录，安装依赖，生成内部随机管理员令牌并保存在 Git 忽略的 `.env` 中。本机浏览器访问 `http://127.0.0.1:8787` **自动登录**，不必手工输入面板令牌。VPS 的 SSH 密码仍要通过系统凭据库保存或输入一次。
- **以后运行**：同一条命令会复用 `netdeploy-ai-git`，检查 Git 来源、当前分支和本地变更，备份 `data/` 后仅允许快进更新，再启动并打开浏览器。如果 8787 端口已有服务运行，会显示正在运行的版本并中止更新，要求先在旧 PowerShell 窗口停止服务；不会打开旧面板假装更新成功。
- **已有旧版本**：不会清空桌面 `netdeploy-ai-git` 下原来的 `data/`、`.env`、`secrets/`、SSH 指纹和 Windows 凭据库。旧 ZIP 解压目录 `netdeploy-ai` 不会被覆盖或移动。
- **不适用于 NAS / 公网**：自动登录仅在 Windows 快捷启动的 `127.0.0.1:8787` 本机单用户模式启用；Docker、Linux 与远程部署仍需要管理员令牌，禁止通过反向代理暴露本机免登录端口。它不能防护当前电脑上恶意程序，请使用 Windows 账户锁屏与系统安全保护。

已克隆后也可以在桌面 `netdeploy-ai-git` 文件夹里双击 `QuickStart-NetDeploy.bat`，达到相同效果。


**首次安装：** 先安装 [Git for Windows](https://git-scm.com/downloads/win) 与 Python 3.12+，然后在 PowerShell 执行：

```powershell
git clone https://github.com/slobys/netdeploy-ai.git
cd netdeploy-ai
.\Start-NetDeploy.bat
```

首次启动会在本地创建 `.venv`、安装依赖、生成独立的内部管理员令牌并保存在 **不纳入 Git 的** `.env`；Windows 本机启动默认自动登录，无需显示或复制令牌。服务就绪后自动打开浏览器；以后也可以双击 `QuickStart-NetDeploy.bat` 完成安全更新与启动。

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


## v0.2.0 Alpha：3X-UI 一键安装（非 Docker）

**代码提供经审批的自动化安装，但仍未在真实 VPS 上完成端到端验收。请先使用有快照、可重装的测试机。**

固定官方 `v3.11.0` 安装器及 SHA-256。下载后校验原始脚本一致，再做经过审查的精确修改，强制跳过 TLS 时的无人值守 HTTP 绑定到 127.0.0.1。上游发布包还会验证其公开的 .sha256 文件；本版本尚未独立签名验证二进制。

使用步骤：

1. 停止 NetDeploy 服务并通过 Git 更新后重新启动，然后对 VPS 再执行一次“环境检测”（需 `XUI_PRESENT=no`、`SS_AVAILABLE=yes`）。
2. 选择 **3X-UI → 部署项目**，选 VPS 与面板端口（默认 `24443`），审阅固定脚本和高权限风险，输入审批确认语句。
3. 安装程序会完成依赖安装、校验和无人值守部署、systemd 检测、本机监听检测。安装器的密码与 API Token 不会进入 NetDeploy 日志。
4. 任务完成后打开 **查看面板登录信息**，才会按需读取在 VPS 上生成的管理员账号、密码和随机 Web 路径。
5. 在自己电脑的新 PowerShell 窗口运行面板提供的 SSH 隧道命令，例如 `ssh -N -p 22 -L 24443:127.0.0.1:24443 root@YOUR_VPS_IP`。隧道保持运行时，浏览器打开显示的 `http://127.0.0.1:24443/<随机路径>`。

不会自动安装 Docker、开放公网面板端口或签发 TLS 证书；没有事务级自动回滚。失败或网络中断后必须先检查 VPS 远端状态，不要盲目重新安装。

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
  three_x_ui.py       固定 3X-UI 安装器校验、非公网监听与按需登录信息读取
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
- Alpha 可审批执行 **3X-UI 非 Docker 安装**、sing-box 核心安装与 wg-easy 容器部署；Hysteria2 仍是引导模式。
- SSH 支持密码或专用私钥登录；两种方式都必须固定主机密钥。密码默认驻留当前 API 进程内存；Windows 可选择保存到系统凭据库，服务重启后可安全取回。
- 暂时没有自动快照、回滚、幂等断点恢复。任务超时/重启必须手工核对 VPS 结果后再操作。
- `CODEX_API_KEY` 属于可选的 AI Worker 环境变量，不应发送给 VPS 或写进 Skills 文件。
- Docker、APT、网络和 DNS 在你实际的 VPS 中可能受到防火墙、权限或系统版本限制，必须测试。

参见 [架构](docs/ARCHITECTURE.md)、[安全边界](docs/SECURITY.md)、[阶段计划](docs/ROADMAP.md)。


## v0.3.14：云平台安全组入口 + S-UI 固定版本一键部署

### 云平台安全组快捷入口（可选）

VPS 连续引导的第 4 步和安装后的服务器「网络端口」页均提供默认收起的 **“云厂商安全组 · 快速打开官方控制台”**。点开后有四个官方入口：阿里云 ECS、腾讯云 CVM、Google Cloud VPC 防火墙、AWS EC2 Security Groups。无需新建 NetDeploy 云账号或交出云平台密钥；登录到相应云平台后，自行选择地域、实例及安全组并设置入站规则，未登录会先要求完成云端身份认证。此入口不是第六个必经步骤，也不替你自动修改云安全组。

**关于安装后为什么能访问：** 新安装 3X-UI 时不会自动关闭 UFW；如果选择了 HTTPS 一次部署，NetDeploy 在 UFW 活跃时会按经审核的固定脚本尝试放行 ACME TCP 80，并在 HTTPS 验收成功后放行面板端口。UFW 已停用时会跳过本机规则；云厂商安全组始终不由 NetDeploy 自动修改。安装成功只说明服务和本机验收完成，不代表来自外网的所有连接均被允许。sing-box 不创建公网监听，wg-easy 的 Docker UDP 映射也不能等同云安全组已经放行。

### S-UI 项目一键部署（v1.6.6 Beta）

在“选择软件”中增加 **S-UI（sing-box 面板）**。固定官方 [alireza0/s-ui](https://github.com/alireza0/s-ui) **v1.6.6** 发布版本，使用 GitHub Releases 已公开的 amd64/arm64 发行包 SHA-256；不用联网执行不固定版本的 `curl | bash`。仅 Debian/Ubuntu 的 root SSH、systemd 和经过检查的 x86_64/aarch64 服务器可生成安装计划，先验证 2095/2096 TCP 未占用、目录与服务未存在，不会覆盖已有 S-UI。

- 整个安装是**一次审核、五个固定步骤**：系统预检、依赖准备、下载并验证 SHA-256 与安全归档路径、在启动前随机生成管理用户名/强密码及 Web 路径并将管理与订阅监听设为 `127.0.0.1`、启动并验证管理端口 2095/TCP 和订阅端口 2096/TCP 均且仅监听 `127.0.0.1`，拒绝额外公网/IPv6 监听。
- 安装后在项目卡片显示“已安装”，点开可以在**只读且经验证 SSH** 下查看本机登录地址、初始管理员用户名和密码（默认隐藏、可复制）、PowerShell SSH 隧道命令。不会在 NetDeploy 任务日志、AI Worker 或数据库存储明文 s-ui 管理密码。
- **默认不开放公网 Web HTTP，亦不自动申请 S-UI TLS 证书或放行云/本机 UFW**。第一次访问需在本机 PowerShell 建立 SSH 隧道；若未来希望直接公网 HTTPS，将另行引入可审计的 TLS 配置流程。现有 s-ui 实例仅检测和展示，不会重复覆盖安装。
- 本轮使用本地/CI 模拟环境验证固定脚本、参数和状态接口，**没有在你的真实 VPS 上执行安装**。此 Alpha 集成不等同生产环境验收；建议先用可重置的测试 VPS 尝试。

**Windows 更新**：先在原来的 PowerShell 窗口按 Ctrl+C 停止旧 NetDeploy，再双击桌面 `netdeploy-ai-git\QuickStart-NetDeploy.bat`，浏览器 Ctrl+F5，确认 `ALPHA v0.3.14` 与本机 `/api/health` 的 version 一致。

## v0.3.13：第 4 步支持一次添加和放行多个端口

- **多行端口输入**：在“端口与防火墙（可跳过）”页面点击 **＋ 添加端口**，逐行输入 1–65535 的端口，并分别选择 TCP/UDP；不需要的行可以删除。最多一次 **20 项**，例如 `80/tcp`、`8443/tcp`、`51820/udp`。相同端口的 TCP 和 UDP 算两项，完全相同的端口/协议会提示重复。
- **一键批量放行**：点击“**一次放行全部端口**”只发送一次经过管理员认证的批量请求，由后端在一条已固定 SSH 主机指纹的可信会话中，先验证所有规则再使用固定 UFW 白名单命令顺序处理。保留旧的单端口 API 兼容。
- **结果透明且可恢复**：执行结果逐项显示“已放行、失败或未修改”；部分失败不误报成整体成功。可以点击 **仅重试失败项**，不会重复提交已经成功的端口。如果 VPS UFW 未启用或未安装，显示规则均未修改；网络错误时提示先核对远端实际规则，不盲目重复执行。
- **原有操作不变**：此步骤仍可跳过；关闭整台 UFW 仍须单独的高风险确认，不会自动关闭。只管理 VPS 本机 UFW，**不能替代云厂商安全组** 的 TCP/UDP 入站放行。不会自动操作真实 VPS。

**升级：** 关闭旧 NetDeploy AI PowerShell 服务，双击桌面 `netdeploy-ai-git\QuickStart-NetDeploy.bat`，浏览器按 `Ctrl+F5` 并确认 **ALPHA v0.3.13**。这版的结果来自本地模拟测试，尚需在你自己的 VPS 上验收端口放行。

## v0.3.12：VPS 连续引导增加可选网络步骤，SSH 重装无需手填确认短语

- **五步连贯流程：** ① 填写服务器信息 → ② 独立核对 SSH 指纹 → ③ 连接/环境检测 → **④ 网络端口与防火墙（可跳过）** → ⑤ 选择要部署的软件。步骤集中在同一弹窗，不在中途反复返回首页。
- **端口快速放行：** 在第 4 步输入 1–65535 范围的端口，选择 TCP 或 UDP，点击“放行所填端口”即调用已授权的固定 UFW 规则。页面只读显示当前 UFW 状态；UFW 未安装/未启用时明确告知无需新增规则。所有这些操作仅针对 **VPS 本机 UFW**，不能代替云厂商安全组的入站规则。
- **关闭整个 UFW 属于高级高风险操作：** 仅当 UFW 确认运行时显示可用按钮；明确点击“关闭 UFW”后，还会展示全端口暴露风险，用户再主动确认才可能执行。不会因点击“下一步”、打开状态页或选择软件而自动关闭防火墙。若不想处理网络设置，直接点“跳过此步，下一步：选择软件”即可。
- **重装 VPS 后信任确认更简洁：** 云厂商独立核对新 SHA256 指纹并勾选后，确认窗口不再要求复制、输入 `REKEY IP:端口`。点击 **确认更新 SSH 信任** 即可；前端自动构造服务器端兼容确认信息，后端仍严格校验当前 SSH 端点、新旧指纹、执行中的任务和信任版本，并备份原 known_hosts。完成后可在引导中继续进行 SSH 环境检测。
- **部署安全不变：** 第 4 步的可选端口变更是用户明确操作；第 5 步真正部署软件时仍需另外审批固定高权限脚本。没有获得云厂商 API 授权时，NetDeploy 无法自动修改云端防火墙。

**本机更新**：先关闭旧版 NetDeploy PowerShell 服务，再运行桌面 `netdeploy-ai-git\QuickStart-NetDeploy.bat`，浏览器按 `Ctrl+F5`，确认 **ALPHA v0.3.12**。以上为本地模拟测试，不代表已经触碰你的真实 VPS。

## v0.3.11：SSH 只填 VPS IP，域名可选；添加后连续下一步

**正确填写方式：** “服务器公网 IPv4（SSH 连接）”填写 VPS IP；下面的“HTTPS 证书域名”可选。若填写 `ts.example.com` 则自动为域名签发证书；不填就为该 VPS 公网 IPv4 签发 IP 证书。不再让域名充当 SSH 登录地址，也不需要单独选择证书类型。

- 服务器新增可选 `tls_domain`，SQLite 旧数据自动迁移，原 SSH 指纹、密码和任务历史不会丢失。域名只参与 3X-UI HTTPS 证书及访问 URL，SSH 始终按原公网 IP + 端口连接。
- 域名申请前自动验证 VPS 出站公网 IP 与 SSH IP 相符、DNS A 指向该 VPS；证书失败不回退为公网 HTTP。域名更改将使该服务器等待审批的旧 HTTPS 方案失效，避免用旧域名执行。
- 添加 VPS 后在**一个弹窗**依次完成 **①服务器信息 → ②SSH 指纹 → ③连接检测 → ④选择软件**。首次指纹仍须在云厂商可信控制台独立核对；已信任且匹配则自动略过重复确认。SSH 检测成功后直接点“下一步”选择安装软件。
- 失败时可以原位重新扫描 SSH 指纹、修改 SSH 密码并重试，不必返回首页。部署只需最后一次固定高权限脚本审批；不会因为“下一步”而自动安装。
- 已添加的 VPS 也可到服务器设置中补填证书域名，不需重置 SSH 地址或重新添加。已签发的旧证书不会随编辑自动更换，只有新部署/HTTPS 配置才使用新域名。
- 已新增 SQLite 迁移、域名校验、证书选型、端点保护以及完整前端引导交互测试。真实 VPS 的域名证书签发仍需在用户环境验收。

**更新：** 停止本地 NetDeploy PowerShell 服务，再运行桌面 `netdeploy-ai-git\QuickStart-NetDeploy.bat`，浏览器 `Ctrl+F5`，确认版本 **v0.3.11**。

## v0.3.10：避免误用旧 HTTPS 执行脚本与“假更新成功”

**诊断依据：** 用户 2026-10-29 09:34 UTC 的失败日志仍显示 `XUI_LISTENER_MISSING: x-ui active but not listening on approved IPv4 TCP 8443`。这句话仅存在于 v0.3.8 的旧执行脚本；v0.3.9 已换成兼容 Linux `*:8443` / `[::]:8443` 的监听检查。因此此日志不能证明 v0.3.9 修复失败，反而说明本地服务、前端缓存或任务历史中仍在使用旧版脚本。

- **不再默默打开旧服务：** Windows 快捷启动器若发现 `127.0.0.1:8787` 已有 NetDeploy AI 服务，会显示**实际正在运行的版本**、明确要求到旧 PowerShell 窗口按 `Ctrl+C` 后重新运行，并返回失败状态；不再自动打开旧版页面、返回成功码导致误以为已完成更新。不会强杀其他进程，也不会修改数据。
- **前后台版本对照：** 前端每次刷新只读调用 `/api/health`，如果页面 JS 版本和后台版本不一致，右上角标记“版本不一致”并提示彻底停止旧服务、重新更新及 `Ctrl+F5`。检测不需要 SSH/VPS 访问。
- **失败历史明确区分：** 除了原有“待审批任务”的固定脚本比较，新版还会对失败、部分成功或中断的历史任务，**只读**比较已保存的执行脚本和当前被审查的固定模板。属于历史旧脚本失败的 HTTPS 任务，在 VPS 控制台中直接显示“生成最新版 HTTPS 修复方案”，查看详情有“旧版执行记录”提示及按钮；点击只会创建新的四步 HTTPS-only 方案，仍需一次明确的部署批准，**不会重新安装 3X-UI、覆盖证书或静默执行旧命令**。
- **保留日志证据：** 旧任务及其原失败日志不会被改写或删除，用于追溯。新计划的执行脚本必须匹配当前源代码，仍在审批前复核 SSH 身份、服务器环境、超时、端口与原模板。
- **若运行 v0.3.10 后仍失败：** 请以新生成的任务最后一步日志为准（而非旧历史记录），查看错误是否变为新的分类；有效证书和原 3X-UI 安装都无需重做。

**升级：** 先在运行 NetDeploy AI 的 PowerShell 窗口按 `Ctrl+C` 停止，再双击桌面的 `netdeploy-ai-git\QuickStart-NetDeploy.bat`，浏览器 `Ctrl+F5`。还可打开本机 `http://127.0.0.1:8787/api/health` 核对实际正在运行的版本字段应为 `0.3.10`。代码测试并未远程修改或验证你的真实 VPS。

## v0.3.9：修复 HTTPS 最后一步的 Linux/Go TCP 监听误判

**日志依据（2026-10-29）：** 3X-UI 已在 `127.0.0.1:8443` 完成安装与本机 HTTP 验收，Certbot / IP 证书 / 自动续期通过；第 9/9 步 `XUI_LISTENER_MISSING` 仅表示旧脚本没找到字面上完全一致的 `0.0.0.0:8443`，不能据此确认服务没有监听。

**上游源码核实：** 3X-UI v3.11.0 在 [internal/web/web.go](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/web/web.go) 使用 `net.ListenConfig.Listen("tcp", net.JoinHostPort(listen, port))`。Go 的双栈 TCP wildcard 套接字在 Linux `ss` 中可能显示为 `*:8443` 或 `[::]:8443`（也有 `0.0.0.0:8443`）。v0.3.8 使用 `grep -Fxq '0.0.0.0:8443'`，易误判并回滚。

- **修复 3 处一致性**：HTTPS 安装最后一步、已经安装面板的状态只读检查、HTTPS 登录信息读取统一复用经过审查的 `netdeploy_public_socket`。支持 `0.0.0.0:端口`、`*:端口`、`[::]:端口`、`:::端口`，同时严格匹配批准的端口，拒绝 `127.0.0.1` 等仅回环监听和其他端口。
- **仍需可信 HTTPS 终验**：只把 IPv6 wildcard 视为待验证的候选；后续必须通过 `curl --connect-to IP或域名:端口:127.0.0.1:端口` 的实际 IPv4 连接，校验目标公网 IP/域名对应的可信证书及 Web 路径。禁止 `--insecure`，IPv6-only 但 IPv4 连接失败时依旧阻断并回滚。
- **自动续接而非重装**：新 VPS 的初次安装沿用一次审批的九步任务；已有安装成功但 HTTPS 部分失败的 VPS 仅创建四步 HTTPS 续接计划，保留现有 3X-UI、受保护的原凭据和有效证书，不会重复安装。已更新的旧审批任务将提示刷新当前代码的固定步骤，**不能未经新授权自动执行更改过的远程脚本**。
- **测试覆盖**：纯本地 Linux 假 `ss`、假 x-ui CLI 和假 curl 的真实 Bash 执行，覆盖四种 wildcard 输出、只有回环、错误端口、IPv6-only 但 IPv4 连接失败，以及既有面板只读状态和凭据访问的一致行为。不会连接你的真实 VPS。

**更新测试：** 关闭已运行的 NetDeploy AI，在桌面双击 `netdeploy-ai-git\QuickStart-NetDeploy.bat` 更新，浏览器 Ctrl+F5 确认 `ALPHA v0.3.9`。进入原 VPS → 3X-UI → **继续完成 HTTPS**，刷新旧审批方案后只需授权 HTTPS 续接一次；不要重新安装 3X-UI，也不需要为了此误报关闭整个防火墙。证书和回环 HTTPS 检查通过后，还需在云服务商安全组允许已选面板 TCP 端口才能从外网打开。

## v0.3.8：修复 3X-UI 证书设置实际命令入口，首次安装一次完成 HTTPS

**已根据 3X-UI 官方 v3.11.0 源码确认此前真正的错误：** `/usr/bin/x-ui` 是交互式 Shell 菜单，不支持 `setting` / `cert` 子命令；NetDeploy v0.3.7 却把 `x-ui cert` 等命令发送给了菜单脚本。其不支持的命令可能输出帮助并返回 0，导致后续错误地报告 `XUI_CERT_SETTINGS_MISSING`。真正的 CLI 在 `/usr/local/x-ui/x-ui`，官方自身的 `x-ui.sh` 也是用它设置和读取证书。对应上游文件：[安装器](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/install.sh)、[控制脚本](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/x-ui.sh)、[Go 命令处理](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/main.go)。

- **全部切换到真正的程序**：HTTPS 配置、`-getCert`、`-getListen`、改监听地址，以及失败恢复都调用官方固定的 `/usr/local/x-ui/x-ui`；在前置检查就确认程序存在，防止先申请证书再发现 CLI 不可用。
- **失败恢复更完整**：开始修改前只读取原证书路径用于回滚，错误时恢复本机 `127.0.0.1` 监听及原来证书设置，不向公网开放明文 HTTP。配置成功后再读回证书路径和监听地址，等待服务启动，再验证 HTTPS 的可信证书和实际面板响应。
- **一键安装的真实逻辑**：**新的空白 VPS 安装只有一个九步部署任务、一次审批**。初次安装就自动继续证书与 HTTPS，不会要求再安装/审批第二个 3X-UI。IP/域名证书类型仍按 SSH 服务器地址自动识别。对已经安装成功、仅 HTTPS 失败的旧 VPS，继续使用**四步 HTTPS 续接任务**，不重装；由于旧任务已经停止且执行脚本改变，仍须明确一次新的高权限修复授权，不能跨版本自动重放旧的部署权限。
- **Git 更新后的旧审批计划自动识别**：旧版生成、尚未审批的 HTTPS 任务会自动标记为“需要刷新方案”，不会因用户点击批准而误运行上一版的错误命令。点击“更新为最新 HTTPS 修复方案”即可生成当前固定脚本，之后只需一次明确授权。新版本不擅自替换已保存的审批计划或静默执行。
- **界面更明确**：HTTPS-only 方案标题和确认按钮明确标记“继续配置已安装的 HTTPS，不重新安装”；避免误以为又要执行一次安装器。
- **模拟上游 CLI 的实际行为**：专项离线 Bash 测试同时模拟“不支持命令但返回 0 的菜单脚本”和“支持设置/查询的真正二进制”，验证证书成功、监听成功、可信 HTTPS、UFW 精确放行，以及证书读回失败时的安全回滚。绝不实际连接你的 VPS 或 Let's Encrypt。

**更新：** 关闭本地 NetDeploy 服务并双击桌面的 `netdeploy-ai-git\QuickStart-NetDeploy.bat`，再按 Ctrl+F5 确认 `ALPHA v0.3.8`。此前已经安装的 3X-UI **不要重装**；使用“查看现有面板 → 继续完成 HTTPS”即可。实际服务端 HTTPS 能否成功仍需在你的 Ubuntu VPS 验收；若云厂商安全组未允许管理端口，还需开放对应入站 TCP 端口。

## v0.3.7：HTTPS 连接失败诊断 + 自定义端口 + 任务结果实时显示

针对 2026-10-29 VPS 实际日志：Certbot 找到了可用的公网 IP 证书，最后 x-ui 服务切换到 HTTPS 后 `curl (7)` 无法连接 TCP 24443。**这不是证书申请失败，也不能仅凭 curl (7) 判断是云防火墙问题**。修复版先验证 x-ui 是否真正监听目标端口、其证书与监听 IP 配置是否持久保存，再将 TCP 连接和可信 TLS 验证分别诊断。

- **HTTPS 启用更可靠：** 检查并读回 3X-UI CLI 的证书路径与监听地址，等待服务重启后在所选 TCP 端口真正监听；本地 TLS 测试明确连接 `127.0.0.1`，但继续以目标公网 IP/域名校验证书身份（未关闭证书验证）。根据失败阶段分别报告 `XUI_CERT_SETTINGS_MISSING`、`XUI_LISTENER_SETTINGS_MISSING`、`XUI_SERVICE_FAILED`、`XUI_LISTENER_MISSING`、`XUI_TLS_IDENTITY_FAILED`、`XUI_LOCAL_TLS_CONNECT_FAILED`，失败时尝试恢复本地监听。已有证书有效时跳过重复签发。
- **新安装时自定义 3X-UI TCP 端口：** 在 VPS → 安装软件 → 3X-UI 选择想要的端口，默认 24443，可改成任意 **1024–65535**（不能与当前 SSH 端口冲突）；只给新安装使用。平台依据服务器记录的公网 IP 或域名自动选择对应的 IP/域名证书，并在同一部署任务中配置 HTTPS，不增加选择证书类型的步骤。已安装的面板端口从 VPS 实际安装记录读取，不擅自覆盖旧配置。
- **服务器自由添加/删除：** 首页顶部“添加 VPS”保持可见，服务器卡片右下角新加“删除服务器”。点击后说明只删除本地记录、不会卸载 VPS；有关联任务时明确勾选是否连同日志删除，但不再要求输入繁琐英文确认语句。SSH 指纹信任仍按地址+端口维护。
- **UFW 可手动关闭/重新启用（高风险、非默认）：** VPS → 网络端口增加 UFW 开关。关闭整个 UFW 会让所有端口不再受 VPS 本机防火墙过滤，因此必须先确认风险，绝不在安装时自动关闭；重新启用前自动为已核验的 SSH TCP 端口添加允许规则，避免把自己锁在 VPS 外。支持原有指定 TCP/UDP 端口精准放行。仅影响 VPS 的 UFW，不修改云服务商安全组。
- **任务完成后自动显示登录入口：** 任务详情打开状态下，前端每 5 秒查询任务并在状态变为完成/部分成功/失败时即时更新按钮；3X-UI 和 HTTPS 任务完成后直接出现“查看面板信息”，无需关闭再重新打开。新 HTTPS 升级任务不依赖原安装任务编号也能从真实 VPS 读取信息。

**更新步骤：** 先在旧 NetDeploy 的 PowerShell 窗口按 Ctrl+C 停止，再双击桌面 `netdeploy-ai-git\QuickStart-NetDeploy.bat`；刷新浏览器确认 `ALPHA v0.3.7`。会保留本地 `data/`、`.env`、SSH 主机指纹和 Windows 系统凭据。以上是 Alpha 的离线模拟验证，**尚未在你的真实 VPS 上再次配置/测试 HTTPS**，建议保留 VPS 快照后按界面一次性批准新的固定修复方案。

## v0.3.6：已有 3X-UI 直接查看，不再错误要求安装审批

本版本针对用户反馈的 **“3X-UI 明明已装，但面板还显示等待审批、0 步”** 问题，区分三个阶段：

- **未安装**：先通过可信 SSH 只读检测，再生成固定安装方案；安装修改 VPS 时仍需要一次批准。
- **已安装且可访问**：服务器概览和项目卡片标注 **“3X-UI 已安装”**；点击后只读读取真实服务状态和初始安装文件，显示面板地址、用户名、密码（隐藏显示）以及分别复制按钮。**此处不生成部署任务，也不要求审批。**
- **已安装、HTTPS 尚未完成**：显示当前本机安全访问方式和 SSH 隧道，同时提供 **“继续完成 HTTPS”**。即使之前的部署任务记录已删除，也可以在重新核验运行中的本机监听及受保护的安装记录后，仅生成 HTTPS 配置任务，不会重跑安装器。证书操作仍需要一次批准，云平台入站 TCP 80/面板端口需要可达。

安全细节：

- 状态检查由已固定 SSH 主机密钥与管理员认证保护。返回值只有“是否安装、服务是否运行、端口、受保护的记录是否可用、当前本机/HTTPS 状态”，不会默认返回密码或秘密访问路径。
- 只有用户点击“查看现有 3X-UI”才会读取登录数据。仅允许读取 VPS 上 root 拥有、权限 `0600` 的 `/etc/x-ui/install-result.env`，不写入本地数据库、部署日志或 AI 上下文。**这里是安装时凭据，并不保证与后来在 3X-UI 内修改的密码相同。**
- 公网直连 URL 只在实际远端 HTTPS 服务响应且证书与当前公网 IP/域名匹配时展示。不能验证的公网 HTTP 或 TLS 不会生成不安全的点击入口。
- 对于 **外部手动安装或缺少可信安装文件** 的服务器，只显示“已安装”及安全的排查说明，提示在 VPS 云控制台运行 `x-ui settings` 查看/更新账号。不会猜测密码、以默认账号替代、删除面板或静默覆盖。

以前遗留的 **0 步待审批** 记录现在会在页面中引导查看已有面板，而不是显示“确认并安装”。无需手动清空数据库；如需清理，可单独删除该本地任务记录，远端软件不会被卸载。

**升级：** 退出本地运行中的服务，双击桌面 `netdeploy-ai-git\QuickStart-NetDeploy.bat` 更新，然后浏览器 Ctrl+F5，确认显示 `ALPHA v0.3.6`。数据和 SSH 指纹仍会保留。此版本还需在你自己的 VPS 上做首次实机验收。

## v0.3.5：指纹弹窗布局与审批入口体验修复

- **SSH 指纹弹窗修复：** 原版扫描时采用横向 flex 布局，扫描结束仍把状态卡、指纹、核对命令和关闭按钮全部塞在横向容器中，导致图文错位、指纹与按钮断行。现在加载状态单独横向排列，结果改为固定纵向卡片、长 SHA-256 自动换行、移动端自适应。
- **不必要的确认被移除：** 原指纹与当前指纹相同时，只显示“SSH 主机身份验证通过”及“返回服务器控制台”；云控制台核对方式收进可选的折叠区域。首次信任或发现指纹变化时，仍必须独立核验和明确确认。
- **审批入口前置：** VPS 控制台“概览”顶部直接显示“待审批 → 继续审批部署”，不再隐藏在“最近任务”。任务列表每条记录明确标出“继续审批 / 查看进度 / 排查失败 / 查看结果”，点击后直接进入对应流程。
- **10 分钟计划过期：** 直接提示并提供“更新方案并继续审批”按钮，不再让用户先点审批、再遇到旧计划过期提示。选择项目时会优先复用已有仍有效的待审批或运行中任务，避免反复创建重复记录。
- **操作分类解释：** 五个标签统一用自然语言——“概览、安装软件、网络端口、SSH 安全、服务器设置”。每个界面说明它做什么、什么时候需要用；常用操作突出，低频维护与技术命令默认折叠。
- **防止回归：** 增加纯 Node.js 的真实前端函数模拟测试，覆盖审批可见性、计划过期、重复计划复用、指纹一致和变化两种状态与纵向 CSS 布局；纳入 GitHub Windows/Ubuntu 自动测试。

**更新方式不变：** 停止本地服务，双击桌面的 `netdeploy-ai-git\QuickStart-NetDeploy.bat`，自动更新并打开控制台。保留旧 VPS 数据及 SSH 密钥记录。仍须在自己的浏览器验证视觉、缩放和键盘体验；自动化测试不代表已经远程操作 VPS。

## v0.3.4：VPS 一站式操作、APT 自动等待和端口放行

**本版针对 2026-10-29 Ubuntu 26.10 实机日志**：3X-UI 已安装，第七步因 `unattended-upgr` 占用 dpkg 锁失败；后续 HTTPS 则因 Let’s Encrypt 无法从公网连入 TCP 80 而失败。**这两个问题不需要重装 3X-UI。**

- **无需反复确认**：服务器卡片点击进入统一控制台，“概览 / 项目部署 / 端口与防火墙 / 连接安全 / 编辑删除”集中操作。部署计划将摘要和“确认并一键部署”按钮前置，只需一次批准；技术细节可展开，原先手动复制的 `DEPLOY ...` 语句不再必须输入，后台高权限校验全部保留。
- **APT 自动等待**：依赖存在时跳过重复安装；需要时使用 APT 自带的 `DPkg::Lock::Timeout=240`，等待系统更新释放锁。不会删除锁文件、杀掉自动更新进程或关闭 Ubuntu 安全更新。
- **完整 HTTPS**：新的 3X-UI 部署在同一个任务内完成本机安全安装、IP/域名证书签发、自动续期与 HTTPS 验收；如果已经安装，则从对应 VPS 的项目选项自动转为 HTTPS-only 后续配置。签发前尝试给 UFW 放行 TCP 80，证书验证通过后才尝试放行管理面板端口。
- **按端口放行**：在 VPS 控制台的“端口 / 防火墙”输入 1–65535 端口并选择 TCP/UDP，一键执行固定 UFW 规则。不提供一键关闭整个防火墙或开放所有端口。UFW 未启用或未安装时会明确显示。
- **两种防火墙**：这只能更改 **VPS 内的 UFW**。若云厂商安全组或云防火墙未允许公网 TCP 80，Let’s Encrypt 仍会报 `LE_HTTP01_UNREACHABLE`。要直接打开 HTTPS 面板，云厂商还需允许 TCP 24443（或实际面板端口）。**平台未连接云厂商 API，无法替用户修改其云安全组。** 为使 HTTP-01 自动续期正常，UFW 的 80/TCP 允许规则会保留。
- **UI 调整**：VPS 卡片双列大尺寸，整张卡片可点击，鼠标悬停、加载和反馈更明显。项目选择、端口操作和服务器安全信息都在同一服务器控制台。移动端自动变为单列，遵循减少动态效果设置。

**更新：** 关闭现有服务并运行桌面的 `netdeploy-ai-git\QuickStart-NetDeploy.bat`。请勿删除 `data/`、`.env`、`known_hosts`。这是 Alpha，公网证书签发与云安全组连通性仍需在你的 VPS 实机验收。

## v0.3.3：VPS 全生命周期管理 + 工作台 UI 优化

- **服务器编辑、删除：** 首页优先展示 VPS，直接点击“编辑”“登录方式”“指纹 / 重装”“检测连接”“删除”。有部署历史时为了防止旧任务操作新地址，仅允许修改显示名称。删除记录需要确认；若关联任务存在还需同意一并删除其本地日志和历史，**不会卸载 VPS 软件**。
- **VPS 重装后安全重新信任：** 相同 IP/端口下，当 SSH 主机公钥发生变化，点击 **指纹 / 重装** → 比对旧指纹与新指纹 → 在 VPS 云厂商独立控制台运行界面提供的 `ssh-keygen -lf ... -E sha256` → 勾选核对 → 点击 **服务器已重装 → 更新信任** → 输入确认语句。仅替换该 IP/端口的旧信任记录，自动备份 `data/known_hosts`，不影响其他 VPS 指纹。
- **同 IP 多个条目：** 同一地址/端口共享一份主机密钥，重新信任会同时使这些记录的旧环境检测结果和待审批计划失效。旧版已完成的 3X-UI 任务保留作为历史，但因已重装 **不能拿它再读取新 VPS 的登录信息或继续升级**。新服务器需生成新计划。
- **避免无意重复添加：** 面板识别已存在的相同 IP/端口，提示直接使用或编辑已存在的条目。删除冗余条目不会自动清空共用的 `known_hosts`，避免影响其他服务器。
- **界面升级：** 服务器管理移到总览顶部，新增固定顶部“添加 VPS”，收紧大面积装饰区，突出高频动作。卡片悬停抬升/发光、按钮点击回弹及操作加载中状态；所有成功/失败反馈更明显。遵循系统“减少动态效果”，在触屏环境取消不必要的悬停位移。
- **安全边界：** 没有可靠的独立核对，不能跳过或强制接受改变的 SSH 指纹；有执行中的任务时不能更新指纹或删除服务器。修改了信任后需要重新检测操作系统并确认 SSH 用户密码是否仍有效。

**更新：** 关闭旧服务，双击桌面 `netdeploy-ai-git\QuickStart-NetDeploy.bat`；Git 更新保留原有 `data/`、`.env` 和系统凭据。刷新浏览器确认版本 `ALPHA v0.3.3`。当前仍是 Alpha，未在你的真实 VPS 上自动执行指纹重置。

## v0.3.2：IP/域名证书自动识别与 Certbot 错误定位

- **新安装无需再选择访问模式或证书类型**：在服务器管理中填公网 IPv4，3X-UI 自动生成 IP 短期证书方案；填域名，自动生成域名证书方案。后台仍保留严格参数验证和部署审批。安装证书失败时不将未加密的 HTTP 面板向公网开放。
- **已安装 3X-UI 无需重装**：从原部署任务直接点击“启用 HTTPS 直连”；或者在项目中心再次选择这台已经由 NetDeploy 安装过的 VPS，自动生成独立 HTTPS 升级方案。不再执行 3X-UI 安装器。
- **修复 Exit 34 无效报错**：Certbot 原始输出不能直接流入任务日志（包含 ACME 验证细节），但会按固定规则报告 `LE_HTTP01_UNREACHABLE`、`LE_PORT80_BUSY`、`LE_HTTP01_CHALLENGE_FAILED`、`LE_RATE_LIMIT`、`LE_PROFILE_UNSUPPORTED`、`CERTBOT_ARGS_INVALID`、`LE_DNS_ERROR` 等类别，附可执行的排查方向；无法分类时指出 VPS 端 `/var/log/letsencrypt/letsencrypt.log` 的位置。
- **防止不必要的重复申请**：如 VPS 上已有未过期且匹配目标 IP/域名的证书，跳过新 ACME 请求，继续检查证书及自动续期。所有远程更改仍需显式审批，**不会自动重试失败签发**，也不会修改云厂商安全组。
- **你的现有 VPS**：Certbot 5.5.0 已满足 IP 证书命令支持要求；但先前 2026-10-29 的 Exit 34 仅记录通用失败，不能据此确定是云安全组的 TCP 80、CA 限流还是其他原因。更新后，从失败的证书任务点“修复后重新生成证书方案”，在核查公网 TCP 80 后审批，新日志会明确报告分类。**请不要重复安装已有 3X-UI。**

## v0.3.1：任务清理、SSH 错误诊断、桌面一键启动

- 任务列表和详情页都提供删除入口；只有 **planned / failed / completed / partial / interrupted** 等非运行任务可以删除。必须确认“仅删除本地历史”；不会 SSH 卸载软件，也不会影响 VPS、`known_hosts` 或 Windows 凭据库。
- 已有 HTTPS 升级任务引用的 3X-UI 安装任务不能直接删除，必须先清理子任务，避免丢失原安装入口。删除前注意：对应的任务日志、审批记录和本地访问入口会一起消失，**建议先自行备份日志**。
- SSH 错误区分：指纹不匹配、尚未信任的密钥、认证失败、TCP 端口拒绝、连接超时、DNS 错误、算法不匹配和其他握手失败。**已保存 SSH 密码只代表凭据可用，不代表服务器已接受认证**。
- Windows `QuickStart-NetDeploy.bat` 或上面的 PowerShell 一行命令会安全检查 GitHub 来源、备份数据、自动更新并启动本地面板；自动生成内部管理员令牌，仅本机同源允许自动登录。NAS/Linux/公网无此免登录行为。


## v0.3.0：自动连接、HTTPS 直连与一键复制

本版本重点改善 Windows 的日常使用体验，并提供严格审批的 3X-UI HTTPS 转换。**HTTPS 证书签发与公网访问仍属 Alpha；请先在有云快照的 VPS 验证。**

### 服务器密码安全保存和自动检测

- 已添加 VPS 不需要重新添加。点击 **登录方式**，输入一次 SSH 密码，勾选 **保存到 Windows 系统凭据库** 并保存。之后从同一 Windows 用户启动 NetDeploy AI，程序可以从原生凭据库读取密码，更新/重启无须重新输入。
- 这个功能 **仅支持 Windows 原生 Credential Locker**，不允许明文保存到 `.env`、SQLite、Git 或日志。NAS/Linux 暂继续使用临时密码或独立 SSH 密钥。换 Windows 账号、电脑或项目数据目录后，需要再次授权保存。
- **生成部署计划时自动重新执行只读环境检测**，管理员不必每次先手动点击检测。审批前仍会执行第二次安全检测；已有 SSH 主机指纹校验不受影响。
- 系统凭据库保存为**可选**。请为 VPS 使用专用权限受限的账户；当前 Alpha 部署器要求 root，持久保存 root 密码有较高风险，建议结合 VPS 快照和本机账户保护。

### 3X-UI IP/域名证书与直连

- **新安装：** 3X-UI → 部署项目，选 VPS，按需调整面板端口，自动从已填写的服务器公网 IPv4 或域名生成相应 HTTPS 证书方案，不再要求选择证书类型或访问模式；HTTP 本机监听仅作为证书成功前的安全部署阶段。
- **已安装的旧面板：** 在 **部署任务** 里打开此前成功安装的 3X-UI 任务，点击 **启用 HTTPS 直连**，阅读全部命令、风险并单独审批。**不重装，不覆盖已存在的 3X-UI**；只运行证书申请、续期设置、HTTPS 验收。
- 事先确认：VPS 具有正确的公网 IPv4，域名 A 记录解析到服务器，**TCP 80 能被公网访问**用于 HTTP-01 证书签发，且 VPS 的 Certbot 支持相应的证书模式。IP 短期证书有效期 **160 小时**，依赖自动续期定时器持续运行。
- 只有可信证书完成签发、校验、续期配置及本机 HTTPS 验证后，才尝试将管理端由 `127.0.0.1` 改为 `0.0.0.0`。安装/证书失败不会自动开启明文公网 HTTP；启用 HTTPS 后若验证失败，程序会尝试恢复本机监听。
- 证书签发并不等于公网自动放行。**要从浏览器直接打开，还要在云防火墙、安全组以及 VPS 防火墙中允许所选 TCP 面板端口。** 平台不会为你自动更改这些安全规则。建议限制来源 IP、开启 3X-UI 的 2FA、确保续期和服务健康。
- 安装成功后点 **查看面板登录信息**，证书和续期检查通过时出现 HTTPS 直达地址。浏览器点击打开；用户名、密码、面板 URL 各自有**复制按钮**，不再需要手动选择文本。
- 已完成的 HTTP-only 面板仍可继续用旧 SSH 隧道。申请失败、超时或自动续期不正常时需要先检查 VPS 再继续，不能自动重试安装或无条件开放公网端口。

**安全界限：** NetDeploy AI 自己的 8787 端口仍只供本机/SSH 隧道访问，不能暴露在公网。公网 HTTPS 仅针对经过审批的 3X-UI。账号/密码只在用户明确请求时通过已验证 SSH 通道读取，不写入任务或 AI 日志。

## v0.2.1：修复审批前环境变化误报

- 修复审批前的二次 SSH 环境检测：原来直接比较两次检查的所有数值，连 `FREE_KB` 这种会持续波动的磁盘剩余空间也要求完全相同，导致“服务器环境已变化”的误报。
- 新版保留创建部署计划时的完整安全条件快照（除剩余空间绝对值），审批前继续校验 CPU、root 权限、系统版本、systemd、已有 x-ui、Docker、端口检测等关键字段。任一关键条件变化仍要求重新生成计划。
- `FREE_KB` 可以正常变化，但每次审批时都必须通过项目的空间门槛（3X-UI 最少 600000 KB）；空间不足或读数未知仍然阻止安装。
- 旧版部署任务没有安全快照，**不能直接复用**。更新后在原任务中点击“重新检查并生成新方案”（只重新检测和创建计划，不会自动执行），再次检查命令与风险提示后重新审批。
- 在 Git 克隆目录执行 `git pull --ff-only origin main` 更新，或关闭服务后运行 `Update-NetDeploy.bat`；保留原有 `data/`、`known_hosts` 和 `.env`。

## v0.1.2 修复说明

- 修复 Windows 对外部 `ssh-keyscan` 工具的依赖。密码模式继续使用 Paramiko；SSH 握手阶段读取主机公钥无需先登录、无需密码。
- 校验/记录主机密钥改用 Paramiko 的 `HostKeys`，非 22 端口使用 `[host]:port` 格式；仍需在可信渠道对照 SHA256 指纹。
- 连接失败时面板给出端口检测命令和明确的网络/握手诊断。
- **更新时保留旧版 `data/` 目录和原管理员 `NETDEPLOY_ADMIN_TOKEN`，否则登录和 VPS 列表可能丢失。** 仍未经过真实 VPS 验收。

## v0.1.3 修复说明

- 修复重复确认 SSH 主机密钥时，即使与 `data/known_hosts` 中已固定的公钥完全相同，也错误提示“禁止从面板覆盖”的问题。现在相同公钥重复确认直接成功，且不重复写入；VPS 重装或主机密钥变化仍必须拒绝自动覆盖。
- 前端区分“已信任且未变化”和“首次成功固定”；不需要删除旧版 `data/known_hosts` 或重新添加 VPS。
- **本地升级：** 停止旧服务，在 Git 克隆目录执行 `git pull --ff-only origin main`，再运行 `Start-NetDeploy.bat`；不要使用 `git reset --hard` 或删除 `data/`。

