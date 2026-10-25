> **已退役 · 2026-10-25**：本文保留旧 Studio 方案与当时记录，不再作为实施依据。旧文中的“必须”“唯一主计划”“下一步”均已失效。当前决策与任务以 [SE 主流程实施计划](../../../se-workflow-plan.md) 为准。仅允许为读取、备份、导出旧项目参考运行步骤；不要据此重新启动 Studio 开发。

# 没有字幕或只有机翻字幕时怎么处理

首选工作台内置的**本地语音识别**：选择视频或音频，生成原语字幕和独立审阅项目，再逐句听音校对。先按下文安装 whisper.cpp 1.9.5 与多语言 `large-v3-turbo-q5_0` 模型；识别使用 Apple Silicon 的 Metal GPU，不需要 API Key，不调用收费服务。中文 AI 翻译是另一个单独配置的步骤。

## 工作台操作

1. 双击项目中的 `start.command`，打开工作台。导入素材时选择 **从视频识别**，也可从侧栏进入 **本地语音识别**。
2. 选择最终用于审阅的视频或音频，确认显示“本地语音识别可用”。如有多条音轨，可填写音轨索引；留空采用第一条音轨。
3. 选择原音语言：泰英混说可先用 **自动检测**，泰语为主也可选 **泰语**做对照。识别保留原语，不执行“翻译成英语”。
4. 点击 **开始本地识别**。任务依次在本机运行，可继续审阅已有项目，也可以取消任务。
5. 完成后点击 **打开项目**。生成的是待审机器草稿；先检查时间同步、漏句、人名和数字，再翻译、修订和导出。任务完成不会自动切换或覆盖当前编辑。

先识别一段有代表性的短样本，确认语言和音轨正确，再处理整片。片段字幕从片段的零点开始，不能直接套用到完整视频；整片项目应直接选择同一份完整媒体。

## 已有字幕如何取舍

| 视频现状 | 建议路径 |
|---|---|
| 有原语字幕或自动识别字幕 | 保留原文件，抽查同步和错字；能用就直接导入，不必重跑整片 |
| 只有机翻中文或英文 | 保留为参考；优先寻找原语轨，缺失或错漏较多时从声音重识别 |
| 完全无字幕 | 固定媒体版本 → 本地识别 → 原语草稿 → 听音校对与翻译 |
| 字幕印在画面里 | 当前工作台不做 OCR；仍可从音频识别，画面字幕用于人工对照 |

英文字幕可作为中间语参考，但不能标作已经核验的泰语逐字稿。导入原语项目后，可通过“外部字幕回导”加入独立参考轨。平台普通字幕、自动字幕、自动翻译与“人工已核验”是不同概念；语言代码和文件名不能单独证明字幕语言或质量。

## 泰语与英语混说

多语言模型支持泰语、英语，但自动语言检测不能保证每次语言切换都准确。选择包含泰语、英语、人名、数字和背景音乐的片段，重点听查漏词、否定句、错人名和被错误转换的英语。自动检测与指定泰语的结果可以另建项目对照，不要覆盖人工稿。[Whisper 官方语言列表](https://github.com/openai/whisper/blob/main/whisper/tokenizer.py)、[模型与语言说明](https://github.com/openai/whisper#available-models-and-languages)

一句听不清时保留疑点，不要把错误原文反复翻译成流畅中文来“修好”听写。英语较集中的区间可另行识别并人工核对；切片结果必须换算回绑定媒体的时间轴。

## 安装与本机验证记录

- 引擎：`tools/asr/bin/whisper-cli`，whisper.cpp **1.9.5**，官方发行源码固定提交，arm64 Release 静态构建，内嵌 Metal 库；运行时仅依赖 macOS 系统库和框架。
- 模型：`tools/asr/models/ggml-large-v3-turbo-q5_0.bin`，**574,041,195 字节**，约 547.4 MiB；固定 Hugging Face 仓库版本，并按官方 LFS SHA-256 完整校验。
- 验证环境实测：一段 30 秒泰语音频成功生成 **17 条原语字幕**；自动检测 `th`，`translate=false`，Metal 实际使用 Apple M4，含首次初始化总耗时约 **16 秒**。这是流程验证，尚未逐句人工核验准确率；测试音频和识别内容不随仓库发布。
- 安装脚本在 `tools/asr/manifest.json` 记录来源、版本与哈希。JSON `transcription[].offsets`、CLI `--offset-t` 与 `--duration` 单位均为毫秒；JSON `result.language` 是检测结果，`params.language` 保留请求值。

需在另一台 Apple Silicon Mac 补装或恢复时，在项目目录运行：

```sh
.venv/bin/python scripts/setup_asr.py
```

脚本下载固定版本的源码、官方便携 CMake 和多语言模型，支持分段续传；完整哈希通过后才采用文件。需已有 Apple Command Line Tools。`--rebuild` 可重新编译；已存在且校验通过的文件会复用。脚本只安装，绝不会自行转写用户媒体。常规双击 `start.command` 运行即可；受限自动化沙箱可能无法分配 Metal GPU 缓冲区，本机普通用户进程已验证通过。

技术依据：[whisper.cpp v1.9.5 官方发行](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.5)、[固定版本 CLI 实现](https://github.com/ggml-org/whisper.cpp/blob/v1.9.5/examples/cli/cli.cpp)、[固定版本模型与 LFS 元数据](https://huggingface.co/api/models/ggerganov/whisper.cpp/revision/5359861c739e955e79d9a303bcbc70fb988958b1?blobs=true)。

## 备用：Subtitle Edit

安装 Subtitle Edit 5.3.0 后，也可通过 **Video → Speech to text… → Whisper CPP** 生成原语字幕。其独立引擎和模型管理尚未在验证环境配置验收；工作台内置引擎可用并不表示 Subtitle Edit 已自动接入它。按应用提示配置多语言模型，关闭 **Translate to English**，另存 UTF-8 SRT 后在工作台选择“已有字幕”，来源记为“外部语音识别”。应用安装、签名及架构检查见 [Mac 安装记录](mac-setup.md)。[Subtitle Edit 官方语音识别文档](https://github.com/SubtitleEdit/subtitleedit/blob/v5.3.0/docs/features/speech-to-text.md)

## 完整素材流程验证

另一次约 12 分钟的 VP9 / Opus 视频验证，在 Apple M4 上约 113 秒完成转写并创建 257 条待复核原语字幕，另存 217 条英文参考字幕；原媒体未改动。视频、字幕和项目数据不随仓库发布，这些耗时不构成所有素材的性能承诺。

该案例也发现，平台标记为 `th` 的字幕内容实际为英语，而 `th-orig` 才是泰语自动识别结果。因此应将来源标签、实际内容语言和人工核验状态分别记录。开场音乐附近的句首时间、混说和专名仍需听音修订；模型结果不是发布成品。
