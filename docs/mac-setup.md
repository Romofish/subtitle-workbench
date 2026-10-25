# Mac：SE 主流程交接

更新：2026-10-25。当前计划见 [se-workflow-plan.md](se-workflow-plan.md)。**Studio 已停止开发；本轮未连接 Mac 复核现状。** 本文列出的安装事实来自 2026-10-23 前后的历史记录，下一对话须先检查实际机器，不重复安装已有组件。

## 可复用的历史安装

记录环境为 Apple Silicon M4、16 GB 内存、macOS 15.8。

| 工具 | 历史版本 / 位置 | 新流程用途 |
|---|---|---|
| Subtitle Edit | 5.3.0 arm64，曾安装在 `tools/mac-apps/` | 主编辑器；若已移到 Applications，使用实际位置 |
| IINA | 1.5.0 Universal | 原片、软字幕与成片播放检查 |
| LosslessCut | 3.70.1 arm64 | 按需粗剪 |
| Aegisub | 3.5.1 arm64 | SE 不便完成的特殊排版 |
| HandBrake | 1.11.2 Universal | 明确需要时转码/烧录 |
| FFmpeg / ffprobe | 9.0.2，`/opt/homebrew/bin/` | 下载器与媒体探测 |
| yt-dlp | 2026.08.19，`/opt/homebrew/bin/yt-dlp` | 下载器，执行时核对当前版本 |
| Python / Node | 曾使用 Python 3.13.7、Node 24.5.0 | 下载器使用兼容系统 Python；SE 日常流程不依赖 Node/Studio 虚拟环境 |

历史 `.app` 安装、架构、签名与公证已有记录；GUI 播放、SE 内识别、翻译和烧录未完成整体验收。详见 [旧 Mac 安装记录](retired/studio-2026-10-25/docs/mac-setup.md)，不要把其旧 Studio 安装步骤当作当前任务。

SE 官方 Mac DMG 自带 FFmpeg/libmpv；仍须核对实际已安装版本。Studio 的 `tools/asr/` 引擎和模型不等于 SE 已配置；模型只有在格式、版本和校验相容时才复用。[SE 官方安装说明](https://github.com/SubtitleEdit/subtitleedit/tree/v5.3.0#-system-requirements)

## 接收 Windows 改动

1. 检查 Mac 本地分支、未提交修改与项目数据，再按 [计划第 5 节](se-workflow-plan.md#cross-platform-sync)合并；不按提交时间推断内容新旧，不强制覆盖。
2. 确认所有新增文件也已传来。Mac 下载入口最小运行集合为根目录 `youtube_download.command` 与 `scripts/downloader.py`，保持目录结构。
3. 核对 `.gitattributes`、Bash 文件 LF 以及 `.command` / `.sh` 执行位；ZIP 或拖拽传输可能丢失执行权限。
4. 保留 Mac 自己的 `.venv`、应用、配置和 `.workbench-data/`；不覆盖为 Windows 对应目录。需要迁移媒体/项目/模型时另列清单。
5. 在 SE 内重新核对路径、字体、快捷键及 Apple Silicon 可用后端；不要直接复制 Windows `Settings.json` 或插件二进制。

仓库的 `examples/timing-check.mp4` 是可随源码保留的合成样例；真实视频、字幕成果和验证输出通常被 Git 忽略，需单独传输。同步后不用运行旧 `start.command` 验证 SE，旧入口可能触发 Studio 环境安装。

Windows 已完成两个测试项目的 P0 保全、实际恢复和 SE 打开检查，备份在 `output/se-handoff/20261025-212630-P0/`。这不涵盖 Mac 本机项目，也不会随源码自动传来；Mac 仍须独立盘点、保全和验证，勿覆盖两机同名数据目录。

## 当前下载入口

在仓库根目录：

```sh
./youtube_download.command --check
./youtube_download.command 'https://www.youtube.com/watch?v=7WbgUplUHWE&t=657s'
```

共享下载核心与包装已改为独立运行；Mac 入口不再自动选择项目 `.venv`，默认查找 Homebrew 或系统兼容全局 `python3`（3.10+）。需要指定解释器时设置 `DOWNLOADER_PYTHON` 完整路径，旧的显式 `WORKBENCH_PYTHON` 仍兼容；入口不读取 Studio `.env`。yt-dlp、FFmpeg/ffprobe 须可被其 PATH 找到，Deno 推荐可用，详见 [下载器说明](downloader.md)。

本轮仅在 Windows Git Bash 检查了 Mac 包装语法、参数和返回码，**Mac 本机 P1 尚未验收**。Windows 的独立入口下载验证不继承为 Mac 通过；须在 Mac 实测依赖、引号中的 `&` URL、中泰字符/空格路径、独立输出和返回码。

## 本机待执行

- 按 P0 保全有价值的旧项目，按需导出到 SE；项目 ZIP/数据库备份不包含原媒体。
- 按 P1 验证独立下载入口，再按 P2 配置 SE。
- 用真实短片及完整视频执行 P3–P5，记录 Mac 自己的模型、速度、错误与修正，不沿用 Windows 结论。
- 验证书签、角色和字幕保存重开，检查中泰字形、首中尾同步、IINA 播放及烧录结果。
- 完成后回写计划执行记录；Windows 未在本机复测的项目仍注明待验。
