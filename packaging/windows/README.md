# Windows 安装包构建

在 Windows x64 上使用 Python 3.13 和 Git 执行 `python packaging/windows/build.py`。构建器从当前 Git 提交导出允许分发的源码，准备两套独立的 Python 运行环境，编译桌面入口并生成 Inno Setup 安装程序。首次构建会下载并校验官方 Python、OpenSSH 和 Inno Setup。

输出位于 `release/`，包括安装 EXE、免安装 ZIP、SHA-256 和构建清单。构建时不会读取本机 `.env`、数据库、SSH 文件或 ChatGPT 授权。安装包中的依赖各自保留其许可证。

执行 `python tests/smoke_windows_installer.py release/NetDeployAI-0.3.38-Setup-x64.exe` 可验证首次安装、独立 Codex SDK、重复打开、覆盖升级及卸载保留数据。测试使用临时中文目录与独立端口 18787、18789。

客户端使用 .NET Framework 4.8、Windows 10 兼容清单和 WinForms 的 PerMonitorV2 配置，避免系统位图拉伸导致 WebView2 内容发虚。构建必须同时分发 `NetDeployAI.exe.config`。安装验证会检查主窗口的 DPI 感知、WebView2 像素比例和实际内容尺寸；应在标准 DPI 与高 DPI 环境分别运行。

安装版的数据根目录为 `%LOCALAPPDATA%\NetDeployAI\desktop`。SSH 密码使用 Windows 凭据保管库。使用 SSH 私钥的用户可将专用私钥放在该目录的 `ssh_key` 文件。

启动器支持 `--stop` 退出后台。升级与卸载会先请求正常退出，执行中的部署任务会阻止退出。源码版 QuickStart 保持独立。

GitHub Actions 的 Windows installer 工作流支持手动构建和版本标签构建。标签构建完成真实安装验证后，会发布 Release 附件。此版本尚未配置 Authenticode 代码签名。

窗口状态保存为用户数据目录中的 `window-main.json`，与授权配置分开存储；缺失或损坏时回到最大化，移除显示器后由 Windows 恢复到可见区域。Hiddify、S-UI 和其他面板都在默认浏览器打开，原页面保持不变。客户端截获 Hiddify 同源启动链接，用当前会话令牌请求固定的本机 API（禁止重定向），仅把校验后的 HTTPS 管理地址交给浏览器，失败在原页面提示。网页版本保留同源启动页的新标签流程。安装验证使用模拟管理链接接口，覆盖成功、无效链接、HTTP 错误、重复点击、IPv6 S-UI 和窗口状态恢复，不连接实际 VPS。
