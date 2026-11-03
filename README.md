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

**Windows 本机启动**：只需预先安装一次 [Docker Desktop](https://www.docker.com/products/docker-desktop/)（切换为本机 Linux 容器）。以后双击 `QuickStart-NetDeploy.bat` 即可：程序自动生成独立 Worker 令牌，在后台检测 Docker、按需启动 Docker Desktop 和 Codex Worker，并复用上次的 ChatGPT 登录状态；**不必再运行 `Enable-Codex-Windows.bat`，也不必打开 Codex 桌面程序**。首次启动时，Docker 镜像可能需要下载与构建；NetDeploy AI 面板会先正常打开，可在左侧「Codex AI」查看启动状态。没有安装 Docker、Docker 启动失败或网络异常都不影响普通 VPS 管理与部署。只有首次连接账号或登录失效时才需要重新授权。

如不希望自动启动 Docker，在项目私有 `.env` 中添加 `NETDEPLOY_CODEX_AUTO_START=0`；其他功能仍正常使用。手动启用脚本仅保留作故障排查入口。Codex Worker 使用 Docker 的 `unless-stopped` 重启策略，Docker Desktop 已启动时会自动恢复容器。

启动器会优先识别 Docker Desktop 的本机 `desktop-linux` 和 `default` 上下文，并验证实际运行的是 **Linux 引擎**。即使你平时使用其他 Docker 上下文，NetDeploy AI 也不会修改全局默认上下文或把 Codex 凭据发往远程 Docker。如果 Docker Desktop 确实运行在 Windows containers 模式，请在 Docker Desktop 菜单切换到 **Linux containers**；单纯的 Docker Desktop 尚未启动不再被误报为上下文错误。

**Docker / NAS 启动**：在项目私有 `.env` 中设置至少 24 位随机 `NETDEPLOY_WORKER_TOKEN`（与管理员令牌不同），然后运行 `docker compose --profile ai up -d --build`。现有主程序不会把 SSH 密钥、数据库或 Docker Socket 挂载进 AI Worker。

进入后台左侧 **Codex AI** → **使用 ChatGPT 账号连接**，在浏览器打开官方验证页并输入一次性设备代码。设备码登录（Beta）需要在 ChatGPT 安全设置中启用。授权成功后，打开部署任务点击 **AI 只读排障**。

Codex 登录凭据仅存放在独立 Worker 的 `codex-auth` Docker 卷内，等同密码，请妥善保护；退出登录可清除凭据。点击「AI 只读排障」会将经过脱敏的任务日志摘录及基本系统信息发送给 Codex，请避免在任务日志里保存敏感信息。ChatGPT 订阅有使用限制，实际支持以账号权限为准；个人订阅不会共享给其他用户。AI 无权执行 VPS 命令、修改部署方案或跳过审批。没有启动 Worker 时，常规部署功能不受影响。

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

