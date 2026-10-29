# NetDeploy AI · 中文在线使用文档

计划站点：https://slobys.github.io/netdeploy-ai/ （GitHub Pages）

包含文档首页、安装与更新、第一次部署、VPS/SSH、端口防火墙、各项目部署、Google Cloud、故障排查、安全与限制。

## 本地预览（无需 npm）

在 NetDeploy 仓库根目录执行：

    python3 docs/site/build.py
    python3 -m http.server 4173 --directory .build/docs-site

浏览器打开 http://127.0.0.1:4173 。请通过 HTTP 预览，不要以本地 file:// 方式打开（搜索索引会受浏览器安全限制）。

该站点不依赖第三方前端框架或外部字体/脚本。目录、页面与版本在 site.json；章节正文在 content/*.html；site.css 和 site.js 提供响应式布局、搜索、主题、复制代码。命令必须审核后才加入公开文档。

## 验证

    python3 -m unittest discover -s tests/docs -p "test_*.py"
    python3 docs/site/build.py
    bash -n scripts/gcp-root-setup.sh

构建器检查页面 ID、站内链接、锚点、搜索索引、输出文件白名单，仅生成 .build/docs-site 的静态资源，不复制仓库根目录的 .env、data、secrets 或任何 VPS 凭据。

## 自动发布

推送至 main 后，.github/workflows/docs.yml 将自动校验并尝试部署到 GitHub Pages。PR 只运行校验，不对外发布。

首次启用需要一次手工操作：打开 GitHub 仓库 Settings → Pages → Build and deployment → Source，选择 GitHub Actions。然后在 Actions 页手动运行 NetDeploy AI online handbook 工作流，或推送一次文档更新自动触发。若 Pages 尚未启用，文档代码及构建测试仍可通过，但线上网址暂时可能不可用；在工作流部署 Job 中检查状态。

不要在文档中提交 SSH 私钥、root 明文密码、管理员初始密码、真实 VPS 配置或凭据截图。Google Cloud 交互脚本不内置固定密码；高风险 SSH 密码登录须显式确认，绝不是默认启用。

## 内容维护规则

- 新增页面：向 site.json 添加条目，并创建 content/<page-id>.html，章节标题必须有唯一 id。
- 站内链接使用 name.html#section，禁止绝对 /name.html 根路径（GitHub Pages 带仓库子路径）。
- 更新主软件版本时，同步 site.json 的版本号与首页描述。
- 只上传白名单中的公开文档文件，不把仓库其他文件复制进 Pages 产物。
