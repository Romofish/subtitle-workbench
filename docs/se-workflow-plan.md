# Subtitle Edit 主流程实施计划

更新：2026-10-25（Asia/Hong_Kong） · 状态：**Windows P0/P1、P2 操作恢复、P4 复制粘贴翻译机制、P5 短样片及 P6 入口已验证；已利用原英文 CC 完成 60 秒文本双向核对，原声听校与整片交付未通过。本轮按用户要求仅处理 Windows，Mac 待验项不构成本轮阻碍**。

本文是后续工作的唯一有效计划。用户要求以现成工具完成字幕制作，不为保留已有代码继续自建；停止 Studio 开发，直到实战出现值得解决的具体问题。旧计划及旧验收清单已[退役](retired/README.md)，不再构成待办。

## 1. 已确定的取舍

- Subtitle Edit（SE）作为 Windows 和 Apple Silicon Mac 的主要字幕编辑器。
- 停止 Studio 新功能、界面、API、任务系统和模型管理开发；不继续为退役应用补齐整套验收。
- 保留已有代码和数据作为历史快照，必要时仅用于读取、备份和导出。停止开发不等于立即删除数据库、媒体、模型或卸载共用软件。
- 保留独立下载器及来源记录；其入口与 Studio 运行环境完全解耦属于本计划的小范围实施工作。
- 优先级：SE 内置设置与功能 → 现成插件/外部工具 → 最小脚本或插件。没有明确实战缺口时不开发扩展。
- 用户已授权缺失软件的下载安装，已有软件复用；Windows 新组件放 C 盘常用软件目录。软件安装授权不代表选择了付费 AI 服务、模型或费用额度。

当前未发现必须继续开发 Studio 才能满足的核心字幕生产需求。以下差异不作为继续自建的理由：

| Studio 当前能力 | SE / 文件工作流的处理方式 | 保留边界 |
|---|---|---|
| 原文/中文编辑、听音、时间调整、局部翻译、AI 建议采用 | SE 内置功能承担；高级翻译支持上下文、简介和术语 | 本机体验与语言效果待实测，不仅看菜单是否存在 |
| 人工说话人、交叠和存疑标注 | SE Actor、书签与备注；选择能保存角色/样式的 ASS | 三态审阅及原布尔字段未证明能原样迁移，先验证实际标记习惯 |
| 持久候选、版本/上下文/术语指纹和事务历史 | SE 建议预览、明确采用、撤销、备份及分版本文件 | 未发现同等级原生指纹机制的证据；用户尚无必须保留它的实战需求 |
| 下载分类、来源和媒体哈希 | 独立下载器、来源旁文件和项目目录 | 不要求运行 Studio；不新建另一套项目管理平台 |
| 私有 JSON/SQLite 项目与恢复 | 原项目包/一致性数据库备份归档，字幕导出到 SE | 私有历史不要求完整迁入 SE |
| 多人交叠语音识别 | SE 可选引擎与人工复核 | 当前 Studio 也未实现可靠逐人分离，不能把此问题当成其优势 |

## 2. 目标工作流与范围

**下载或选择原片 → 按需定剪 → SE 导入字幕或识别 → 原文听音校对 → 中文翻译与复核 → SE 排版/导出/烧录 → 播放检查。**

已有可信原语字幕优先使用；有独立英文 CC 时，保留原轨及来源，按时间对齐泰语识别稿，双向检查缺漏、矛盾、人名、数字、否定与称谓，并检查中文是否保留译意。英文可作为中文参考底稿；有争议处回到原声，不由英文反推泰语逐字稿，也不把由英文译出的中文作为证明英文正确的独立证据。节目画面文字与对白分别判断。需要剪辑时先确定成片时间轴，随后检查字幕同步。原片、原始字幕和人工稿分开保存。

| 环节 | 默认工具 | 按需补充 |
|---|---|---|
| 下载视频及可用字幕 | 独立 yt-dlp / FFmpeg 下载器 | 保存来源清单，媒体与字幕失败分别报告 |
| 剪辑 | 无需剪辑时跳过 | LosslessCut；精确剪辑另按实际需要选工具 |
| 识别、翻译、校时、角色、普通样式 | SE | 先一个本地识别引擎、一个常用翻译入口 |
| 字幕与视频输出 | SE | Aegisub 仅用于 SE 不便完成的排版；HandBrake 仅用于明确转码需求 |
| 播放验收 | Windows：VLC；Mac：已有 IINA | 核对软字幕与烧录版本 |

