# 下载脚本与字幕来源记录

更新：2026-10-23。适用于 [youtube_download.command](../youtube_download.command)。媒体下载与可选字幕下载现已分开；本地工作台及无字幕转写入口见 [运行说明](../README.md)。

## 429 故障与处理依据

实际故障案例在 `zh-Hans-th` 自动翻译字幕请求上收到 HTTP 429，旧脚本在下载媒体前处理字幕，因此中途报错连带阻断视频。`th.*,zh.*,en.*` 选中九条字幕，包含多条平台自动翻译。yt-dlp 维护者已记录自动翻译字幕的 429 问题；不能仅据此断定是代理故障、下载速度过快或版本过旧，也不能保证增加延时就解决。[官方问题记录](https://github.com/yt-dlp/yt-dlp/issues/13831)

该案例随后“不下载字幕”的重试成功。此前三个成功的 VTT 留在失败运行的 `.yt-dlp-work/` 中；旧记录的 `not_saved_or_not_confirmed` 表示缺少完成阶段证据，不表示已下载的文件消失。

内容检查又发现：`th` 和 `th-th` 内容相同，实际是英文，不能当作泰语原文；`th-orig` 是泰文平台自动识别稿。原 VTT 被保留，另转换为参考 SRT 并记录哈希；恢复不代表已经完成翻译、语义校对或累计文本去重。案例媒体、恢复字幕与个人来源记录不随仓库发布。

## 当前行为

1. 先下载视频/音频并确认完成路径，媒体阶段禁用字幕写入和嵌入。
2. 随后逐轨下载独立字幕并转换 SRT，每条都有独立完成证据。某条失败不会撤销已完成媒体与字幕。
3. 遇到 429 立即停止本轮剩余字幕请求，记录未尝试轨；不连续高频重试。
4. 默认跳过有 `tlang` 证据的自动翻译和未经确认的自动轨。平台普通字幕和资源不同的 `-orig` ASR 轨都保留；只按同一字幕资源去重，不能因为语言代码相似就丢掉另一来源。
5. 字幕只作为独立 SRT 保存，本次不再新增内嵌轨；已有媒体的内嵌轨仍由 ffprobe 如实记录。工作台可直接导入独立文件。

“平台普通字幕”不保证人工制作、官方、准确或原语。语言代码也不证明实际内容语言，需要听音与文本核对。

## 使用方式

需要 yt-dlp、FFmpeg / ffprobe、Python 3；建议安装 Deno 供 YouTube 解析使用。已有 Homebrew 时可运行 `brew install yt-dlp ffmpeg python deno`。本脚本独立运行，不依赖工作台的 Python 虚拟环境或前端。

```bash
./youtube_download.command --check
./youtube_download.command --simulate 'https://www.youtube.com/watch?v=VIDEO_ID'
./youtube_download.command 'https://www.youtube.com/watch?v=VIDEO_ID'
```

默认保存到 `~/Downloads/YouTube/视频标题 [视频ID]/`，每个视频独立文件夹，语言筛选仍为 `th.*,zh.*,en.*`，但默认在元数据层排除自动翻译。`--simulate` 只解析，不创建媒体、字幕或来源记录，不表示真实下载已通过。

```bash
# 只考虑泰语，仍保留平台普通字幕与不同资源的原语 ASR
SUB_LANGS='th.*' ./youtube_download.command '视频链接'
# 明确要求平台自动翻译（仍可能遇到平台 429）
ALLOW_TRANSLATED_SUBS=yes SUB_LANGS='th.*,zh.*,en.*' ./youtube_download.command '视频链接'
DOWNLOAD_SUBS=no ./youtube_download.command '视频链接'
YOUTUBE_DOWNLOAD_DIR='/绝对路径/下载目录' ./youtube_download.command '视频链接'
PROXY_URL='http://127.0.0.1:7897' ./youtube_download.command '视频链接'
```

默认不显式指定代理；环境与 yt-dlp 配置仍可能影响网络。需要代理时通过 `PROXY_URL` 指定自己的地址，上例端口仅为示例。脚本不会读取浏览器 Cookie 或修改系统代理。

## 文件和完成语义

```text
YouTube/
└── 视频标题 [视频ID]/
    ├── 视频标题 [视频ID].mkv
    ├── 视频标题 [视频ID].20261023T000000Z-abc123.th.srt
    ├── 视频标题 [视频ID].sources.json
    ├── 视频标题 [视频ID].sources.failed.json
    └── sources-history/视频ID.20261023T000000Z-abc123.json
```

字幕和来源记录使用实际视频所在目录，确保特殊字符经过 yt-dlp 处理后仍放在一起。旧版平铺文件不会自动迁移。相同标题和 ID 重复下载复用同一目录；标题改变会生成新目录。

媒体文件名稳定；每次字幕带独立 run ID，保护旧字幕及人工修改。媒体实际扩展名以取得的流为准；需要合并时使用 MKV。元数据处理可能更新媒体元数据，需固定审阅素材时另存归档副本。

清单 schema_version=2：`download` 表示媒体阶段结果；`subtitles` 单独记录成功数量、尝试数量、429、逐轨状态及策略排除。媒体成功但字幕不齐时返回码为 0，并明确报告字幕缺口；媒体或来源记录失败仍返回非 0。不能仅靠返回码判断字幕齐备。

`.sources.json` 是最近媒体完成记录；`.sources.failed.json` 保存媒体未完成记录，不覆盖成功记录。每轮另存 `sources-history`，旧失败记录不会在成功重试后自动删除，以时间与 run ID 区分。

| 来源类别 | 含义 |
|---|---|
| `platform_subtitles` | 在平台普通字幕集合中匹配；不保证原语或人工制作 |
| `platform_automatic_asr` | 自动集合匹配且含 `kind=asr` 等明确证据 |
| `platform_automatic_translation` | 所选字幕有 `tlang` 自动翻译证据 |
| `unknown` | 元数据不足，不根据文件名猜测 |

清单只保存公开页面和白名单语言/类型证据，不保存签名下载 URL、Cookie、请求头。完整临时元数据退出时清理。已下载字幕仅依据本轮独立完成快照和实际非空文件确认，不扫描旧文件猜测成功。

字幕阶段复用媒体阶段取得的地址。长视频下载后签名字幕地址可能过期，此时如实报错，不自动刷新或无限重试。媒体未完成的分片保留在 `.yt-dlp-work/<run_id>/`；新运行不会自动续传旧 run 分片，已完成媒体可以复用。脚本不删除这些遗留文件。

## 验证

Bash 语法、依赖检查、来源/部分失败单测与真实 yt-dlp + FFmpeg 离线集成已执行。真实工具集成包含本地 HTTP 429 场景：媒体先完成、首条字幕保留、失败请求不重复、之后的轨未请求。新脚本未重复请求 YouTube 验证平台是否解除限制。

```bash
python3 -m unittest discover -s tests -p 'test_downloader_manifest.py' -v
python3 tests/integration_downloader.py
```

历史桌面脚本备份保留在验证环境，不随仓库发布。独立 SRT 的格式转换不等于通过工作台语义与时间校验；例如平台滚动 ASR 可能含空白 cue、重复文本或逐词标记，仍需清理和复核。

实现依据：[yt-dlp 字幕选项](https://github.com/yt-dlp/yt-dlp#subtitle-options)、[ffprobe](https://ffmpeg.org/ffprobe.html)。
