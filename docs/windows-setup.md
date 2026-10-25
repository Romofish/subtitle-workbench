# Windows：SE 主流程交接

更新：2026-10-25。当前计划见 [se-workflow-plan.md](se-workflow-plan.md)。**Windows P0/P1、P2 操作恢复、P4 复制粘贴翻译机制、P5 短样片与 P6 日常入口已验证；泰语语义、上下文/局部重译与最终整片未验收。** Studio 已停止开发且本机旧服务已正常停机，后续继续复用已有软件。

## 本机软件快照

新增便携组件位于 `%LOCALAPPDATA%\Programs\SubtitleWorkbench\`；本次机器的目录为 `C:\Users\flora\AppData\Local\Programs\SubtitleWorkbench`。项目目录仍在 `E:\SideJob\subtitle-workbench`。

| 组件 | 已核对版本 | 当前处理 |
|---|---|---|
| Subtitle Edit | 5.3.0 | 主编辑器；`SubtitleEdit\SubtitleEdit.exe` |
| SE 的播放器/媒体组件 | `libmpv-2.dll` 存在，SE 自用 FFmpeg 9.0.2 可运行 | SE 内播放、波形、逐句回放及三条中文短样片烧录已实测；整片待验 |
| FFmpeg / ffprobe | 9.0.2 | 工具目录 `ffmpeg\ffmpeg-9.0.2-essentials_build\bin\`，供下载器使用 |
| yt-dlp / Deno | 2026.10.21 / 2.9.8 | 工具目录 `yt-dlp\` / `deno\` |
| Python | 新装 3.13.17；原 3.11 保留 | `%LOCALAPPDATA%\Programs\Python\Python313\python.exe`；无需为了 SE 建 Studio 虚拟环境 |
| VLC | 3.0.24 | 原片、软字幕及成片播放检查 |
| LosslessCut / Aegisub | 3.70.1 / 3.5.1 | 按需剪辑 / 特殊排版 |
| HandBrake | 已有 1.11.2 | 复用 `C:\Program Files (x86)\HandBrake\HandBrake.exe` |
| Node / Git | 已有 22.17.0 / 2.53.0.windows.2 | 复用；SE 日常制作不依赖 Node |
| 可复用 Whisper 组件 | 1.9.5 对应 b5454 CUDA 包、large-v3-turbo-q5_0 | 已复制到 SE 的 cuBLAS/模型目录并逐文件核对哈希；SE 内泰语短片运行完成，语义未验 |

本机 RTX 4070 已在旧 Studio 的实际引擎日志中使用 CUDA。本轮在 SE GUI 使用 `Whisper CPP → cuBLAS → large-v3-turbo-q5_0 → Thai` 完成指定 60 秒片段的基线和一次 VAD 替代设置运行。引擎运行完成不代表语言质量通过，具体问题见下文 P3。复用证据为 `output/se-validation/engine-audit.json`。安装细节、清单和旧启动方法保存在 [退役安装记录](retired/studio-2026-10-25/docs/windows-setup.md)。

## P0 资料保全结果

本机两测试项目共 16 条字幕，含 1 条人工中文，已完成可恢复项目 ZIP、SQLite 一致性备份、媒体与源码保全；备份实际恢复、媒体重新关联及文本/时间检查通过。原文和中文导出均已在 SE 打开。保全目录为 `output/se-handoff/20261025-212630-P0/`，不随普通 Git 同步。

确认备份与恢复后，旧 Studio 通过 `CTRL_BREAK` 正常停机，数据库内容保持不变。原数据库、媒体、人工稿与源码均保留；后续仅在取回旧资料时使用旧运行入口。Mac 的旧项目仍须在 Mac 本机单独盘点。

## 后续操作边界

- 按已记录的实测结果接续，核对真实说话人和原文，再完成 P4 内容审阅与 P5 整片交付。Actor、自动备份恢复、复制粘贴翻译和短样片机制已验证。
- 自动分人、泰语语义、上下文/局部重译和整片尚未验收。现有英文字幕仅作参考，不能据此宣称恢复了真实泰语原文。
- Windows P0/P1 已完成。不要把 `setup.cmd`、`start.cmd`、`setup_asr.cmd` 当成新流程前置步骤。
- 日常使用桌面或开始菜单 `Subtitle Workflow` 组的新 SE/下载器入口；原 `Subtitle Workbench` 组完整保留，仅在需要取回历史资料时使用旧 Studio 入口。
- 全量旧安装器存在复用判断待检查项：正常更新过的 Aegisub 文件可能被当作不完整安装。优先直接使用已有程序，勿盲目执行 `--only all` 重装。

## P2 实测与 P3 识别记录

SE 内已实际验证视频播放、波形、中泰字形，以及 `F5` 播放选中句后自动停止。`clip-review.ass` 审阅副本和中文书签保存后，先新建空稿再重开，内容与书签均恢复；英文参考以只读双栏和 `Show all original lines` 打开。实际 UI 证据为 `output/se-validation/se-ui-validation.json`。

P2 的 Actor 持久化及自动备份恢复已在 `p2-persistence-test.ass` 测试副本实际演练：首条经右键 Actors 添加 `QA_TEST_ONLY` 并保存，随后临时将备份间隔设为 1 分钟，写入未保存的中泰恢复标记。实际生成时间戳备份后，先撤销标记，再通过 `File → Restore auto-backup` 恢复，另存为 `p2-restored-from-autobackup.ass`。恢复文件与备份副本逐字节一致，均为 13 条；其余 12 条及全部时间未变，原始稿/审阅稿和书签哈希保持不变。证据为 `output/se-validation/p2-persistence-validation.json`。

演练后配置已恢复：自动备份开启、5 分钟、保留 90 天，`AutoSave=false`。`QA_TEST_ONLY` 和恢复标记仅为机制测试，不代表真实身份或译文。恢复时书签未出现，符合自动字幕备份不包含 `.SE.bookmarks` 的实际行为；字幕与书签旁文件仍须另行成套保全。

指定的 10:57 起 60 秒片段，基线产生 8 条字幕，首条“นี่”重复 109 次。只额外试了一个 VAD 设置，得到 13 条字幕，未见同样的长串重复，但仍有 3 条过长字幕，58.340–60.000 秒区间没有字幕，需要回听判断是否漏句。两版语义均未验，VAD 结果不能记为识别质量通过。原始结果和比较证据保留在 `output/se-validation/asr-comparison.json`，不通过自动删句掩盖问题。

## 最小日常操作

1. 打开原片和原语字幕；另存审阅稿，需角色/样式时使用 ASS。原片、原始识别结果、人工稿分别保留。
2. 选句按 `F5` 回放；存疑处按 `Ctrl+Shift+B` 添加中文书签，例如“待核对：语义/重复/说话人未确认”。未经核实的说话人保持未确认。
3. 按 `Ctrl+Shift+O` 或 `File → Open original subtitle` 开启双栏；条数不等时选 `Show all original lines`，参考保持只读。英文文件只作参考，不冒充泰语原文。
4. 分别保存原文与译文；保存、交接 ASS/SRT 时同时保留完整文件名加 `.SE.bookmarks` 的旁文件，例如 `clip-review.ass.SE.bookmarks`。当前审阅稿为 `output/se-validation/clip-review.ass`，关闭重开后核对书签和文本；不要依赖普通字幕文件单独携带备注。

## P4 复制粘贴翻译与 P5 短样片

本机已用三条英文平台参考走通 `Translate → Auto-translate via copy/paste`：候选译文以独占一行的 `(...)` 分隔，导入后逐条核对预览，再点 OK 采用。Ctrl+Z 可恢复原英文，Ctrl+Y 可重做；中文另存为 `mechanism-en-reference-zh.srt` 后实际重开，时间、Yu/Bam、否定和换行均保留，英文来源哈希未变。证据为 `output/se-validation/p4-translation-validation.json`。此入口按分段顺序匹配，不能忽略条数和对应关系；局部实验先另建副本。本轮没有验证上下文引擎、术语约束或局部重译，也没有使用收费 API。

短烧录操作为选中三条字幕后右键 `Selected lines → Generate video with burned-in subtitles`，检查 Cut 为 34.800–40.300 秒。此次原片已有底部泰文，因此中文设为顶部居中、垂直边距 60；Arial Bold、Font size factor 0.52、白字黑边，1920×1080、libx264/medium/CRF 23。Font size factor 为非线性比例，1.00 会产生极大字号，调整时必须观察预览。

本素材的 `Audio encoding=copy` 会保留选区前的音频，产生 6.720 秒文件，视频流从 1.179 秒开始。改用 AAC、48000 Hz、stereo、128k 后，另存 `mechanism-sample-burned-aac.mkv`：5.521 秒、165 视频帧、音视频均从 0 秒开始，完整解码通过，音频包络匹配源片 34.800 秒。失败版本保留用于对照；精确截段烧录采用 AAC 后仍应检查输出时间轴。

SE 的 Play 按钮调起本机默认 PotPlayer；在关闭外挂字幕显示时回放，中文仍可见，之后已恢复该设置。三处输出截图的中文字形、位置及换行通过；此次没有单独验证 VLC。`p5-ui-validation.json`、`p5-media-verification-aac.json` 与 `burned-frames-aac/` 保存证据。这只是三条英文参考译稿的短样片，没有完成泰语听音、口型同步、整片原语/中文/双语交付；画面已有泰文也不能证明新烧录泰文的字形通过。

## Windows 日常快捷入口

当前用户桌面（本机为 `C:\Users\flora\OneDrive\Desktop`）和开始菜单 `Subtitle Workflow` 组均已建立：

- `Subtitle Edit - SE Workflow`：直达已安装的 `SubtitleEdit.exe`。
- `YouTube Downloader - SE Workflow`：直达仓库 `youtube_download.cmd`，经独立 PowerShell 入口选择全局 Python，不依赖 Studio dispatcher 或自动选择 `.venv`。

重建入口可在仓库执行 `powershell -NoProfile -File scripts/create_windows_shortcuts.ps1 -Desktop`；省略 `-Desktop` 只处理开始菜单。同名相同目标直接复用，目标冲突则新建编号，不覆盖旧快捷方式。本轮 4 个新入口已回读核对目标、参数和工作目录，下载器目标 `--check` 返回 0；重复执行无改动，46 个既有桌面/旧组快捷方式哈希未变，未启动 Studio。证据为 `output/se-validation/p6-shortcuts-validation.json`。

## 当前下载入口

以下独立入口不需要 Studio 环境；PowerShell 中完整 URL 必须保留引号：

```powershell
.\youtube_download.cmd --check
.\youtube_download.ps1 'https://www.youtube.com/watch?v=7WbgUplUHWE&t=657s'
```

`.cmd` 直接调用 `youtube_download.ps1`；旧 `workbench.ps1 download` / `workbench.cmd download` 仍可使用，下载分支提前转入独立入口。自动查找兼容全局 Python，不再自动选择 `.venv` 或读取 Studio `.env`；下载核心自行查找已有工具。指定解释器使用 `DOWNLOADER_PYTHON`，指定工具目录使用 `WORKBENCH_TOOLS_DIR`。详见 [下载器说明](downloader.md)。

Windows P1 已通过 17 项下载器单测、5 项入口契约测试及 7 个真实工具离线场景；四个 Windows 入口还在无 Studio 文件的最小目录完成本地 HTTP 下载，验证含 `&` URL、中泰空格路径、独立输出和返回码 0/1/2。证据为 `output/se-validation/p1-download-validation.json`。这些工程检查不代表外网限流、字幕语言或 SE 成片质量通过。

缺下载工具时只处理缺失项，Python 已有则复用；旧 `setup.cmd` 提示已移除。日常下载支持 Python 3.10+，可选安装器 `scripts/install_windows_tools.py --only core` 需要全局 Python 3.11+，不会在下载时自动执行。

## 已有测试素材与未验项

- 完整视频、英文参考字幕与来源清单位于 `output/windows-validation/downloads/`；不重复下载作为 SE 验收前提。
- `output/windows-validation/YouTube-7WbgUplUHWE-10m57s-60s.mp4` 为 10:57 起 60 秒片段。
- 旧 Studio 短片转写有明显重复；整片首次导入失败，最后修复未完成真实整片 API 重跑。仅用于比较问题，不作为完成的字幕。
- 已有 `clip-burned-draft.mp4` 是命令行渲染/字形测试，含测试文字，不是 SE 烧录或翻译质量验收结果。
- 本地 `output/` 和 `test-results/` 被 Git 忽略，Mac 源码同步不会取得它们。单独迁移素材时保存来源与时间轴。

先完成 SE 的真实素材闭环，再将实际结果写入计划。无需为退役 Studio 追补浏览器多人预览或全套应用回归。
