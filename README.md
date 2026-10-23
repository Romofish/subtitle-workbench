# 字幕审阅工作台

面向 Apple Silicon Mac 的本地字幕审阅应用，附带独立的 [YouTube 下载脚本](youtube_download.command)。支持已有 SRT / VTT 导入、本地语音转写、原文与中文逐句审阅、修订保护和字幕导出。React + TypeScript + Vite 界面、FastAPI API、SQLite 存储与独立 Python worker。

字幕与媒体保存在本机。AI 翻译默认未配置、关闭调用；开启并确认任务后，仅发送预览里的字幕文本、邻近上下文与术语。仓库不包含用户媒体、字幕项目、密钥、模型或第三方应用安装包。

## 启动

新机器先准备 Python 3.12/3.13、Node.js 20.19+ 或 22.12+、FFmpeg / ffprobe。已安装 Homebrew 时可运行 `brew install python@3.13 node ffmpeg`，然后在下载或克隆的项目目录操作。安装脚本会下载 Python / npm 依赖；它不自动安装语音模型和外部字幕应用。

```sh
git clone https://github.com/Romofish/subtitle-workbench.git
cd subtitle-workbench
./setup.command
./start.command
```

1. 第一次使用或更换机器：双击 [setup.command](setup.command)，安装锁定依赖并构建界面。
2. 双击 [start.command](start.command)。浏览器打开 `http://127.0.0.1:8765`，保持启动的终端窗口运行。
3. 点“新建项目”：已有字幕选 UTF-8 SRT / VTT；没有字幕选“从视频识别”，上传视频或音频后点“开始本地识别”。识别完成后点“打开项目”，逐句审阅机器底稿。没有媒体也能单独编辑已有字幕。
4. 在终端按 `Ctrl+C` 关闭服务。下次启动可重开已保存项目。

本机运行环境及外部工具安装记录见 [Mac 安装说明](docs/mac-setup.md)。如果已安装依赖，命令行也可以执行：

```sh
.venv/bin/python scripts/launch.py
```

工程演示可导入 `examples/timing-check.srt` 与 `examples/timing-check.mp4`。它们是合成的字符、时间与播放测试素材，**没有真实人声，不是翻译质量样片**。

## 无字幕与机翻字幕

工作台已增加本地 Whisper 转写：不需要 API 密钥、不上传素材，任务在本机依次执行，支持取消和进度查看。每次完成创建一个独立项目，字幕全部标为“待复核”，不改写现有项目。原音语言可选择自动、泰语或英语；泰英混说、专名、静音误识别和时间同步仍须听音检查。自动检测不保证逐句正确识别语言。

首次使用本地识别需额外安装引擎和模型。先安装 Apple Command Line Tools（终端运行 `xcode-select --install`，已安装可跳过），再在项目目录运行：

```sh
.venv/bin/python scripts/setup_asr.py
```

文件位于 `tools/asr/`。模型约 574 MB，首次还会下载固定版本的 whisper.cpp 源码和 CMake 并在本机编译；安装过程校验 SHA-256，需要网络和额外临时磁盘空间。应用运行时不自动下载模型。详细操作见 [无字幕素材处理](docs/no-subtitle-workflow.md)。

机器翻译的中文/英文保留作参考轨；从原音识别得到原语底稿后，再校对、翻译。平台字幕语言标签可能不准确，普通字幕也不保证人工制作，不能只按文件名判断原语。

转写进度中的百分比为引擎进度与准备阶段的近似显示，不是剩余时间。识别使用选定音轨，失败或取消不创建半成品项目；工作台中断后未完成任务需重新提交。成功项目保留媒体和原始识别结果，临时 WAV 与取消/失败任务的上传副本会清理，用户原文件保持不变。

## 审阅与保存

点击字幕定位视频。原文和简体中文分别编辑；时间使用媒体起点的整数毫秒。逐句播放与循环可设置前后余量。编辑器的保存状态以 API 成功为准；遇到冲突请保留当前草稿并重载，不能覆盖更晚的版本。