不在本轮范围：继续开发 Studio、制作完整迁移/双向同步系统、批量安装所有插件、预先评测所有模型、删除用户历史项目、未经选择开启收费 AI。

## 3. SE 能力与插件基线

功能核查基于 **SE 5.3.0** 固定版本官方文档。实施时先核对两机实际版本，若不同记录变化，不把动态在线目录当作固定安装包内容。

- 内置：双栏翻译、波形/校时、多个识别入口、局部翻译、AI Review、AI Assistant、ASS 样式、双语合并、烧录、备份。内置入口可能需要额外引擎/模型，但这些不是 SE 插件。
- 插件入口默认隐藏：`Options → Settings → Appearance → Show Plugins menu`；随后 `Plugins → Manage plugins → Get plugins online`。
- SE 5 插件为独立程序，使用 JSON 交换字幕与选中行信息；SE 4 的 WinForms DLL 不能直接使用。平台包按 Windows/macOS 和架构选择。
- 按需候选：**ASSA tag check**（ASS 标签检查）、**Fix encoding errors**（实际出现乱码时）。不因目录中存在就默认安装。
- **Split dialogs** 只拆已有的对话文本，并按文字长度分配时间；不分析音频，不做说话人检测，使用后必须听音校时。
- 不把 **Remove Unicode characters** 加入中泰字幕的默认清理步骤。插件先在副本上核对差异和撤销，不能假定所有插件都保真保留 ASS、角色与时间。
- 后续若确有批处理需求，可先评估 SE 自带 `seconv` 命令行能力；当前不要求另装或自建批处理界面。

多人识别须分别评估：手动角色标签、自动说话人检测、同时讲话的完整识别。Crisp ASR 的部分后端可用 Sortformer 检测说话人；MOSS Diarize 文档仅列英语/中文。`Isolate speech` 主要分离对白与音乐/音效，不能据此保证逐人分离重叠讲话。泰语适配及效果均待实测，不用不支持泰语的模型试图替代泰语转写。

## 4. 实施顺序与完成条件

按平台记录实际完成状态。下列 Windows 完成项不代表 Mac 通过；两机任务使用分项状态，另一平台继续保留待验。

### P0 · 盘点与保全

- [x] Windows：读取本文、[文档索引](README.md)及平台说明；检查 Git 已修改和未跟踪文件，保留已有适配成果并生成源码快照，未重置工作区。
- [x] Windows：盘点 2 个测试项目（共 16 条字幕，含 1 条人工中文），全部生成可恢复 ZIP、SQLite 一致性备份；另复制并逐文件校验媒体、原始字幕/ASR 和来源记录。隔离恢复及媒体重新关联通过后正常停止旧服务。
- [x] Windows：独立导出原文/中文及 cue 身份清单；中文 1 条、泰语原文 8 条在 SE 5.3.0 实际打开并核对时间、字形。项目均无说话人标签；未构造 Actor 迁移。中文空译文已明确省略，未按行号拼接。
- [ ] Mac：本机项目盘点、保全和按需迁移；当前未连接 Mac，不能据 Windows 测试项目推断 Mac 无重要内容。

Windows 保全位置：`output/se-handoff/20261025-212630-P0/`。`P0-report.json`、`restore-verification.json`、`studio-shutdown.json` 记录验证；素材副本 47 文件 / 961,710,629 字节，源码快照 83 文件，项目 ZIP 不含媒体。原库停机后所有表行与备份一致、完整性为 `ok`。这是 E 盘第二份本地副本，未声称已完成异机备份。原文件、环境和源码均保留；未为测试草稿建设迁移系统。

完成条件：已有人工内容可从备份取回，字幕在 SE 可打开；不要求把旧候选、审阅状态和全部历史转换成 SE 内部数据。普通 SRT/VTT 不携带完整 Studio 字段，`speaker` 标签文本也不等于结构化 Actor。没有重要项目时记录事实后跳过迁移，避免为测试草稿建设迁移系统。

### P1 · 下载入口独立化

