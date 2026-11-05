---
name: "NetDeploy AI"
description: "面向 VPS 管理与部署审批的运维工作台视觉系统"
colors:
  accent: "#91bdff"
  accent-light: "#2557bd"
  action: "#346aca"
  action-deep: "#2855b1"
  on-action: "#fff"
  page: "#101720"
  page-light: "#eef3f8"
  rail: "#141e2b"
  rail-light: "#e6eef7"
  panel: "#18222e"
  panel-light: "#ffffff"
  panel-secondary: "#212e3d"
  panel-secondary-light: "#f1f5fb"
  panel-hover: "#29394b"
  panel-hover-light: "#e6eef9"
  input: "#131c27"
  input-light: "#ffffff"
  line: "#344254"
  line-light: "#d9e3f0"
  line-strong: "#566b82"
  line-strong-light: "#b9cce3"
  control-line: "#70859b"
  control-line-light: "#71869d"
  text: "#eef3f9"
  text-light: "#1a2a42"
  text-secondary: "#bac8d8"
  text-secondary-light: "#455b77"
  text-muted: "#a5b6ca"
  text-muted-light: "#506b88"
  code: "#111923"
  code-light: "#ecf2fa"
  success: "#91e3bb"
  success-light: "#0b7352"
  success-bg: "#15362e"
  success-bg-light: "#e5f8ee"
  success-line: "#347760"
  success-line-light: "#9bd5b9"
  warning: "#f3d39a"
  warning-light: "#88561e"
  warning-bg: "#302c27"
  warning-bg-light: "#fff7e8"
  warning-line: "#796049"
  warning-line-light: "#e8ca9a"
  danger: "#ffb5c8"
  danger-light: "#a12d56"
  danger-bg: "#382432"
  danger-bg-light: "#fff0f3"
  danger-line: "#86536a"
  danger-line-light: "#eab5c4"
typography:
  display:
    fontFamily: "\"Segoe UI\", \"PingFang SC\", \"Microsoft YaHei\", system-ui, sans-serif"
    fontSize: "30px"
    fontWeight: 700
    lineHeight: 1.22
    letterSpacing: "-.02em"
  headline:
    fontFamily: "\"Segoe UI\", \"PingFang SC\", \"Microsoft YaHei\", system-ui, sans-serif"
    fontSize: "19px"
    fontWeight: 750
    lineHeight: 1.45
  title:
    fontFamily: "\"Segoe UI\", \"PingFang SC\", \"Microsoft YaHei\", system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 700
    lineHeight: 1.35
  body:
    fontFamily: "\"Segoe UI\", \"PingFang SC\", \"Microsoft YaHei\", system-ui, sans-serif"
    fontSize: "14.5px"
    lineHeight: 1.55
    letterSpacing: ".005em"
  body-compact:
    fontFamily: "\"Segoe UI\", \"PingFang SC\", \"Microsoft YaHei\", system-ui, sans-serif"
    fontSize: "13.5px"
    lineHeight: 1.55
  label:
    fontFamily: "\"Segoe UI\", \"PingFang SC\", \"Microsoft YaHei\", system-ui, sans-serif"
    fontSize: "12px"
    lineHeight: 1.35
  button:
    fontFamily: "\"Segoe UI\", \"PingFang SC\", \"Microsoft YaHei\", system-ui, sans-serif"
    fontSize: "13.5px"
    fontWeight: 700
    lineHeight: 1.4
  button-compact:
    fontFamily: "\"Segoe UI\", \"PingFang SC\", \"Microsoft YaHei\", system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 700
    lineHeight: 1.4
  input:
    fontFamily: "\"Segoe UI\", \"PingFang SC\", \"Microsoft YaHei\", system-ui, sans-serif"
    fontSize: "14.5px"
    lineHeight: 1.5
  mono:
    fontFamily: "ui-monospace, \"Cascadia Mono\", Consolas, monospace"
    fontSize: "13px"
    fontWeight: 630
    lineHeight: 1.6
rounded:
  chip: "6px"
  control: "8px"
  panel: "12px"
  pill: "100px"
spacing:
  nav-gap: "4px"
  control-gap: "8px"
  grid-gap: "12px"
  content-top: "24px"
  section-gap: "28px"
  content-inline: "clamp(18px, 2.5vw, 36px)"
  rail-width: "216px"
components:
  button-primary:
    backgroundColor: "{colors.action-deep}"
    textColor: "{colors.on-action}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
    height: "42px"
  button-secondary:
    backgroundColor: "{colors.panel-secondary}"
    textColor: "{colors.text}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
    height: "42px"
  button-ghost:
    backgroundColor: "{colors.panel-secondary}"
    textColor: "{colors.accent}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
    height: "42px"
  button-danger:
    backgroundColor: "{colors.danger-bg}"
    textColor: "{colors.danger}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
    height: "42px"
  button-project:
    backgroundColor: "color-mix(in srgb, #346aca 8%, #18222e)"
    textColor: "{colors.accent}"
    typography: "{typography.button-compact}"
    rounded: "{rounded.control}"
    padding: "6px 10px"
    height: "42px"
  text-field:
    backgroundColor: "{colors.input}"
    textColor: "{colors.text}"
    typography: "{typography.input}"
    rounded: "{rounded.control}"
    padding: "11px 13px"
    height: "46px"
  nav-active:
    backgroundColor: "color-mix(in srgb, #346aca 8%, #18222e)"
    textColor: "{colors.accent}"
    rounded: "{rounded.control}"
    padding: "9px 12px"
    height: "45px"
  chip-neutral:
    backgroundColor: "{colors.panel-hover}"
    textColor: "{colors.text-secondary}"
    typography: "{typography.label}"
    rounded: "{rounded.chip}"
    padding: "6px 9px"
  chip-success:
    backgroundColor: "{colors.success-bg}"
    textColor: "{colors.success}"
    typography: "{typography.label}"
    rounded: "{rounded.chip}"
    padding: "6px 9px"
  chip-warning:
    backgroundColor: "{colors.warning-bg}"
    textColor: "{colors.warning}"
    typography: "{typography.label}"
    rounded: "{rounded.chip}"
    padding: "6px 9px"
  chip-error:
    backgroundColor: "{colors.danger-bg}"
    textColor: "{colors.danger}"
    typography: "{typography.label}"
    rounded: "{rounded.chip}"
    padding: "6px 9px"
  project-card:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.panel}"
    padding: "14px 15px 10px"
  plan-overview:
    textColor: "{colors.text}"
    rounded: "{rounded.panel}"
    padding: "18px"
