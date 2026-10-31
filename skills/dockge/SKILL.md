---
name: netdeploy-dockge-apps
description: 'Source-build the reviewed slobys/dockge-apps fork with localhost-only Docker management access.'
---

# Dockge Apps · 审核过的二开应用中心

只使用 app/dockge.py 里固定的脚本与源代码提交，不得从 AI 文本执行未知 Shell 命令。

1. 审核 Debian/Ubuntu、root、Docker Engine、Compose v2、Git、ss、Docker Socket、5001/TCP 空闲与至少 3GB 可用空间。
2. 拒绝已存在的上游 Dockge、手动安装的 Dockge Apps、旧 NetDeploy Dockge 容器和部分安装目录；不得自动升级或删除用户数据。
3. 从 https://github.com/slobys/dockge-apps.git 获取固定提交 66aec693a974bd980f632f643586deab16932531，校验 git HEAD，确保 docker/Dockerfile.apps 和 package-lock.json 存在；禁止使用原版 louislam/dockge:1.5.0 应用镜像代替二开程序。
4. 将源码保留于 /opt/netdeploy/dockge/source，用 Docker Compose 从源码构建 netdeploy/dockge-apps:66aec693a974。Dockerfile.apps 使用上游基础镜像（非 digest 固定），此风险应透明说明。
5. Compose 目录 /opt/netdeploy/dockge、数据 /opt/netdeploy/dockge/data、栈目录 /opt/stacks，宿主机/容器栈路径一致。保留已有栈，不删除/移动。
6. 5001 TCP 严格绑定 127.0.0.1:5001，默认关闭内置控制台；验证实际 Docker HostConfig.PortBindings、镜像标记与本机 Web。端口异常时停止容器。
7. 经 SSH 隧道访问 http://127.0.0.1:5001/，首次在 Dockge Apps 中创建管理员。应用中心有 Nginx Proxy Manager、IT-Tools、MyIP，可编辑应用端口。

Dockge Apps 挂载 Docker Socket，具备高权限，不能公开 5001 明文管理界面。源代码构建比拉取预建镜像慢，失败可能留下需要人工检查的目录，禁止盲目重试。

来源：https://github.com/slobys/dockge-apps
