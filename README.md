# 字幕工作流：Subtitle Edit 为主

**2026-10-25 决策：停止自建 Studio 开发，使用 Subtitle Edit 完成字幕制作。** 仓库继续保留独立下载器、跨平台交接说明和旧 Studio 资料。后续只有实战出现明确且现成工具无法合理解决的问题，才评估最小补充。

## 从这里接手

**唯一实施计划：[docs/se-workflow-plan.md](docs/se-workflow-plan.md)**。

计划包含 SE 插件调查、P0–P6 实施步骤、已有资料迁移、Windows/Mac 同步、实际验收标准及可复制到新对话的提示词。2026-10-25 已完成 **Windows P0 资料保全与导出、P1 下载入口独立化**。P2 已实测 SE 播放、波形、中泰字形、逐句回放、本地泰语识别运行、ASS 与书签重开、只读参考双栏；Actor 测试标签保存及自动备份实际恢复机制也已通过，真实说话人身份仍未核对。

P3 已完成指定 60 秒片段的基线及一个 VAD 替代设置比较，识别质量尚未通过，语义未验。P4 已验证三条英文参考的复制粘贴翻译预览、采用、撤销重做及保存重开；P5 已在 SE 生成并检查短烧录样片，音频 copy 的头部前滚问题通过 AAC 重编码解决。上下文/局部重译、泰语审阅及整片交付仍未完成；Mac 本轮未连接，其本机 P0–P6 仍待执行。现有英文字幕仅为参考，不代表真实泰语原文。

短样片为 `output/se-validation/mechanism-sample-burned-aac.mkv`，5.521 秒、三条中文测试稿，已检查解码、时间轴和实际画面。它验证操作流程，不是审定成片。证据见 `p4-translation-validation.json`、`p5-ui-validation.json`、`p5-media-verification-aac.json`。

日常目标流程：**下载/选择原片 → 按需定剪 → SE 导入或识别 → 原文校对 → 翻译与复核 → SE 排版/输出 → 播放检查**。

| 文档 | 用途 |
|---|---|
| [实施计划](docs/se-workflow-plan.md) | 从各平台执行记录接续，避免重复已完成步骤 |
| [下载器说明](docs/downloader.md) | 独立入口、媒体优先、字幕来源；Windows 已验证，Mac 实机待验 |
| [Windows 交接](docs/windows-setup.md) | 已安装软件、路径、SE 待验和入口边界 |
| [Mac 交接](docs/mac-setup.md) | 历史安装信息、源码同步与 Mac 实测要求 |
| [文档索引](docs/README.md) | 有效文档与历史资料的状态 |
| [退役资料](docs/retired/README.md) | 旧 Studio 计划、运行说明、API 和验收；仅用于历史查阅/取回项目 |

## 仓库内容的当前用途

- `scripts/downloader.py` 和下载入口：独立使用兼容全局 Python 与外部下载工具；不自动选择 Studio `.venv`。Windows 日常入口为 `youtube_download.ps1` / `.cmd`，Mac 为 `youtube_download.command`。
- `frontend/`、`backend/`、Studio 启动/安装入口：已停止开发，暂留用于历史项目取回。不要以运行 `setup.command` / `setup.cmd` 作为 SE 工作流的前置条件。
- `examples/`：合成的字符、时间与播放样例，不是泰语识别或翻译质量样片。
- 用户媒体、`.workbench-data/`、`.env`、模型、运行环境及 `output/` 不随普通 Git 同步；旧项目包不包含媒体，须另行保全。

Windows 两个测试项目共 16 条字幕（含 1 条人工中文）已生成备份、实际恢复并重新关联媒体；原文和中文导出已在 SE 打开。旧 Studio 服务已正常停机，数据库内容保持不变。本地保全目录为 `output/se-handoff/20261025-212630-P0/`，下载器验证记录为 `output/se-validation/p1-download-validation.json`；这些资料需单独保全和交接。

Windows 日常入口已放到桌面和开始菜单 `Subtitle Workflow` 组：`Subtitle Edit - SE Workflow`、`YouTube Downloader - SE Workflow`。前者直接打开 SE，后者使用独立下载器；旧 Studio 快捷方式仍保留用于历史资料取回。入口验证记录为 `output/se-validation/p6-shortcuts-validation.json`，Mac 入口仍需本机处理。

## 同步到 Mac 前

先阅读计划的 [Windows → Mac 同步要求](docs/se-workflow-plan.md#cross-platform-sync)。检查已修改和未跟踪文件，尤其 `youtube_download.command` 必须与新增 `scripts/downloader.py` 成套同步。同步源码不等于复制 Windows 的 `.venv`、EXE/DLL、SE 设置或数据库，也不意味着重装 Studio。

本轮实施未提交或推送 Git。保留两机已有修改，以实际内容差异核对交接结果；Mac 的 SE 流程仍须在 Mac 本机验收。