- [x] 保留 `scripts/downloader.py` 的媒体优先、逐轨字幕、429 停止、旧字幕保护与来源记录行为；17 项单测和 7 个真实工具离线场景通过。
- [x] Windows/Mac 下载包装已改为独立选择兼容全局 Python；Windows 新增 `youtube_download.ps1`，旧 workbench 下载分支提前转发，核心自行查找工具。不会自动选项目 `.venv`、读取 Studio `.env` 或安装/启动 Studio。
- [x] Windows：5 项入口契约测试、四个真实包装的最小文件集合下载测试通过；覆盖引号中的 `&` URL、中泰字符/空格路径、独立输出、来源清单及返回码 0/1/2/7。复用既有工具，未重复下载原片。
- [ ] Mac：在真实 Mac 检查上述入口、工具路径、执行权限与输出。Windows Git Bash 语法/契约检查已通过，不能代替 Mac 实测。

Windows P1 证据：`output/se-validation/p1-download-validation.json`。日常推荐 `youtube_download.ps1` / `youtube_download.cmd`；Windows 最小运行集合还包括 `scripts/downloader.py` 与 `scripts/windows_environment.py`。下载器本身要求 Python 3.10+；可选旧工具安装器要求 3.11+，缺依赖提示已不再引向 `setup.cmd`。

完成条件：不启动或安装 Studio，也能下载媒体、字幕和来源清单。当前入口与后续改动界限见 [下载器说明](downloader.md)。

### P2 · SE 最小配置

- [x] Windows：复用 SE 5.3.0；真实短片画面/计时播放、波形、中泰字形、F5 选中句回放并在句尾停止均已观察。双栏以英文参考 22 条对照泰语稿 13 条，选择显示所有参考行并保持参考只读；英文不视为泰语原文。
- [x] Windows：配置 Thai / Whisper CPP / cuBLAS / `large-v3-turbo-q5_0`，复用并逐文件校验既有引擎和模型，未重新下载；基线控制台观察到 CUDA0，完成两次转写。详见 `output/se-validation/engine-audit.json`。
- [x] Windows：在 `clip-review.ass` 中保留中文待核对书签；保存、切换空稿、重开后全文恢复。字幕与 `clip-review.ass.SE.bookmarks` 必须成套保存。SRT 原稿保留，ASS 的厘秒精度会将 41.989 秒存为 41.99 秒。
- [x] Windows：在测试副本实际编辑并保存 Actor `QA_TEST_ONLY`，临时以 1 分钟自动备份保留未保存的中泰测试标记；撤销标记后，通过 `File → Restore auto-backup` 实际恢复并另存。备份与恢复文件逐字节一致、13 条字幕及全部时间保留、其余 12 条未变。配置已恢复为自动备份 5 分钟/90 天，自动保存关闭。测试标签不代表真实说话人，原始/审阅稿及书签哈希未变；自动备份不包含 `.SE.bookmarks`，书签需另行成套保全。
- [ ] Mac：在真实设备完成本阶段；Windows 观察不能代替 Mac 验收。

操作记录：`output/se-validation/se-ui-validation.json`；后续 Actor/自动备份恢复与文件核验见 `output/se-validation/p2-persistence-validation.json`。已验证播放控制、音频波形/识别链路及保存恢复机制；此次没有完成实际听音及泰语语言核对。

完成条件：本机实际播放、识别、编辑、保存重开可用；记录选择的引擎/模型/设备。Mac/Windows 可以采用不同硬件后端，不要求逐字一致或同步绝对路径。

### P3 · 真实困难片段与识别选型

- [x] Windows：使用测试视频 `7WbgUplUHWE` 从 **10:57（657 秒）起 60 秒**的既有片段，基线与单一 VAD 对照分别另存，未覆盖旧稿、未自动删重复。
- [x] Windows：仅比较一个针对重复的替代设置：同一引擎/模型/语言，启用 Silero VAD；英文翻译与后处理均关闭。基线 8 条，首句 `นี่` 连续 109 次；VAD 13 条，没有同一字串连续至少 3 次，但 SE 仍报 3 条过长。
- [x] Windows：核验既有视频完整英文 CC 为平台普通字幕轨，共 928 条；与原下载/P0 哈希一致，未重下视频。对 60 秒片段的 22 条英文与 13 条 VAD 泰语逐时间区间双向检查，并生成 22 条中文参考稿。区分主旨吻合、文本冲突和节目画面说明；尚未听原声，不计算准确率。
- [ ] 听音核对并记录漏句、错词/专名、时间偏差、说话人与人工修正耗时；补充分类型代表区间。当前两份稿均为**原声语义未验**，已有英文文本交叉核对，不报告准确率；VAD 是否漏掉轻声、插话及片尾仍待听校。

