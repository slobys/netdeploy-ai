# Windows 安装包构建

在 Windows x64 上使用 Python 3.13 和 Git 执行 `python packaging/windows/build.py`。构建器从当前 Git 提交导出允许分发的源码，准备两套独立的 Python 运行环境，编译桌面入口并生成 Inno Setup 安装程序。首次构建会下载并校验官方 Python、OpenSSH 和 Inno Setup。

输出位于 `release/`，包括安装 EXE、免安装 ZIP、SHA-256 和构建清单。构建时不会读取本机 `.env`、数据库、SSH 文件或 ChatGPT 授权。安装包中的依赖各自保留其许可证。

执行 `python tests/smoke_windows_installer.py release/NetDeployAI-0.3.36-Setup-x64.exe` 可验证首次安装、独立 Codex SDK、重复打开、覆盖升级及卸载保留数据。测试使用临时中文目录与独立端口 18787、18789。

客户端使用 .NET Framework 4.8、Windows 10 兼容清单和 WinForms 的 PerMonitorV2 配置，避免系统位图拉伸导致 WebView2 内容发虚。构建必须同时分发 `NetDeployAI.exe.config`。安装验证会检查主窗口与子窗口的 DPI 感知、WebView2 像素比例和实际内容尺寸；应在标准 DPI 与高 DPI 环境分别运行。

安装版的数据根目录为 `%LOCALAPPDATA%\NetDeployAI\desktop`。SSH 密码使用 Windows 凭据保管库。使用 SSH 私钥的用户可将专用私钥放在该目录的 `ssh_key` 文件。

启动器支持 `--stop` 退出后台。升级与卸载会先请求正常退出，执行中的部署任务会阻止退出。源码版 QuickStart 保持独立。

GitHub Actions 的 Windows installer 工作流支持手动构建和版本标签构建。标签构建完成真实安装验证后，会发布 Release 附件。此版本尚未配置 Authenticode 代码签名。

主窗口和管理子窗口首次打开默认最大化，分别把位置与状态保存为用户数据目录中的 `window-main.json` 和 `window-panel.json`。这些文件与授权配置分开存储；缺失或损坏时回到最大化，移除显示器后由 Windows 恢复到可见区域。安装验证覆盖状态恢复、最小化唤回、文档外部浏览器路由及原有管理子窗口行为。