每句字幕使用稳定 UUID，显示序号只用于阅读。修改原文会保留中文并标记复核；改变时间会使同步审阅失效。拆分需要明确填写各段时间和文字，合并仅支持相邻条目。撤销检查整个事务的版本，有冲突时全部拒绝。

审阅、拆分、合并、导出、修订和候选保存在 `.workbench-data/`；原始导入字幕和媒体保留为独立文件。不要删除这个目录或用普通复制替代正在运行的 SQLite 备份。

## AI 翻译配置

本地审阅不需要 AI。第一版实现 OpenAI **Responses API**，使用支持 Structured Outputs 的模型；不预选模型，不预填密钥，也没有启用费用。其他地址须实现同一个 Responses API 协议，只有 Chat Completions 的兼容服务尚不适配。

将 `.env.example` 复制为 `.env`，在本机填写 `OPENAI_API_KEY`、`OPENAI_MODEL`。阅读费用边界后，将 `TRANSLATION_ALLOW_PAID=true`，重启工作台。密钥不通过浏览器设置、不进入项目包或普通日志。

每次翻译先预览要发送的选中句、前后最多两句和术语，再明确确认。每次最多 100 句，默认每批 8 句，默认最多输出 4,096 tokens。只有全部响应 ID 正确的一批才会提交；响应只产生候选，不直接改写原文、时间或人工中文。

候选采用时重新验证版本、原文、上下文和术语指纹。过期候选可以查看，但不能直接覆盖当前稿。术语版本与任务请求均可追溯。取消保留已完成批次；worker 中断会把未提交批次标为失败，需手动重试，每批最多 3 次调用。**网络中断后重试可能重复计费，token 限额不是金额预算；请在服务商后台设置费用上限。**

接口参考：[OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)。本次工程离线验证不代表真实 API、模型费用或泰英语言质量已经验收。

## 导出、备份与外部交接

支持原文、中文、双语 SRT / VTT。建议选择带清单的 ZIP：其中包含冻结版本、条目 ID 映射、媒体与字幕哈希、草稿状态。中文为空的句子不会生成空的中文 cue，清单会记录遗漏；未审字幕允许作为草稿导出。

项目包保留稳定 ID、修订、候选、术语和来源，不包含媒体。恢复后重新选择原媒体，SHA-256 一致才能绑定。完整数据库备份使用 SQLite backup API，包含 WAL 中已提交数据。恢复数据库的安全操作见 [验收及限制](docs/acceptance.md)。

外部修改过的字幕回导先预览差异。SRT 行号或时间相似不能证明身份，当前版本将其存为独立参考轨，不自动覆盖人工稿。高级 ASS 样式、剪辑和烧录交给外部软件；流程见 [配套工具计划](free-tools-subtitle-workflow-plan.md)。本地识别已接入工作台，也可导入外部工具的识别结果。

## 独立视频下载脚本

下载脚本可以单独使用，不要求启动工作台。需要 yt-dlp、FFmpeg / ffprobe、Python 3；建议安装 Deno 供 YouTube 解析使用。Homebrew 可运行 `brew install yt-dlp ffmpeg python deno`。

```sh
./youtube_download.command --check
./youtube_download.command 'https://www.youtube.com/watch?v=VIDEO_ID'
```

默认保存到 `~/Downloads/YouTube/` 下的各视频目录。先完成媒体，再逐轨下载独立字幕；默认跳过平台自动翻译，字幕 429 不会撤销已完成视频。代理、语言选择及来源清单详见 [下载器说明](docs/downloader.md)。请使用自己有权下载和处理的素材。

## 开发与检查

```sh
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests tests/test_downloader_manifest.py
cd frontend
npm run build
```

前端开发运行 `npm run dev`，Vite 将 `/api` 代理至 `127.0.0.1:8765`。API 数据契约见 [api-contract.md](docs/api-contract.md)，工程实测和未完成验收见 [acceptance.md](docs/acceptance.md)。
