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
- **Codex AI（可选）**：管理员用自己的 ChatGPT 账号登录，只读分析安装日志；不需要另填 API Key。

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
- **3X-UI**：IPv6 VPS 可选择「本机 SSH 隧道」或「NPM 反向代理」。NPM 模式会经单独风险审批开放原始 HTTP，并额外从 VPS 本机实际探测 IPv6 HTTP 监听；生成的链接采用 `http://[IPv6]:端口/路径`。原始 HTTP 不加密，必须在云安全组限制可信来源。
- **S-UI**：IPv6 VPS 支持「本机 SSH 隧道」及「NPM 反向代理」（面板仍仅监听 `127.0.0.1:2095`）。可让 NPM 使用指向本机的域名 **AAAA 记录**对外提供 HTTPS，但需要 NPM 的 IPv6 80/443 入站与证书配置正确。
- **证书限制**：Let’s Encrypt 已能签发 IPv6 IP 证书，但 NetDeploy AI 当前内置 3X-UI / S-UI Certbot 安装脚本仍是按 IPv4 地址及 DNS A 校验编写。为防止错误签发或错误标记部署成功，**暂时不允许 IPv6 SSH 地址使用内置自动 HTTPS 流程**。请使用 SSH 隧道或 NPM + AAAA 域名，后续单独适配并验收 IPv6 ACME/证书续期。
- UFW 仅管理 VPS 本机规则；云厂商 IPv6 防火墙/安全组还需独立放行。双栈 VPS 的 A / AAAA DNS 记录必须与实际服务对应，避免证书验证命中错误服务器。

## Windows 快速开始（推荐）

先安装 [Git for Windows](https://git-scm.com/downloads/win) 和 [Python 3.12+](https://www.python.org/downloads/windows/)（需包含 `py` 启动器）。

打开 **PowerShell**，依次执行：

```powershell
git clone https://github.com/slobys/netdeploy-ai.git
cd netdeploy-ai
.\QuickStart-NetDeploy.bat
```

启动后在浏览器访问 **http://127.0.0.1:8787**。Windows 本机模式首次启动可自动登录。

**以后启动或更新：** 先在旧服务窗口按 `Ctrl+C` 停止，再双击项目文件夹中的 `QuickStart-NetDeploy.bat`。程序会检查更新并保留本地数据。

## 使用 ChatGPT 订阅连接 Codex（可选）

**Windows 默认原生模式（无需 Docker）**：只需安装 Git 和 Python。运行 `QuickStart-NetDeploy.bat` 后，后台自动创建专用 Python 环境并安装官方 Codex SDK，**不启动 Docker Desktop、WSL 或 Codex 桌面软件**。首次下载 SDK 的 Windows 运行组件可能需要一些时间，后台「Codex AI」可显示进度。连接自己的 ChatGPT 账号并完成首次设备码授权后，正常重启会复用登录状态（登录失效时需重新授权）。

原生 Worker 仅监听 `127.0.0.1:8789`，使用 `%LOCALAPPDATA%\NetDeployAI\codex-native` 下的独立工作区、SDK 环境与登录目录；不会把 NetDeploy 的 SSH 密码、管理员令牌或数据库路径传给 Worker。Windows 原生沙箱开启 `prefer_mxc`，只读诊断禁止提权审批；**但同一 Windows 用户下的进程隔离不等于 Docker / 独立用户的强隔离**。请在可信的本机使用，不要把后台公开到互联网。

如需关闭自动启动，在本机 `.env` 添加 `NETDEPLOY_CODEX_AUTO_START=0`；不影响其他 VPS 管理功能。之前安装的 Docker 版 Worker 不会被自动卸载或清除数据，但 Windows 默认不再调用它。

**Docker / NAS 启动**：在项目私有 `.env` 中设置至少 24 位随机 `NETDEPLOY_WORKER_TOKEN`（与管理员令牌不同），然后运行 `docker compose --profile ai up -d --build`。现有主程序不会把 SSH 密钥、数据库或 Docker Socket 挂载进 AI Worker。

进入后台左侧 **Codex AI** → **使用 ChatGPT 账号连接**，在浏览器打开官方验证页并输入一次性设备代码。设备码登录（Beta）需要在 ChatGPT 安全设置中启用。授权成功后，打开部署任务点击 **AI 只读排障**。

登录凭据分别保存在 Windows 原生 Worker 的专属 `CODEX_HOME` 或 Docker/NAS Worker 的私有 `codex-auth` 卷中；请像密码一样保护，退出登录可清除授权。点击「AI 只读排障」会将脱敏的任务日志摘录和基本系统信息发送给 Codex，请勿把私密数据写进部署日志。ChatGPT 套餐额度有限，个人登录不能共享给其他用户；AI 不会直接审批或执行 VPS 安装。Codex 不可用不影响普通部署。

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

