---
name: netdeploy-3x-ui
description: "When user selects 3X-UI VPS installation; provide safety requirements and reviewed options; do not run upstream interactive script during Alpha."
---

# 3x-ui VPS 安全部署工作流

## 适用范围

NetDeploy AI 的单管理员 VPS 部署。只解释项目条件、运行结果和用户下一步，不具备独立 SSH 执行权限。

## 操作流程

1. **环境核对**：检查发行版、CPU 架构、root、安装目录与已有管理面板。
2. **创建计划**：使用 NetDeploy 内置白名单模板。不得把本 Skill、用户输入或模型输出作为 SSH shell 脚本执行。
3. **审批确认**：必须展示计划与风险，按规定校验主机公钥和管理员确认语句。
4. **执行策略**：Alpha 只生成引导方案，不执行远程下载即运行脚本。
5. **验收提醒**：正式安装器必须固定版本和校验；管理面板需 TLS、强认证、私有路径及合理访问限制。
6. **异常处理**：只读分析日志与证据。AI 可以提出建议，不能代替用户批准任何新命令。

官方来源：https://docs.sanaei.dev/docs/guide/installation/

## 安全停止条件

未知架构、系统不兼容、指纹不可信、root 权限缺失、计划过期、端口占用或服务已存在时必须阻断变更。不得默认禁用防火墙，不能主动覆盖已有配置，不能打印私钥、密码或 API Token。