证据在 `output/se-validation/asr-comparison.json`，原始 SE 保存稿为 `clip-se-baseline.srt`、`clip-se-vad.srt`，工作副本为 `clip-review.ass`。优先回听片内 15.367–29.967 秒（倒数/欢呼与长时短文）、46.780–54.820 秒（专名/混说）、58.340–60.000 秒（VAD 无字幕）。英文参考来自既有平台字幕，保留偏移与来源清单，支持语义交叉核对和疑点定位，不能当作泰语逐字标准答案。基线临时日志未留存；VAD 捕获器因 Windows 路径大小写过滤失误错过进程，SE 已清理临时文件，未为补证据重跑。不能将另存 SRT 称为完整原始引擎日志。

英文 CC 对照成果：`output/se-validation/cc-crosscheck.html` 与 `cc-crosscheck.json` 保留正向/反向匹配、全文来源、哈希和逐条结论；`source-7WbgUplUHWE.en.srt` 是完整英文轨的逐字节副本，`clip-cc-reference-zh-draft.srt` 是对应 60 秒的中文参考草稿。英文来自 `platform_subtitles`，不是本次选中的自动翻译轨，但元数据不证明人工或官方作者。倒数、HarborLand 与尾句存在明显文本冲突/覆盖缺口；Bam 精力、没有注意他人、冒险与滑索主旨相符。末条英文原时间到 11:57.433，60 秒片段在 11:57.000 截断，需回到全片核查尾句。未将括号说明一律判成 ASR 漏句，也未将仅 7 ms 的边界重叠算成尾句已覆盖。

完成条件：得到可供人工校对的底稿，清楚记录未解决区间。有英文参考时先完成可做的文本核对，再将原声未核部分单列；不能仅凭中文通顺或英文回译相似判定准确率通过。

### P4 · 翻译与人工审阅

- [x] Windows：用三条英文平台参考验证 `Translate → Auto-translate via copy/paste`，以独占一行的 `(...)` 分隔候选；预览三条对应关系、点击 OK 采用、Ctrl+Z 恢复英文、Ctrl+Y 恢复中文，另存后实际重开。时间、Yu/Bam、否定和换行均保持，英文参考哈希未变。
- [ ] 在原文校对后继续验证上下文引擎、术语约束、局部重译和正式审阅；当前三条只是英文参考转中文的机制测试，不是泰语内容验收。
- [ ] 正式服务/本地模型选一个常用方案；本轮复制粘贴机制无需 API，未调用收费接口。
- [ ] 回听人名、数字、否定、称谓、混说、说话人切换和交叠区间。需要的插件只在副本上验证差异、取消/撤销与保存重开后再采用。

证据：`output/se-validation/p4-translation-validation.json`，输入为 `mechanism-reference-en.srt`，输出为 `mechanism-en-reference-zh.srt`，来源和测试上下文见 `mechanism-test-provenance.json`。复制粘贴入口按顺序匹配分段，采用前必须核对条数及对应关系；不要假定选中几行就只处理这几行，局部实验先使用单独副本。

完成条件：人工修改不会在日常操作中意外丢失，原文、译文及存疑项可继续编辑；不要求复刻私有候选指纹数据库。

### P5 · 整片交付

- [ ] 用 SE 完成同一完整视频的字幕流程，输出原语、中文和双语字幕；需要角色/样式时保留 ASS 源文件。
- [x] Windows：在 SE 选中三条中文测试稿，按 34.800–40.300 秒生成短烧录样片。AAC 版本 5.521 秒、165 视频帧、音视频均从 0 秒开始，完整解码通过；三处实际画面中文字形、换行及位置检查通过。SE 调起本机默认 PotPlayer，关闭外挂字幕后中文仍可见，已恢复播放器设置。
- [ ] 原文及译文审阅通过后，再生成最终整片，核对首/中/尾同步、音轨和新增中泰字幕。样片中原片自带的泰文画面不能证明新增泰语字幕已验证；本轮没有完成实际听音或整片验收。
- [x] Windows：引擎/模型、来源、实际问题和工程/语言/成片边界分别记录；首次音频 copy 的失败样片与修正后的 AAC 样片均保留。

