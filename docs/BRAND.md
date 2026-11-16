# NetDeploy AI 品牌素材

标志以翡翠绿底、白色 N 形网络路径与薄荷绿部署节点组成。节点与路径分离，让 16–32px 小图标仍可辨认。保留现有产品配色、字体与功能。

- 绿色：`#0c6551`；白色路径：`#f4fffb`；部署节点：`#73e5b1`。
- 共用素材：`app/static/brand/logo.svg`，供面板、登录页、浏览器标签、GitHub README 与在线文档使用。
- Windows：`app/static/brand/favicon.ico` 含 16、24、32、48、64、128、256px 图层；客户端、安装器和快捷方式使用同一文件。
- PNG：提供 64、128、192、512px 透明圆角图标。
- 生成源：`packaging/windows/brand_assets.py`，只用 Python 标准库。调整几何后运行 `python packaging/windows/brand_assets.py` 重建，避免各处分别画图导致差异。

不改变标志比例，不给标志叠加发光、渐变或额外文字。使用至少 8px 的外侧留白。正文与暗色页面使用原有文字主题，标志自身保持一致。
