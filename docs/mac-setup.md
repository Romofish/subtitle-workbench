# Mac 本地字幕工作台：安装与启动

验证环境：Apple Silicon M4、16 GB 内存、macOS 15.8。程序、依赖和按需安装的外部免费工具放在项目目录，不要求购买插件。仓库只包含源码和安装脚本，不附带已安装的运行环境、模型、应用或个人数据。首次安装需要网络；本地编辑、项目保存、字幕导出不需要 AI 密钥。

## 日常启动

双击项目根目录的 `start.command`，等待浏览器打开 <http://127.0.0.1:8765>。保留终端窗口；结束时按 `Ctrl+C`，启动器会一起关闭 API 和独立翻译 worker。已有编辑保存在 `.workbench-data/`，再次启动即可重开。

首次缺少环境或前端构建时，启动脚本会先执行安装；也可以单独双击 `setup.command`。更新源码后再次运行 `setup.command`，它按依赖锁安装并重新构建前端。该脚本不删除项目数据、旧虚拟环境或原始素材。

终端运行：

```sh
# 在克隆或下载的项目目录中执行
./setup.command
./start.command
# 不自动打开浏览器
./start.command --no-open
```

服务只监听 `127.0.0.1`，不开放局域网。API 与前端共用 8765 端口，翻译任务由另一个 Python 进程执行。端口已占用时脚本停止并说明原因，不会终止其他应用。日志位于 `.workbench-data/logs/api.log` 和 `worker.log`。

## 独立运行环境

| 组件 | 验证时使用的版本 / 路径 | 用途 |
|---|---|---|
| Python | 3.13.7；`.venv/bin/python` | FastAPI、SQLite 操作、worker |
| Node.js | v24.5.0；`/opt/homebrew/bin/node` | 安装前端依赖及 Vite 构建 |
| FFmpeg / ffprobe | 9.0.2；`/opt/homebrew/bin/` | 媒体探测与按需浏览器预览 |
| yt-dlp | 2026.08.19；`/opt/homebrew/bin/yt-dlp` | 现有独立下载脚本 |

工作台使用兼容的 Python 3.12/3.13 创建 `.venv`，不依赖系统默认 Python 的版本。Python 直接依赖列于 `backend/requirements.txt`，包括传递依赖的验证环境锁定版本列于 `backend/requirements.lock`；前端使用 `frontend/package-lock.json`。

新机器需要 Python 3.12/3.13、Node.js 20.19+ 或 22.12+、FFmpeg / ffprobe。已安装 Homebrew 时可先运行 `brew install python@3.13 node ffmpeg`。`setup.command` 会优先寻找兼容 Python，并可通过已有的 Homebrew 补装缺少的 Python 3.13 和 FFmpeg；Node.js 须先准备好。也可设置 `WORKBENCH_PYTHON=/绝对路径/python3.13`。原 `.venv` 如果版本不兼容，先另存改名再重建，不要移动现成虚拟环境到另一台电脑。

## AI 配置

`setup.command` 会在 `.env` 不存在时从 `.env.example` 创建一份权限仅限当前用户的配置。填写 `OPENAI_API_KEY`、`OPENAI_MODEL`，明确接受该服务计费后将 `TRANSLATION_ALLOW_PAID` 改为 `true`，再重启工作台。默认值保持空密钥、空模型、关闭调用；本次安装不调用收费服务。

当前连接使用 OpenAI Responses API，默认地址 `https://api.openai.com/v1`；自定义地址也必须实现相同接口。界面会展示选中字幕与上下文发送范围，媒体文件不随字幕翻译请求上传。真实服务和语言质量验收须在用户确定服务、模型与费用后另做，不能把本地模拟测试当作实际翻译验收。

## 已选外部 Mac 工具

以下版本曾从官方发行下载并验证，仓库不包含应用本体。预期 SHA-256、文件大小与来源由安装清单和下载脚本记录。安装后应用位于 `tools/mac-apps/`，可直接双击，也可自行将 `.app` 拖到“应用程序”。这些应用均为按需选择，不是工作台启动依赖。

