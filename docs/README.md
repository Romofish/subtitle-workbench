# 项目文档索引

2026-10-25 起采用 Subtitle Edit 主流程，Studio 停止开发。

| 状态 | 文档 | 用途 |
|---|---|---|
| 唯一有效计划 | [se-workflow-plan.md](se-workflow-plan.md) | 决策、插件调查、P0–P6 实施、两机同步、已知状态与新对话提示词 |
| 有效说明 | [downloader.md](downloader.md) | 独立下载核心与入口、Windows 验证及 Mac 实机待验 |
| 有效平台交接 | [windows-setup.md](windows-setup.md) | Windows 安装快照、SE 待验与路径 |
| 有效平台交接 | [mac-setup.md](mac-setup.md) | Mac 历史安装事实、同步要求与待验 |
| 历史资料 | [退役文档索引](retired/README.md) | 原开发计划、Studio 运行手册、API、验收与安装记录 |

根目录旧开发计划以及旧 `acceptance.md`、`api-contract.md`、`no-subtitle-workflow.md` 只保留退役跳转。新对话先读当前计划，不从历史清单恢复开发。

Windows P0 已完成两测试项目的备份、实际恢复、媒体重新关联和 SE 字幕打开检查，旧 Studio 已正常停机；P1 下载入口独立化与 Windows 验证已完成。P2 已实测播放、波形、中泰字形、逐句回放、Whisper CPP/cuBLAS 泰语运行、ASS/中文书签保存重开与只读英文参考双栏；Actor 测试标签保存及自动备份实际恢复机制通过，真实说话人身份未验。

P3 的基线及唯一 VAD 替代设置已比较，语义未验且存在待核对区间，不能记为识别质量通过。P4 复制粘贴翻译的预览、采用、撤销重做和重开已通过；P5 已生成并检查三条中文的 AAC 短样片，记录并解决音频 copy 前滚问题。上下文/局部重译、泰语审阅和整片交付仍未完成；Mac 本轮未连接，本机 P0–P6 待执行。工程检查通过不代表语言或成片审定，已完成/未完成均以计划中的执行记录与平台证据为准。

本地证据位于 `output/se-handoff/20261025-212630-P0/` 和 `output/se-validation/`，后者包含 `asr-comparison.json`、`se-ui-validation.json`、补充恢复记录 `p2-persistence-validation.json`、`clip-review.ass` 及其 `.SE.bookmarks` 旁文件。自动字幕备份不包含书签旁文件，须另行成套保全；这些资料不随普通 Git 同步。本轮没有卸载软件、删除资料、提交或推送代码。

P6 的 Windows 日常快捷入口已建于桌面和开始菜单 `Subtitle Workflow` 组，指向 SE 与独立下载器；旧入口保留。目标与既有快捷方式保全验证见 `output/se-validation/p6-shortcuts-validation.json`。Mac 入口和后续正常制作流程仍待本机实践。
