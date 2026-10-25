> **已退役 · 2026-10-25**：本文保留旧 Studio 方案与当时记录，不再作为实施依据。旧文中的“必须”“唯一主计划”“下一步”均已失效。当前决策与任务以 [SE 主流程实施计划](../../../se-workflow-plan.md) 为准。仅允许为读取、备份、导出旧项目参考运行步骤；不要据此重新启动 Studio 开发。

# Windows 本地字幕工作台：安装与启动

适用 Windows x64。工作台沿用 Mac 的 React 界面、FastAPI API、SQLite 数据与字幕格式，Windows 入口负责解释器、工具路径和进程生命周期。现有 Mac `.command` 入口继续保留。安装完成与实际流程验收分别记录；本文末尾列出 Windows 待验项。

## 软件位置与复用规则

默认使用当前用户在 C 盘的常用软件目录，无需替换其他项目使用的 Python，也不修改系统全局 PATH。

| 内容 | 默认位置 |
|---|---|
| Python 3.13 | `%LOCALAPPDATA%\Programs\Python\Python313\python.exe` |
| FFmpeg、yt-dlp、Deno 与外部工具 | `%LOCALAPPDATA%\Programs\SubtitleWorkbench\` 下各工具目录 |
| whisper.cpp 与全部配套 DLL | `%LOCALAPPDATA%\Programs\SubtitleWorkbench\asr\bin\` |
| 多语言模型 | `%LOCALAPPDATA%\Programs\SubtitleWorkbench\asr\models\ggml-large-v3-turbo-q5_0.bin` |
| 普通软件安装清单 | `%LOCALAPPDATA%\Programs\SubtitleWorkbench\installed.json` |
| 识别引擎与模型安装清单 | `%LOCALAPPDATA%\Programs\SubtitleWorkbench\asr\manifest.json` |
| 项目独立 Python 环境 | 项目目录 `.venv\Scripts\python.exe` |
| 数据、媒体副本、日志 | 项目目录 `.workbench-data\` |

`LOCALAPPDATA` 在典型安装中为 `C:\Users\用户名\AppData\Local`。外部应用采用便携发行包；手动打开时从对应目录运行程序。工作台启动会在自身进程内补充工具路径，已有 PATH 中的工具优先使用。

安装器会查找当前 PATH 和常见软件目录，复用发现的已有工具；本工具目录中的安装还会检查完成记录，避免把中断解压留下的孤立 EXE 当作完整安装。独立位置的便携软件可先加入当前终端 PATH，再执行安装。已安装的 Node.js、Git、HandBrake 继续使用，无须重复安装。存在安装清单不表示 GUI、识别质量或烧录效果已经通过验收。

便携包先解压到工具目录下的 `.staging`，完整检查后才放入正式目录；需要替换的旧目录保留在 `backups`。`installed.json` 以完整文件原子更新；损坏的清单会明确提示并保留，启动仍可查找已知工具目录。

可通过 `WORKBENCH_PYTHON` 指定兼容 Python 的完整路径，通过 `WORKBENCH_TOOLS_DIR` 指定便携工具目录，通过 `SUBTITLE_ASR_DIR` 单独指定识别组件目录。自定义位置时应在安装与启动时使用一致设置。

### 2026-10-25 本机安装快照

本次新增工具安装在 C 盘的 `%LOCALAPPDATA%\Programs\SubtitleWorkbench\`，项目源码、虚拟环境和工作台数据仍位于 E 盘项目目录。下表记录实际安装清单及已核对的已有软件版本；它不是整套流程通过记录。

| 组件 | 本机版本 / 类型 | 位置或处理方式 |
|---|---|---|
| Python | 3.13.17 x64 | `%LOCALAPPDATA%\Programs\Python\Python313\`；保留原 Python 3.11 |
| Node.js | 22.17.0 | 复用 `C:\Program Files\nodejs\` |
| Git | 2.53.0.windows.2 | 复用 `C:\Program Files\Git\`；用于源码管理 |
| FFmpeg / ffprobe | 9.0.2 | 工具目录 `ffmpeg\ffmpeg-9.0.2-essentials_build\bin\` |
| yt-dlp | 2026.10.21 | 工具目录 `yt-dlp\` |
| Deno | 2.9.8 | 工具目录 `deno\` |
| whisper.cpp | 1.9.5，官方 b5454 CUDA x64 包 | 工具目录 `asr\bin\`，包含运行所需 DLL |
| Whisper 多语言模型 | large-v3-turbo-q5_0，574,041,195 字节 | 工具目录 `asr\models\` |
| Subtitle Edit | 5.3.0 | 工具目录 `SubtitleEdit\` |
| Aegisub | 3.5.1 | 工具目录 `Aegisub\aegisub-portable\` |
| LosslessCut | 3.70.1 | 工具目录 `LosslessCut\` |
| VLC | 3.0.24 | 工具目录 `VLC\vlc-3.0.24\` |
| HandBrake | 1.11.2 | 复用 `C:\Program Files (x86)\HandBrake\HandBrake.exe` |

Subtitle Edit 本机已有 `libmpv-2.dll`，其首次下载的 `ffmpeg\ffmpeg.exe` 也已通过版本命令核对为 9.0.2。Subtitle Edit 与 Aegisub 的样例字幕载入已有窗口标题证据；实际播放、字体和成片质量仍须分别验收。

## 首次安装

需要 Python 3.12/3.13、Node.js 20.19+ 或 22.12+、FFmpeg / ffprobe。下载器另外需要 yt-dlp，建议 Deno；已有 Node.js 也可作为受支持的 JavaScript 运行时。SQLite 随 Python 提供，不需要数据库服务。

已有可运行 Python 3.11 或更新版本时，可在项目目录显式运行软件安装器；它将另外安装本项目需要的 Python 3.13，不改变原有 Python 的 PATH 优先级：

```powershell
python -X utf8 scripts/install_windows_tools.py --only all
```

尚无可用 Python 时，先从 [Python 官方 Windows 下载页](https://www.python.org/downloads/windows/) 安装 Python 3.13 x64，再使用该解释器执行安装器。安装器支持 `--only python`、`--only core`、`--only gui`；`core` 是 FFmpeg、yt-dlp、Deno，`gui` 是 Subtitle Edit、Aegisub、LosslessCut、VLC。需要 Node.js 时从其官方发行安装兼容 LTS，再重开终端。

普通软件安装器从固定官方发行下载文件；Python 安装程序检查 Python Software Foundation 的有效签名，其余已固定的压缩包/可执行文件检查 SHA-256。校验不通过时保留文件并停止采用，不把不完整下载当作已安装。

基础软件准备后：

```powershell
.\check.cmd
.\setup.cmd
.\start.cmd
```

`setup.cmd` 创建本机 `.venv`、按后端依赖锁安装、运行 `pip check`、`npm ci` 与前端正式构建；只有 `.env` 不存在时才从 `.env.example` 创建。已有 Mac `.venv` 不可直接使用，脚本会要求先保留并改名。重新执行环境安装不会删除项目数据或原始素材。

`check.cmd` 输出工具路径、版本、前端构建、ASR 文件和默认端口情况。它是环境诊断，不访问 YouTube，也不代表模型识别或整个应用已完成测试。

## 日常使用

双击 `start.cmd`，浏览器打开 `http://127.0.0.1:8765`，保留终端窗口。服务只监听本机回环地址；端口被占用时会停止并说明，不关闭其他应用。

