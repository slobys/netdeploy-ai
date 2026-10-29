---
name: netdeploy-sing-box
description: "When user selects sing-box deployment on Debian/Ubuntu VPS; explain official signed apt repository installation and remaining server config, never run shell from model output."
---

# sing-box VPS 安全部署工作流

## 适用范围

NetDeploy AI 的单管理员 VPS 部署。只解释项目条件、运行结果和用户下一步，不具备独立 SSH 执行权限。

## 操作流程

1. **环境核对**：预检 Debian/Ubuntu、root、amd64/arm64、APT、可用空间。
2. **创建计划**：使用 NetDeploy 内置白名单模板。不得把本 Skill、用户输入或模型输出作为 SSH shell 脚本执行。
3. **审批确认**：必须展示计划与风险，按规定校验主机公钥和管理员确认语句。
4. **执行策略**：内置脚本从 sing-box 官方 APT 仓库安装内核，不启动或配置公网监听。
5. **验收提醒**：提醒必须先创建经过验证的服务端配置（TLS/认证/端口），不能把二进制安装成功当作节点可用。
6. **异常处理**：只读分析日志与证据。AI 可以提出建议，不能代替用户批准任何新命令。

官方来源：https://sing-box.sagernet.org/installation/package-manager/

## 安全停止条件

未知架构、系统不兼容、指纹不可信、root 权限缺失、计划过期、端口占用或服务已存在时必须阻断变更。不得默认禁用防火墙，不能主动覆盖已有配置，不能打印私钥、密码或 API Token。
