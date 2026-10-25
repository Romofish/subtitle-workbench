# 已退役的 Studio 文档

退役日期：2026-10-25。当前执行依据是 [SE 主流程实施计划](../se-workflow-plan.md)。

这些文件保留决策历史、旧项目取回方法和当时的证据；不再作为开发路线或必须完成的验收清单。停止 Studio 开发不要求删除源码、数据库和个人素材。

| 原位置 | 历史快照 | 当前处理 |
|---|---|---|
| 根 README | [旧运行手册](studio-2026-10-25/README.md) | 根 README 改为 SE 主流程入口 |
| multilingual-subtitle-tool-development-spec.md | [旧开发计划](studio-2026-10-25/multilingual-subtitle-tool-development-spec.md) | 原路径仅提示退役 |
| free-tools-subtitle-workflow-plan.md | [旧工具分工](studio-2026-10-25/free-tools-subtitle-workflow-plan.md) | 原路径仅提示退役，SE 不再是备选 |
| docs/acceptance.md | [历史工程验收](studio-2026-10-25/docs/acceptance.md) | 原路径仅提示退役；不追补旧清单 |
| docs/api-contract.md | [旧 API 契约](studio-2026-10-25/docs/api-contract.md) | 原路径仅提示退役；不据此扩展接口 |
| docs/no-subtitle-workflow.md | [旧内置识别流程](studio-2026-10-25/docs/no-subtitle-workflow.md) | 原路径仅提示退役 |
| docs/mac-setup.md | [Mac 旧安装记录](studio-2026-10-25/docs/mac-setup.md) | 当前路径改为 SE 交接说明 |
| docs/windows-setup.md | [Windows 旧安装记录](studio-2026-10-25/docs/windows-setup.md) | 当前路径改为 SE 交接说明 |
| docs/benchmark-results.json | [旧合成性能结果](studio-2026-10-25/docs/benchmark-results.json) | 仅作为历史工程证据保留 |

[快照清单](studio-2026-10-25/snapshot-manifest.json)记录退役前工作文件与存档文件的 SHA-256。Markdown 仅追加退役提示、修正搬移后的相对链接；性能 JSON 按字节保留。快照包含尚未提交的文档状态，不代表某个正式发行版。

退役目录使用 `docs/retired/` 而不是本仓库被忽略的 `docs/archive/`，以便纳入 Windows / Mac 源码同步。不要把旧文档里的运行命令、相对运行目录或本机路径当成新流程指令；取回旧项目时回到仓库根目录并核对当前代码。
