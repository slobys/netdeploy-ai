# S-UI 安全部署 Skill（NetDeploy AI）

## 适用范围

本 Skill 仅供 AI 提供只读部署建议和操作解释；**禁止根据本文件拼接 Shell 命令自动执行**。远程安装必须使用源码 `app/s_ui.py` 与 `app/sui_https.py` 中固定、审计过的脚本，经 NetDeploy 管理员批准后通过受信任的 SSH 主机密钥执行。

上游项目：[alireza0/s-ui](https://github.com/alireza0/s-ui)，固定版本 **v1.6.6**。可用系统：Debian/Ubuntu root SSH VPS、x86_64/aarch64、systemd；`2095/tcp` 与 `2096/tcp` 应空闲。已存在的 s-ui 目录、服务或可执行文件应停止重新安装。

## 部署阶段

1. 读取 Linux、root、CPU、systemd 与已安装服务状态；确认端口及磁盘空间，没有已安装 S-UI 才可创建安装计划。
2. 确认 curl / Python3 / OpenSSL / SHA-256 / tar 依赖。
3. 只下载 GitHub Releases 固定 v1.6.6 的官方架构资产，校验由 GitHub Releases 提供的 SHA-256，拒绝不安全归档内容。
4. 在服务**首次启动前**完成随机管理员账户、密码、Web/订阅路径初始化；将管理 `2095` 和订阅 `2096` 的绑定地址限制为 `127.0.0.1`。凭据只保存在 VPS `0600` 受保护文件，不写入 NetDeploy 日志。
5. 启动 systemd 服务，确认管理 2095/TCP、订阅 2096/TCP **均且仅**监听 IPv4 `127.0.0.1`（存在额外 `0.0.0.0` 或 IPv6 公网监听必须判为不安全），验证本机 Web 响应，失败时停止并禁用服务。不可在公网开放未经 TLS 验证的管理界面。
6. 默认继续执行 **HTTPS 四步**：校验 VPS 公网 IPv4 与证书域名 DNS A、UFW 仅按需放行 ACME 80/TCP、复用受审核 Certbot IP/域名证书签发与续期模块、原生写入 S-UI `webCertFile`/`webKeyFile`/`webDomain` 并将 `webListen` 改为公网监听。
   IP 证书由独立 Certbot 5.8.0 venv 与 `netdeploy-certbot-renew.timer` 续期，单独保存在 `/etc/netdeploy/letsencrypt`。域名证书使用原系统 Certbot；保留 Debian 13 旧版 APT Certbot 和其他站点的续期文件，失败后可以重新审批四步 HTTPS 续接，不重复安装 S-UI。

7. 用真实 IPv4 TLS + 证书身份验证 2095 端口，订阅 2096 始终本机。只有验收通过才放行 UFW 2095 并记录安全 HTTPS 地址；任何后续失败优先停止服务、撤销公网配置并恢复本机，不得提供公网 HTTP 回退。

## 操作建议

- 点击已安装的 S-UI 卡片只能安全只读查询状态；当用户主动点击“查看 S-UI 面板信息”时，经可信 SSH 获取初始地址/用户名/密码/本机 SSH 隧道命令。
- 选择安装只需**一次固定高权限步骤审批**；不能调用官方未锁定版本的在线安装脚本，也不能使用 AI 生成的远程 Shell。
- 新安装默认自动识别 IP/域名证书，一次审批完成 S-UI 本机安装及可信 HTTPS；支持已安装、仍本机监听的 S-UI 单独执行四步 HTTPS 续接（无需重装）。证书失败保留 SSH 隧道本机访问；**不会开放明文 HTTP 或自动修改云厂商安全组**。
- 如果出现残留目录、同端口占用、服务已经存在，应拒绝覆盖；新旧版本、已经改动的管理密码或真实监听需要人工核对。
- 初版尚未在用户真实 VPS 上测试，必须先在可恢复的隔离测试机验证。