推荐检查的短样片为 `output/se-validation/mechanism-sample-burned-aac.mkv`，仅含三条未经泰语核对的中文参考译稿。`p5-ui-validation.json` 记录实际操作，`p5-media-verification-aac.json` 记录解码、轨道及源音频区间匹配，截图在 `burned-frames-aac/`。初次 `audio copy` 产生 6.720 秒文件：视频内容仍为 5.5 秒，但音频带有选区前滚，视频流到 1.179 秒才开始；改用 AAC 48 kHz/stereo/128k 后消除该头部差异。见 `p5-media-verification.json`、`p5-copy-preroll-analysis.json`。本素材精确截段烧录采用 AAC，不用成功提示代替时间轴检查。

完成条件：存在可重复操作的实际成片流程与证据；不是只有“已安装”或一个成功退出码。复用已经下载的原片，不重复下载作为验收前提。

### P6 · 固定日常流程并退役运行入口

- [x] Windows：更新平台说明、下载说明与本计划，补充当前可用操作及实际 SE 验收边界；Mac 保留本机待验。
- [x] Windows：保全与隔离恢复通过后正常关闭旧 Studio 服务，保留源码/数据快照。
- [x] Windows：在当前用户桌面与开始菜单 `Subtitle Workflow` 组创建 `Subtitle Edit - SE Workflow`、`YouTube Downloader - SE Workflow`；分别直达 SE 和独立 `youtube_download.cmd`。目标、参数、工作目录及重复执行保真均已核对，下载器目标 `--check` 通过；46 个既有快捷方式哈希未变，旧 Studio 入口保留。证据：`output/se-validation/p6-shortcuts-validation.json`。
- [ ] Mac：在本机核对日常 SE/下载入口；后续制作过程补全两机日常流程。
- [ ] 后续正常制作字幕，只记录具体阻碍，不再保留 Studio 开发路线图、自动恢复开发的承诺或周期性维护任务。

<a id="cross-platform-sync"></a>

## 5. Windows → Mac 同步要求

1. **先确认真实文件差异。** 当前工作区包含已修改文件和未跟踪新文件；只复制 `git diff`、`git archive HEAD` 或在 Mac 执行 `git pull` 不会得到所有本机未提交成果。尤其 `youtube_download.command` 已依赖新增 `scripts/downloader.py`，必须成套交接。
2. **同步内容包括**：当前 README、AGENTS、有效文档、退役文档与重定向页、共享下载核心、必要入口/工具查找脚本、对应测试和属性文件。保全 Windows 已做的 Studio 代码差异用于历史快照；同步源码不代表要在 Mac 重新安装或继续开发 Studio。
3. **Git 同步须形成可核对版本。** 提交前审阅 `git status --short`、完整内容差异和新增文件名单；检查无凭证/用户素材。推送远端须用户另行要求，本次文档整理未提交或推送。Mac 合并前同样保存当地未提交修改，不用强制重置覆盖。
4. **不跨机复制运行环境**：`.venv/`、`frontend/node_modules/`、`frontend/dist/`、系统专用 EXE/DLL/.app、缓存和临时日志。媒体、数据库、字幕与模型需要迁移时按单独数据清单传输；不要合并覆盖两机同名 `.workbench-data/`。仓库已跟踪的 `examples/timing-check.mp4` 是可同步的合成测试样例。
5. **不直接复制配置和凭证**：`.env`、Cookie、API Key、含个人路径的完整 SE `Settings.json` 不进入源码同步。两机分别配置路径、快捷键、GPU 后端和字体；可核对后单独共享无密钥的术语、提示词和样式。
6. **Mac 验证**：核对 Apple Silicon 架构、`.command`/`.sh` 执行权限与 LF 换行；检查系统 Python 和 Homebrew/应用组件路径。按 P1–P5 在 Mac 记录自己的结果，不继承 Windows 的“通过”。
7. **退出条件**：两机能各自完成 SE 主流程，日常使用不要求 Node、FastAPI、worker 或 Studio 数据库。只在一台机器完成时保留另一台待验，不虚构远程执行。

