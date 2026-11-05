# NetDeploy AI

**一个用网页管理 VPS、快速部署常用开源项目的小工具。**

添加服务器、检查 SSH 连接、选择软件、确认部署，整个过程都可以在浏览器中完成。

> **当前为 Alpha 测试版**，请先在可以备份或重装的 VPS 上试用。

[📖 在线使用文档](https://slobys.github.io/netdeploy-ai/) · [🚀 安装教程](https://slobys.github.io/netdeploy-ai/installation.html) · [❓ 常见问题](https://slobys.github.io/netdeploy-ai/troubleshooting.html) · [💬 反馈问题](https://github.com/slobys/netdeploy-ai/issues)

## 主要功能

- **VPS 管理**：添加服务器、SSH 密码/密钥连接、核对主机指纹。
- **向导式部署**：自动检查运行环境，确认安装方案后再执行，并显示进度和日志。
- **HTTPS 证书**：3X-UI、S-UI 可自动申请 IP/域名证书，也可交给 NPM 统一管理 HTTPS。
- **端口管理**：管理 VPS 上的 UFW 规则，提供常见云厂商安全组入口。
- **自定义界面**：多种主题颜色、明暗模式和阅读字号。
- **Codex AI（可选）**：使用自己的 ChatGPT 账号，通过自然语言查询任务、打开面板页面、生成待审批部署方案或分析安装日志，无需另填 API Key。

## 支持的项目

| 项目 | 当前支持情况 |
| --- | --- |
| **3X-UI** | 自动安装，支持 IP/域名 HTTPS 或 NPM 统一 SSL；NPM 模式可提供公网 HTTP 管理地址 |
| **S-UI** | 自动安装，支持 IP / 域名 HTTPS |
| **sing-box** | 自动安装内核，服务端配置需自行完成 |
| **wg-easy** | Docker Compose 自动部署，需完成首次设置 |
| **[Dockge Apps](https://github.com/slobys/dockge-apps)** | 二开应用中心（NPM、IT-Tools、MyIP）；缺 Docker 可使用官方一键脚本，管理端口随机或自定义；新安装默认公网 IP 直连，执行前需确认风险 |
| **Hysteria2** | 提供部署引导，暂不支持一键安装 |

## IPv6 VPS 支持（3X-UI / S-UI）

- 添加服务器时可填写 **公网 IPv4 或 IPv6**（例如 `2606:4700:4700::1111`，**不要加方括号**），连接过程保持 SSH 指纹核验、密码/密钥认证与部署审批。支持纯 IPv6 和双栈 VPS；连接地址由用户选择。
- **SSH 指纹排查**：Windows `Test-NetConnection -ComputerName IPv6 -Port 22` 的 `TcpTestSucceeded=True` 只代表 TCP 端口可达，不能证明 sshd 正常协商。若步骤 2 扫描失败，可以在 PowerShell 执行 `ssh-keyscan -6 -T 15 -p 22 IPv6` 区分 SSH 协议异常与扫描超时。NetDeploy 会区分 Banner、算法和连接中断，仅对临时 Banner/握手中断在未认证阶段有限重试；扫描返回的指纹仍须去云厂商控制台独立核对，软件绝不自动信任。
- **3X-UI**：IPv6 VPS 可选择本机 SSH 隧道、NPM 反向代理或内置自动 HTTPS。IP 证书采用约 160 小时的短有效期配置和独立 Certbot 续期；域名 HTTPS 要求 DNS AAAA 正确。HTTPS 成功会显示 `https://[IPv6]:端口/路径`（域名证书则显示域名 URL）；NPM 模式仍保持明确的公网明文 HTTP 风险提示。
- **S-UI**：IPv6 VPS 同样可选择本机 SSH 隧道、NPM 或自动 HTTPS。签发并校验证书后才开放管理端口 2095；**订阅端口 2096 始终仅监听本机 `127.0.0.1`**。HTTPS 失败会尝试恢复本机监听；异常服务不会回退成公网明文 HTTP。
- **自动证书检查**：IPv6 签发前验证目标地址确实分配给 VPS；若使用域名，则要求其全部 AAAA 记录指向当前 IPv6。Certbot 使用 IPv6 TCP 80 接受 HTTP-01 挑战，签发后校验可信证书链、IPv6 TLS 监听和本机公网 IPv6 连接。IPv6 IP 证书使用独立 Certbot 每四小时检查续期；域名使用系统 Certbot 定时器。
- **上线前仍需实机验收**：UFW 必须启用 IPv6（活跃时 `/etc/default/ufw` 的 `IPV6=yes`），云厂商 IPv6 安全组需独立放行 TCP 80 和管理端口、限制管理来源；本机 curl 验证不等于已从外部网络验证。IPv6 ACME 自动化虽已有模拟测试，尚未在真实 IPv6 VPS/Let’s Encrypt 生产环境实测；建议先用可重装的测试 VPS 试用。IPv4 原流程不变。

## Windows 快速开始（推荐）

先安装 [Git for Windows](https://git-scm.com/downloads/win) 和 [Python 3.12+](https://www.python.org/downloads/windows/)（需包含 `py` 启动器）。

打开 **PowerShell**，依次执行：

```powershell
git clone https://github.com/slobys/netdeploy-ai.git
cd netdeploy-ai
.\QuickStart-NetDeploy.bat
```

启动后在浏览器访问 **http://127.0.0.1:8787**。Windows 本机模式首次启动可自动登录。

**以后启动或更新：** 双击项目文件夹中的 `QuickStart-NetDeploy.bat`。面板正在运行时会直接打开网页。停止面板后再次双击会检查更新、备份本地数据并在后台启动。需要在终端查看输出或用 `Ctrl+C` 停止时，可单独运行 `Start-NetDeploy.bat`。

## 使用 ChatGPT 订阅连接 Codex（可选）

**Windows 默认原生模式（无需 Docker）**：只需安装 Git 和 Python。运行 `QuickStart-NetDeploy.bat` 后，后台自动创建专用 Python 环境并安装官方 Codex SDK，**不启动 Docker Desktop、WSL 或 Codex 桌面软件**。首次下载 SDK 的 Windows 运行组件可能需要一些时间，后台「Codex AI」可显示进度。连接自己的 ChatGPT 账号并完成首次设备码授权后，正常重启会复用登录状态（登录失效时需重新授权）。

旧的 `Enable-Codex-Windows.bat` 入口也会进入原生启动流程。请用普通 Windows 用户权限启动面板。

原生 Worker 仅监听 `127.0.0.1:8789`，使用 `%LOCALAPPDATA%\NetDeployAI\codex-native` 下的独立工作区、SDK 环境与登录目录；不会把 NetDeploy 的 SSH 密码、管理员令牌或数据库路径传给 Worker。Windows 原生沙箱开启 `prefer_mxc`，只读诊断禁止提权审批；**但同一 Windows 用户下的进程隔离不等于 Docker / 独立用户的强隔离**。请在可信的本机使用，不要把后台公开到互联网。

如需关闭自动启动，在本机 `.env` 添加 `NETDEPLOY_CODEX_AUTO_START=0`；不影响其他 VPS 管理功能。之前安装的 Docker 版 Worker 不会被自动卸载或清除数据，但 Windows 默认不再调用它。

**Docker / NAS 启动**：在项目私有 `.env` 中设置至少 24 位随机 `NETDEPLOY_WORKER_TOKEN`（与管理员令牌不同），然后运行 `docker compose --profile ai up -d --build`。现有主程序不会把 SSH 密钥、数据库或 Docker Socket 挂载进 AI Worker。

进入后台左侧 **Codex AI** → **使用 ChatGPT 账号连接**，在浏览器打开官方验证页并输入一次性设备代码。设备码登录需要在 ChatGPT 安全设置中启用。授权后，可以输入「最近哪些部署失败了」或「为东京 VPS 生成 S-UI 部署方案」。使用面板中的 VPS 完整名称和项目名称，面板会自动只读预检并打开方案，由你审阅后确认执行。自动方案中的 3X-UI、S-UI 和 Dockge Apps 采用 SSH 隧道访问。自定义端口、证书或公网模式可打开部署向导设置。查看具体安装失败原因时，可以在对应任务中点击 **AI 只读排障**。

登录凭据分别保存在 Windows 原生 Worker 的专属 `CODEX_HOME` 或 Docker/NAS Worker 的私有 `codex-auth` 卷中，退出登录可清除授权。面板指令会将输入文字、服务器名称、近期任务状态和项目名称等摘要发送给 Codex。使用「AI 只读排障」时会另外发送脱敏的日志摘录和基本系统信息。请勿在指令、名称或日志中填写凭据。ChatGPT 套餐额度有限，个人登录仅供本人使用。

## 如何部署软件？

1. 点击 **添加 VPS**，填写服务器地址和 SSH 登录信息。
2. 核对 **SSH 主机指纹**，检查服务器环境。
3. 打开 **项目中心**，选择要安装的软件。
4. 查看安装方案、确认执行，最后查看结果。

Docker / NAS 用户可参考 [Docker 部署教程](https://slobys.github.io/netdeploy-ai/installation.html#docker)。各项目的具体要求见 [部署文档](https://slobys.github.io/netdeploy-ai/deployments.html)。

## 使用前请注意

- 安装任务需要相应的系统权限；部分项目要求 Debian / Ubuntu、Docker 或指定端口。
- NetDeploy 控制台默认只供本机访问，**不要把管理端口直接暴露到公网**。
- SSH 主机指纹必须通过可信渠道核对；证书签发还需正确的 IP / 域名及防火墙规则。
- 项目尚在测试阶段，自动化测试通过不等于所有 VPS 环境都已实机验收。

**开源协议：** [MIT License](LICENSE)

