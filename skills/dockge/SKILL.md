---
name: netdeploy-dockge
description: 'Deploy Dockge 1.5.0 through an audited, localhost-only Docker Compose plan for a trusted Debian or Ubuntu VPS.'
---

# Dockge · 安全 Docker Compose 管理

只使用 app/dockge.py 中固定、可审核的计划；不将 AI 建议或用户输入作为 SSH Shell 脚本执行。

## 工作流程

1. 环境预检：root SSH、Ubuntu/Debian、x86_64/ARM64、Docker Engine、Compose v2、Docker Socket、ss、至少 1.2GB 可用空间与 TCP 5001 空闲；拒绝已有 /opt/dockge、/opt/netdeploy/dockge 和同名容器。
2. 固定上游版本：拉取 louislam/dockge:1.5.0 官方 Docker Hub 镜像并检查架构。固定版本标签不是不可变 digest，升级需再次审查。
3. 写入 Compose：目录 /opt/netdeploy/dockge、数据 /opt/netdeploy/dockge/data、项目栈目录 /opt/stacks（容器内外一致）。不删除/移动已有栈。
4. Web 仅发布 127.0.0.1:5001:5001/tcp，默认关闭 DOCKGE_ENABLE_CONSOLE；用户阅读 Docker Socket 权限风险后独立批准。
5. 验收容器运行、真实 Docker HostConfig.PortBindings、本机 HTTP 响应。检测到意外公网绑定时停止 Dockge，拒绝输出直连地址。
6. Windows PowerShell 执行 SSH -L 隧道，再访问 http://127.0.0.1:5001/，首次初始化 Dockge 管理员账号。

## 风险与边界

Dockge 挂载 /var/run/docker.sock，可对 VPS 容器和文件执行高权限操作；/opt/stacks 中的其他栈也可能被管理员操作。只供可信管理员经 SSH 隧道访问，不开启公网明文 HTTP，不自动关闭 UFW。

检测到已有目录、数据或未知容器时必须停止，不应重装覆盖。初次安装失败可能留下目录和镜像，须先检查远端真实状态；不得盲目重试。

官方来源：https://github.com/louislam/dockge/releases/tag/1.5.0