退役资料使用 `docs/retired/`，因为本仓库已有 `.gitignore` 忽略 `docs/archive/`；不要把新交接资料放入被忽略目录而误以为已同步。

## 6. 接手时的已知状态

以下为 2026-10-25 的交接记录，执行者仍须在实际机器确认。

| 项目 | 当前证据与边界 |
|---|---|
| Windows 软件 | SE 5.3.0、FFmpeg/libmpv、下载工具与本地 Whisper 已安装；Node/Git/HandBrake 复用。详见 [Windows 说明](windows-setup.md) |
| Mac 软件 | 2026-10-23 历史记录称 SE 5.3.0 等已安装；本轮未连接 Mac 复核。详见 [Mac 说明](mac-setup.md) |
| SE 实战 | Windows 已完成播放/波形、本地 CUDA 泰语转写、书签/Actor/自动备份恢复、复制粘贴翻译的采用/撤销重开，以及 AAC 短样片烧录/外部播放；泰语语言质量、真实身份、上下文/局部重译及整片交付仍未验；Mac 未执行 |
| 测试视频 | Windows 已取得完整约 35 分 43 秒、1080p 视频及英文参考字幕；`t=657s` 是播放起点，下载保留整片 |
| 旧 Studio 短片 | 10:57 起 60 秒 GPU 转写完成，8 条待审稿，但存在明显重复；不作为识别质量通过 |
| 旧 Studio 整片 | 首次完整 ASR 在导入阶段因零时长字幕失败；后续修复有分项回归，但实际完整 API 重跑未完成。不要继续此项，除非阻碍现有资料导出 |
| 多人标注改动 | 保存/撤销/恢复等分项测试通过；最后前端多句预览未完成浏览器验收。无需为退役 Studio 补齐它 |
| 付费翻译 | 未配置和实际调用；模拟测试不等于真实服务通过 |

Windows 本地素材位于 `output/windows-validation/`：完整视频在 `downloads/`，短片为 `YouTube-7WbgUplUHWE-10m57s-60s.mp4`。该目录及 `test-results/`、`output/multispeaker-qa/` 均被 Git 忽略，Mac 不会通过源码同步自动取得它们。`real-workflow.json` 是未完成验收记录；`clip-burned-draft.mp4` 含字体测试文字与未审 ASR，只是渲染测试片，不能当成审定译制成品。

已知旧代码问题仅作交接：相同时间字幕可能按 UUID 重排，P0 已保留原始项目 JSON 与 cue 身份；安装器逐文件大小检查可能把 Aegisub 正常更新误判为需重装。P1 已修正下载器缺依赖时运行 `setup.cmd` 的误导提示。不要为归档用途扩大修复；P2 直接复用已有组件，不运行全量重装。

## 7. 重新开发的门槛

必须先具备真实素材上的可复现必要问题、明确期望结果与验收方式，并验证内置设置、现成插件/工具仍不能合理解决。再比较人工绕行的频率/耗时与维护成本，由用户确认最小补充范围。

已有代码、界面熟悉、记录字段更丰富、一次识别错误都不自动触发重启开发。优先一个小脚本/插件；恢复完整 Studio 必须重新论证。

## 8. 官方依据与新对话入口