---

# Design System: NetDeploy AI

## Overview

**Creative North Star: "雾蓝部署工作台"**

石墨蓝与雾蓝灰为日常运维提供沉稳的底色。用清晰的标题、稳定的操作位置和可扫读的状态组织信息，帮助管理员在执行前确认目标和风险。

**Key Characteristics:**

- 用面板明度和细分隔线区分区域。
- 动作、当前选项和键盘焦点共用可切换的主题色。
- 中文正文采用系统字体，SSH 地址采用等宽字体并允许长地址换行。

## Colors

经典蓝是默认配色。前置变量记录舒适字号、经典蓝和最终生效的主题值。界面支持暗黑、明亮与跟随系统三种模式，并可切换经典蓝、极光紫、海洋青、翡翠绿、玫瑰粉和暖日橙。实现中复用 `theme.css` 的 `--theme-*` 语义变量。

### Primary

`accent` 用于链接、焦点轮廓和选中导航。`action` 用于交互染色和控件边线。`action-deep` 搭配 `on-action` 用于实心主按钮。

### Neutral

`page` 承载工作区，`rail` 区分导航，`panel` 承载项目、服务器、任务与表单。`panel-secondary` 和 `panel-hover` 区分嵌套控件与悬停层。`line` 划分区域，`control-line` 用于输入边界。完成、风险和失败各自采用文字、底色与边线变量。

### Named Rules

**The Action Color Rule.** 主题色标记动作、当前选项和键盘焦点。状态色随状态语义使用，并配合文字。

## Typography

页面和控件采用 Segoe UI，中文依次回退至苹方和微软雅黑。页标题（30px，窄屏 25px）、分区标题（19px）、项目名称（16px）和正文（14.5px）形成层级。紧凑说明使用 13.5px，状态标签使用 12px。默认「舒适」为 1×，「标准」为 .92×，「大字」为 1.15×，字号由 `typography.css` 统一缩放。

SSH 地址采用等宽字体并允许长地址换行。汇总数字与导航计数使用等宽数字。页标题下方及分区说明最长为 68ch。

## Layout

桌面采用 216px 固定左侧导航和居中的内容区，内容宽度最多 1440px。项目列表使用 12px 间距，桌面三列，1150px 及以下两列，650px 及以下一列。850px 及以下导航移至页首。651–850px 且高度不超过 500px 时，品牌、导航和退出入口同排。

分区之间通常留 28px。宽屏任务行依次排列图标、任务、状态和操作，窄屏让状态和操作换行。弹窗内容区域独立滚动，标题与关闭按钮固定在弹窗顶部。

## Elevation & Depth

工作台的项目卡、服务器卡、汇总条和工具栏使用平面、底色与细边线建立层级。项目卡在悬停或内部控件聚焦时加深边线。弹窗使用主题阴影和带 5px 模糊的遮罩。按钮、导航和弹窗的交互过渡较短，并支持系统的减少动态效果设置。

## Shapes

卡片和弹窗采用 12px 圆角，通用按钮和输入框采用 8px。类别使用描边胶囊，任务状态使用 6px 圆角标签。导航和项目图标使用 19–20px 的同色描边 SVG。

## Components

- **按钮**以实心样式突出最终确认，次按钮使用浅层底色和描边。删除使用危险色。项目入口使用轻微主题染色，保留「部署项目」「查看方案」等明确动作名称。
- **项目卡**依次呈现图标、名称、类别和简短说明。分隔线下并排放置带文字的安装状态与操作，操作沿同组卡片底部对齐。
- **输入框**在字段上方呈现标签，标准输入高度至少 46px。键盘聚焦用 2px 主题色轮廓，输入偏移 1px，按钮偏移 3px。
- **导航与状态标签**以边线、淡色底和加粗文字区分当前导航项。状态标签同时显示语义颜色和文字。
- **部署审批**先呈现目标、访问方式和风险提示，再按需展开技术详情与执行命令。确认执行使用实心主按钮。

## Do's and Don'ts

- **Do** 用主题语义变量实现文字、表面、边线和焦点，并检查明暗两种模式。
- **Do** 为状态保留可读的文字。触屏下项目操作和导航至少保留 44px 的点击高度。
- **Do** 让同一组项目卡的底部操作对齐，并为长名称、IPv6 地址和大字设置留出换行空间。
- **Don't** 避免给工作台卡片添加浮起、倾斜或跟随指针的光效。
- **Don't** 避免用主题色标注成功、待审批或失败。
- **Don't** 避免用实心主按钮样式呈现查看详情或取消。
