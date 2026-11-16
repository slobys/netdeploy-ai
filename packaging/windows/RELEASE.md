安装 `NetDeployAI-0.3.33-Setup-x64.exe` 后，从桌面或开始菜单打开 NetDeploy AI。

- 支持 Windows 10/11 x64，安装包内含 Python、SSH 客户端及 Codex SDK。
- 双击图标直接进入独立客户端窗口。Hiddify 等管理页面在客户端子窗口打开。
- 安装程序会检查 WebView2，缺少时自动联网安装微软运行组件。
- 关闭客户端窗口后后台继续运行，再次点击桌面图标可重新打开。
- 在开始菜单选择「退出 NetDeploy AI」退出后台。执行中的部署需要先完成。
- 首次使用 Codex 时，请在面板中登录自己的 ChatGPT 账号，授权页面使用系统浏览器。
- 用户数据位于 `%LOCALAPPDATA%\NetDeployAI\desktop`。覆盖安装和卸载均保留该目录。
- 安装包尚未配置代码签名，Windows 可能显示未知发布者提示。下载文件的 SHA-256 见 `SHA256SUMS.txt`。

源码方式仍可使用 QuickStart。安装版使用独立数据目录。已有源码版正在运行时，桌面图标会打开正在运行的面板。