功能依据（已核查，实施时复核实际版本）：[SE 5.3.0 主窗口](https://github.com/SubtitleEdit/subtitleedit/blob/v5.3.0/docs/features/main-window.md)、[识别与说话人限制](https://github.com/SubtitleEdit/subtitleedit/blob/v5.3.0/docs/features/speech-to-text.md)、[高级翻译](https://github.com/SubtitleEdit/subtitleedit/blob/v5.3.0/docs/features/auto-translate-advanced.md)、[AI Review](https://github.com/SubtitleEdit/subtitleedit/blob/v5.3.0/docs/features/ai-review.md)、[Actor/书签](https://github.com/SubtitleEdit/subtitleedit/blob/v5.3.0/docs/features/subtitle-grid.md)、[复制粘贴翻译](https://subtitleedit.github.io/subtitleedit/features/copy-paste-translate.html)、[插件规范](https://github.com/SubtitleEdit/subtitleedit/blob/v5.3.0/docs/plugin.md)、[官方插件目录](https://github.com/SubtitleEdit/plugins)、[seconv](https://github.com/SubtitleEdit/subtitleedit/blob/v5.3.0/docs/reference/command-line.md)。

新对话可直接使用：

> 请读取 AGENTS.md、README.md 和 docs/se-workflow-plan.md，从当前平台未完成项继续 SE 主流程。Windows P0/P1、P2 操作恢复、P4 复制粘贴机制、P5 AAC 短样片和 P6 日常入口已验证，不重复这些验收。优先处理 P3 的泰语听音校对及真实说话人确认，再完成上下文/局部重译和整片交付；查看 output/se-validation/ 的底稿、待核对区间及 p4/p5 证据。Mac 仍须从本机 P0 盘点开始。保留未提交改动与既有安装。Studio 已停止开发，只允许旧资料保全/导出及独立下载器必要维护；不要执行退役路线图，不删除原片/人工稿/数据库/快照，不默认开启收费服务，不自动提交/推送。语言质量未验不阻碍独立的工程检查，但不能将三条英文参考测试稿升级成泰语或整片验收通过。

## 9. 执行记录

| 日期 / 平台 | 阶段 | 实际动作与证据位置 | 结果 / 未验项 |
|---|---|---|---|
| 2026-10-25 / Windows | 文档交接 | 新计划、入口与旧文档退役 | 仅完成文档整理；P0–P6 待新对话实施 |
| 2026-10-25 / Windows | P0 | `output/se-handoff/20261025-212630-P0/`：SQLite 在线备份、两个项目 ZIP、47 个素材/原始结果副本、83 文件源码快照；`restore-verification.json` 实际隔离恢复与媒体重新关联；`P0-report.json` 导出与 SE 打开记录 | 本机通过：16 条字幕、1 条人工中文保留，独立原文/译文文本和毫秒时间核对通过；Mac 待盘点；同盘副本不等于异机备份 |
| 2026-10-25 / Windows | P0 停机 | 上述目录 `studio-shutdown.json`；向已核验 launcher 进程组发送 `CTRL_BREAK` | API 正常关闭、6 个项目进程退出、8765 无监听；停后数据库内容与一致性快照相同，无文件删除 |
| 2026-10-25 / Windows | P1 | `output/se-validation/p1-download-validation.json`；独立 PowerShell/cmd/Mac 薄入口和 Windows 工具定位 | 17 单测、5 入口契约、7 真实工具离线场景通过；四个 Windows 包装在无 Studio 的中泰空格目录实际下载与来源清单通过；Mac 仅 Git Bash 检查，实机待验 |
| 2026-10-25 / Windows | P2 操作机制 | `output/se-validation/se-ui-validation.json`、`engine-audit.json`、`p2-persistence-validation.json`；真实 SE UI 播放、波形、F5、双栏、ASS/书签重开、Actor 测试标签与自动备份恢复 | 本机机制通过；备份与恢复稿逐字节一致，原稿哈希未变；书签旁文件须单独保全；无真实身份、听音/语言准确率通过声明 |
| 2026-10-25 / Windows | P6 日常入口 | `scripts/create_windows_shortcuts.ps1 -Desktop`；`output/se-validation/p6-shortcuts-validation.json` | 桌面/开始菜单共 4 个新快捷方式；SE 与独立下载器目标核对通过，重复执行不改动，46 个旧快捷方式保留；Mac 及正常制作流程仍待验 |
| 2026-10-25 / Windows | P3 底稿 | `output/se-validation/asr-comparison.json`；8 条基线与 13 条 VAD 独立保存；只读英文参考与中文待核对书签 | 长串重复缓解；3 条过长，片尾可能漏句，语义及时间仍待人工复核；未试更多模型，未进入整片翻译/成片验收 |
| 2026-10-25 / Windows | P4 翻译机制 | `output/se-validation/p4-translation-validation.json`；3 条英文参考的中文候选预览、采用、撤销、重做、另存重开 | 时间/专名/否定/换行通过；上下文引擎、局部重译及泰语听音语义仍未验 |
| 2026-10-25 / Windows | P5 短样片 | `p5-ui-validation.json`、`p5-media-verification-aac.json`、`p5-copy-preroll-analysis.json`；SE 实际生成、外部播放器隐藏外挂字幕与三处画面检查 | 音频 copy 前滚已用 AAC 重编码解决，5.521 秒样片工程通过；整片、中泰译文及真实听音未验 |
