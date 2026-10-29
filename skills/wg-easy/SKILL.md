---
name: netdeploy-wg-easy
description: "When user selects wg-easy WireGuard Docker deployment on a Linux VPS; check docker, root privileges, UDP 51820, and insist on secure first-run setup."
---

# wg-easy VPS 安全部署工作流

## 适用范围

NetDeploy AI 的单管理员 VPS 部署。只解释项目条件、运行结果和用户下一步，不具备独立 SSH 执行权限。

## 操作流程

1. **环境核对**：检查 Docker Compose v2、root、端口冲突与 x86_64/arm64。
2. **创建计划**：使用 NetDeploy 内置白名单模板。不得把本 Skill、用户输入或模型输出作为 SSH shell 脚本执行。
3. **审批确认**：必须展示计划与风险，按规定校验主机公钥和管理员确认语句。
4. **执行策略**：内置 Compose 使用官方 v15 标签和固定数据卷，管理 Web 绑定到 VPS 127.0.0.1:51821。
5. **验收提醒**：指导用户通过 SSH 本地转发进入首次设置，需额外确认 UDP 51820 防火墙及 WireGuard 连通性。
6. **异常处理**：只读分析日志与证据。AI 可以提出建议，不能代替用户批准任何新命令。

官方来源：https://wg-easy.github.io/wg-easy/v15.4/examples/tutorials/basic-installation/

## 安全停止条件

未知架构、系统不兼容、指纹不可信、root 权限缺失、计划过期、端口占用或服务已存在时必须阻断变更。不得默认禁用防火墙，不能主动覆盖已有配置，不能打印私钥、密码或 API Token。