| 工具 | 版本 / 架构 | 使用时机 | 官方来源 |
|---|---|---|---|
| Subtitle Edit | 5.3.0 / Apple Silicon arm64 | 格式处理与外部烧录；语音识别为备选 | [官方发行](https://github.com/SubtitleEdit/subtitleedit/releases/tag/v5.3.0) |
| LosslessCut | 3.70.1 / Apple Silicon arm64 | 需要粗剪时使用，切点与字幕同步另验 | [官方发行](https://github.com/mifi/lossless-cut/releases/tag/v3.70.1) |
| IINA | 1.5.0 / Universal，含 arm64 | 交付播放、外挂字幕与固定字幕检查 | [官方下载](https://iina.io/download/) |
| Aegisub | 3.5.1 / Apple Silicon arm64 | 内容与时间确定后制作 ASS 样式、排版 | [官方发行](https://github.com/TypesettingTools/Aegisub/releases/tag/v3.5.1) |
| HandBrake | 1.11.2 / Universal，含 arm64 | 转码、ASS/SSA/SRT 烧录与成片对比 | [官方发行](https://github.com/HandBrake/HandBrake/releases/tag/1.11.2) |

Subtitle Edit 官方 Mac DMG 自带运行时、FFmpeg 和 libmpv，工作台不替换它们；[官方安装说明](https://github.com/SubtitleEdit/subtitleedit#-system-requirements)说明 5.2.0 起使用签名和 Apple 公证安装包。安装脚本进行 SHA-256、`codesign` 和 Gatekeeper 检查，不移除隔离属性、不修改系统安全设置。

可重复下载与安装：

```sh
.venv/bin/python scripts/download_mac_tools.py
# 当前代理速度较慢时，可自行选择官方站点直连
.venv/bin/python scripts/download_mac_tools.py --direct --connections 6
bash scripts/install_mac_tools.sh
```

下载脚本支持分段继续，完整合并后才接受通过官方 SHA-256 的文件。官方来源不能访问时保留可继续的分段，不能把不完整 DMG 当作已安装。

本地转写使用 whisper.cpp 1.9.5 与多语言 large-v3-turbo-q5_0（574,041,195 字节），安装到 `tools/asr/`。新机器须先准备 Apple Command Line Tools（`xcode-select --install`），再运行 `.venv/bin/python scripts/setup_asr.py`。脚本下载固定源码、CMake 和模型，在本机编译 arm64 引擎并使用 Metal；模型按官方 LFS SHA-256 校验。应用启动不会自行下载模型。安装记录生成在 `tools/asr/manifest.json`，操作见 [无字幕素材处理](no-subtitle-workflow.md)。这些组件供工作台使用，Subtitle Edit 内的引擎配置仍独立。

验证环境未安装 Shotcut、Shutter Encoder。Aegisub 与 HandBrake 于 2026-10-23 追加验证。FFmpeg 构建是否包含字幕烧录滤镜不影响工作台的文字审阅；外部发布应检查所用软件的实际组件。

## 本机验收记录与待验项

已通过：Python 3.13 隔离环境安装、全部后端依赖一致性检查（`pip check`）、启动脚本 Bash/Python 语法检查，以及临时数据目录上的启动/关闭烟测。烟测确认 API 健康检查成功、FFmpeg / ffprobe 可用、独立 worker 正常存活；向启动器发送结束信号后服务正常退出，端口释放。

三个外部工具已全部下载并安装到 `tools/mac-apps/`。Subtitle Edit 5.3.0、LosslessCut 3.70.1、IINA 1.5.0 的 DMG 均与官方公布的 SHA-256 一致；复制前后 `codesign --verify --deep --strict` 全部通过，Gatekeeper 对三个应用均返回 `accepted`、`source=Notarized Developer ID`。应用版本已从 Info.plist 核对，执行文件检查确认前两个为 arm64，IINA 为包含 arm64 的 Universal 二进制。

macOS `open` 对三个应用均成功返回，IINA 的启动参数指定工程测试视频。界面检查工具在获取 Subtitle Edit 界面时长时间无响应，已中断；因此只记录启动命令成功，不宣称 GUI 播放、编辑或 ASR 已通过。未修改隔离属性或系统安全设置。

Subtitle Edit 自带 FFmpeg 8.1 的 `ass`、`subtitles` 滤镜已实际列出，弥补系统 FFmpeg 缺少字幕烧录滤镜的组件条件；本次未执行烧录样片。工作台内置 ASR 已用 30 秒真实泰语片段跑通，生成 17 条待审字幕；浏览器内上传、任务完成、重开编辑和导出通过。真实泰英混说准确率、外部工具播放及固定字幕成片仍待专门验收。外部应用安装元数据见 `tools/mac-apps/manifest.json`。

正式素材仍需人工检查：媒体与原语字幕同时间轴、首中尾同步、中泰英字形、原文与中文语义、发布编码、关闭外挂字幕后固定字幕仍可见。不得将生成的开发演示媒体当作真实语言质量样片。


## 2026-10-23 清理与新增工具

验证环境曾清理旧 DMG、ASR 编译器、源码、构建目录和源码压缩包约 827.42 MiB；新安装 Aegisub 与 HandBrake 的两个 DMG 经验证后也清理约 75.07 MiB。合计清理对象原占用约 902.49 MiB，保留模型、引擎、应用、运行依赖、项目数据与原始素材。这不是新增应用安装后净磁盘变化的测量；个人清理清单不随仓库发布。

两款新应用的官方 SHA-256、复制前后 codesign、Gatekeeper 公证检查均通过。Aegisub 是 arm64 原生程序；HandBrake 为包含 arm64 的 Universal。已通过 macOS open 打开工程测试字幕/视频，并实际观察到两个应用进程；界面检查工具卡住，备用辅助功能读取也未获权限，故不宣称 GUI 编辑、字幕实际渲染、烧录质量对比已验收。没有绕过 Gatekeeper、移除隔离属性或改动系统安全设置。

清理后工作台 `/api/health` 正常，`/api/asr/status` 为 `ready=true`，whisper.cpp 1.9.5 可运行。这是验证环境的历史结果，新机器仍需执行安装并检查状态。

后续只恢复指定工具可用：

```sh
.venv/bin/python scripts/download_mac_tools.py --only Aegisub HandBrake
bash scripts/install_mac_tools.sh --only Aegisub HandBrake
```

安装脚本会先跳过已有 `.app`，不要求重下已经清理的安装包。CMake、源码与构建材料只在重建引擎时需要；日常启动不依赖它们。

### 排版与烧录交接

工作台确认内容与时间轴 → 导出字幕 → Aegisub 调整字体、字号、描边、位置，另存 ASS → HandBrake 或 Subtitle Edit 读取同一份原视频和 ASS，分别生成成片。保存 ASS 作为样式源文件，不用 SRT 代替它保存排版。

HandBrake 可以选择一个连续时间/章节/帧区间进行编码，但不支持把多个片段拼接成一条，且输出视频会重新编码；多段剪辑仍交给 LosslessCut 或其他剪辑器。[官方功能边界](https://handbrake.fr/docs/en/latest/introduction/about.html)、[区间编码](https://handbrake.fr/docs/en/latest/advanced/point-to-point.html)

当前 Mac 1.11.2 的官方源码允许直接导入独立 `.ass` / `.ssa` / `.srt`，无需为这个版本强制增加 MKV 封装步骤；具体字体与特效仍以实际渲染为准。[支持扩展名](https://github.com/HandBrake/HandBrake/blob/1.11.2/macosx/HBUtilities.m#L379-L382)、[导入实现](https://github.com/HandBrake/HandBrake/blob/1.11.2/macosx/HBSubtitles.m#L211-L217)

质量比较时从同一个原片分别输出，保持分辨率、帧率、裁切、字幕和编码设置可比；记录编码器、质量值、体积与耗时，检查文字边缘、运动画面、暗部和同步。不要把一个工具已压制的输出再交给另一个作为比较源。