```powershell
.\start.cmd --no-open
.\start.cmd --port 8766
```

`Ctrl+C` 请求 API、worker 与正在运行的识别工具停止。Windows 启动器使用协作退出和 Job Object 清理；关窗与取消的实际表现须按下方验收项检查。日志位于 `.workbench-data\logs\api.log` 和 `worker.log`。已提交的编辑保存在 SQLite，下一次启动可重开。

所有 `.cmd` 入口经 `workbench.cmd` 定位 Python 并设置 UTF-8，常规操作无须激活虚拟环境。入口失败时保留窗口显示错误；自动化执行可设置 `WORKBENCH_NO_PAUSE=1`，避免等待按键。

## 本地语音识别

```powershell
.\setup_asr.cmd
# 明确选择 NVIDIA CUDA 或 CPU 安装包
.\setup_asr.cmd --backend cuda
.\setup_asr.cmd --backend cpu
```

Windows 使用固定 whisper.cpp 1.9.5 对应的官方 `b5454` x64 预编译发行包。默认 `auto` 能检测到 `nvidia-smi` 返回 GPU 时选择 CUDA，否则选择 CPU。CUDA 12.4 发行包包含引擎依赖的 CUDA DLL，无须为运行此包安装完整 CUDA Toolkit 或重新编译；首次执行仍需验证驱动与实际 GPU 可用性。[官方发行](https://github.com/ggml-org/whisper.cpp/releases/tag/b5454)

两种系统共用 `large-v3-turbo-q5_0` 多语言模型，574,041,195 字节。已有同一模型可放入目标 `models` 目录；安装器必须验证大小和固定 SHA-256 后才复用。已有引擎则检查安装清单中全部文件的哈希，避免重复下载；需要重新部署时先保留旧 `bin` 目录备份。

保持安装的 CUDA 引擎，临时使用 CPU：

```powershell
$env:SUBTITLE_ASR_DEVICE = 'cpu'
.\start.cmd
```

恢复自动 GPU 选择：

```powershell
$env:SUBTITLE_ASR_DEVICE = 'auto'
.\start.cmd
```

`SUBTITLE_ASR_DEVICE` 支持 `auto` 或 `cpu`，也可在本机 `.env` 中设置并重启。切换设备不下载模型，不改已有项目。`--backend` 选择安装包；`SUBTITLE_ASR_DEVICE` 选择运行方式，两者用途不同。

进入“从视频识别”，选择视频或音频、语言和可选音轨，完成后明确打开生成的待审项目。首次先用短片检查 GPU 日志、字幕文字和时间轴，再处理整片。识别耗时与准确率不能沿用 Mac 历史数据；泰英混说、专名、静音与同步仍须人工复核。

### 多人讲话的审阅

当前识别流程不自动可靠辨识说话人身份，也不自动分离同时讲话的声音。多人交叠、背景说话和短促插话可能导致漏词、串词或重复，机器底稿仍需逐句试听。

在“当前字幕”编辑区可填写可选说话人（最多 100 字，如 A、B 或姓名），并标记“交叠发言”“听不清”。字段与原文、译文一起自动保存，纳入版本冲突保护、修订、撤销和项目备份。审阅队列显示这些标记，搜索也包含说话人；“风险提示”可集中查看需复核的条目。“时间重叠”表示字幕时间区间相交，“交叠发言”则是人工听音标记。

播放预览会按当前时间堆叠显示所有生效字幕及各自的说话人，当前选中句使用编辑草稿，其余使用已保存内容。逐句循环仍以当前选中句的时间区间为准。导出时可选择“在字幕文字中显示说话人”，默认关闭；开启后以 `[说话人]` 标签加入原文、中文或双语 SRT / VTT。

识别风险包括“识别重复疑点”“识别片段过长”“识别时间异常，需校对”。提示用于辅助定位，不自动删词或确认人物身份。引擎输出零时长字幕时，工作台保留原文字并建立 1 毫秒占位时间窗，同时记录原始时间；应先试听重设时间，再确认已审。原始识别 SRT / JSON、风险统计及时间调整记录保留用于核对。

## 独立下载器

```powershell
.\youtube_download.cmd --check
.\youtube_download.cmd 'https://www.youtube.com/watch?v=VIDEO_ID'
# 仅解析格式，不下载媒体或字幕
.\youtube_download.cmd --simulate 'https://www.youtube.com/watch?v=VIDEO_ID'
# PowerShell 中传入含 & 的网址，推荐原生 PowerShell 入口
.\workbench.ps1 download 'https://www.youtube.com/watch?v=VIDEO_ID&t=657s'
```

双击 `youtube_download.cmd` 后粘贴链接即可。PowerShell 中包含 `&` 的网址建议使用原生入口，例如 `./workbench.ps1 download 'https://www.youtube.com/watch?v=VIDEO_ID&t=657s'`，避免 PowerShell 与 CMD 两层转义。Windows 读取系统配置的“下载”目录，默认在其中建立 `YouTube\视频标题 [视频ID]\`。可在当前 PowerShell 指定输出目录或代理：

```powershell
$env:YOUTUBE_DOWNLOAD_DIR = 'E:\Media\YouTube'
$env:PROXY_URL = 'http://127.0.0.1:7897'
.\youtube_download.cmd 'https://www.youtube.com/watch?v=VIDEO_ID'
```

代理地址仅是填写示例，按本机实际代理设置使用。默认先完成媒体，再逐轨取得独立 SRT；字幕失败不会撤销已完成媒体。遇到 HTTP 429 会停止剩余字幕请求，保留已成功文件。默认不取平台自动翻译，来源清单保留本轮实际结果并去除签名 URL 等临时凭据。下载完成的退出码不表示每一种字幕均已取得，须同时看清单和摘要。

带 `t=` 的 YouTube 链接表示播放器起点；常规下载仍取得整段视频。需要用于短片识别或烧录测试时，应另存测试片段，并使用该片段自己的时间轴。

## 外部排版、剪辑与烧录

- Subtitle Edit：字幕格式处理、备用识别和烧录。Windows 版会在首次需要时提示补充 FFmpeg / libmpv；不要把安装主程序等同于这些功能已就绪。[官方组件说明](https://subtitleedit.github.io/subtitleedit/overview.html)
- Aegisub：内容和时间确定后编辑样式，另存 ASS；需要相同中泰文字体才能比较 Mac 与 Windows 的外观。
- LosslessCut：可选粗剪。关键帧会影响无损切点，输出后检查接缝与字幕时间。
- VLC：播放原片、外挂字幕和烧录成片，承担 Mac 上 IINA 的检查角色。
- HandBrake：复用已有安装，转码和字幕烧录后检查最终成片。对照不同工具时都从同一原片输出，避免再次编码另一工具的成片。

常规交接是：下载或选择原片 → 可选剪辑 → 导入字幕或本地识别 → 工作台审阅 → 导出 SRT / VTT → 按需用 Aegisub 排版另存 ASS → 外部烧录 → 播放检查。

## AI、备份与数据迁移

本地编辑、识别和导出不需要 API Key。AI 翻译默认关闭，只有本机配置密钥、模型并明确开启后才可调用；此次 Windows 验收不应把离线测试当作真实付费翻译测试。

Mac 项目迁移优先使用工作台导出的项目包，再在 Windows 关联 SHA-256 一致的媒体。不要复制 Mac 虚拟环境或可执行识别引擎；模型文件可校验复用。完整数据库备份使用工作台提供的 SQLite backup API；恢复操作见 [验收及限制](acceptance.md)。

## Windows 验收状态

当前本文的状态为 **pending，尚未完成整套 Windows 流程验收**。安装快照与部分分项证据已记录，最终回归和实际工作流程仍在核对。完成后应另记录实际命令、工具版本、样片信息与结果，不引用 Mac 的通过记录替代。

待检查或最终回归确认：后端与下载器测试、前端构建、中文/空格路径、UTF-8 中泰英字幕、独占 worker、启动/取消/关窗后的进程和端口释放；真实链接下载及来源清单；真实短片 GPU 识别、编辑保存重开、字幕导出、备份恢复；说话人及听音标记的保存、冲突、撤销与可选标签导出；两条同时生效字幕的预览；外部软件播放、ASS 字形与烧录成片。合成测试不代表真实语言准确率，安装/进程启动成功也不代表 GUI 操作或成片质量已通过。
