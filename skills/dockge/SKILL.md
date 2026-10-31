---
name: netdeploy-dockge-apps
description: 'Source-build Dockge Apps with optional reviewed public IP access and editable/random host port.'
---

# Dockge Apps · 审核过的二开应用中心

只使用 app/dockge.py 里固定的脚本与源代码提交，不得从 AI 文本执行未知 Shell 命令。

1. 审核 Debian/Ubuntu、root、CPU、systemd、ss、5001/TCP 与可用空间。全新无 Docker 数据的 VPS 可在一次审批计划中先安装 Docker Engine、Buildx、Compose v2 插件及 Git（至少 4GB 空闲）；已有可用 Docker 则直接继续，未知/冲突状态拒绝覆盖。
   Docker 前置步骤使用 https://get.docker.com 官方一键脚本：先下载到受保护目录、检查 Shell 语法/dry-run/校验值，再运行本地文件，并验收 Compose v2。拒绝覆盖旧 Docker。安装可能影响 Docker iptables / UFW 规则，必须显示审批风险。
2. 拒绝已存在的上游 Dockge、手动安装的 Dockge Apps、旧 NetDeploy Dockge 容器和部分安装目录；不得自动升级或删除用户数据。
3. 从 https://github.com/slobys/dockge-apps.git 获取固定提交 66aec693a974bd980f632f643586deab16932531，校验 git HEAD，确保 docker/Dockerfile.apps 和 package-lock.json 存在；禁止使用原版 louislam/dockge:1.5.0 应用镜像代替二开程序。
4. 将源码保留于 /opt/netdeploy/dockge/source，用 Docker Compose 从源码构建 netdeploy/dockge-apps:66aec693a974。Dockerfile.apps 使用上游基础镜像（非 digest 固定），此风险应透明说明。
5. Compose 目录 /opt/netdeploy/dockge、数据 /opt/netdeploy/dockge/data、栈目录 /opt/stacks，宿主机/容器栈路径一致。保留已有栈，不删除/移动。
6. 容器内部 5001 TCP 不变，宿主机端口可留空随机生成 20000–59999 或填 1024–65535。新安装默认规划公网 0.0.0.0 绑定；安装页面不显示访问模式选择器，必须在部署审批中单独明确确认公网 HTTP 与 Docker Socket 权限风险后才能执行。原有实例不自动改变绑定。实际 HostConfig.PortBindings 与 Web 必须验收。
7. 按验收结果显示 SSH 隧道地址或 http://服务器公网IP:端口/；已有受管理实例可仅修改端口，失败回退。建议先通过 SSH 隧道设置管理员。应用中心有 Nginx Proxy Manager、IT-Tools、MyIP，可编辑应用端口。

Dockge Apps 挂载 Docker Socket，具备高权限，公网 HTTP 明文管理具备高风险，必须用户明确确认并限制云防火墙管理 IP。源代码构建比拉取预建镜像慢，失败可能留下需要人工检查的目录，禁止盲目重试。

来源：https://github.com/slobys/dockge-apps
