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

## 支持的项目

| 项目 | 当前支持情况 |
| --- | --- |
| **3X-UI** | 自动安装，支持 IP / 域名 HTTPS |
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

