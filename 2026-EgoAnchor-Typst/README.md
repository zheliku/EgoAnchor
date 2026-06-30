# EgoAnchor Typst 论文工作区

本目录是 EgoAnchor 论文的 Typst 工作区，使用 `@preview/ieee-vgtc:0.0.4`。当前投稿目标是 IEEE VR 会议，主稿入口采用 `conference` 版式。

## 文件分工

- `egoanchor_cn_v2.typ`：当前中文主稿，正文与元信息都在这一份文件内，使用 IEEE VR conference 版式。
- `egoanchor_cn_v1.typ`：上一版中文 Typst 草稿，保留作对照。
- `egoanchor_cn.bib`：当前主稿对应的参考文献文件；当前暂不放条目，正文引用后集中补齐。
- `egoanchor_code_derived_technical_flow.md`：按代码事实整理的技术流程与术语依据，方法章实现细节优先以该文档和源码为准。
- `journal.typ`：`@preview/ieee-vgtc:0.0.4` 的 journal/TVCG 原始示例模板，保留作模板参考。
- `conference.typ`：`@preview/ieee-vgtc:0.0.4` 的 VGTC conference 原始示例模板，保留作模板参考。
- `refs.bib`：VGTC 示例模板自带参考文献，只供 `journal.typ` 和 `conference.typ` 示例使用。

## 编译命令

在仓库根目录运行：

```powershell
New-Item -ItemType Directory -Force .\2026-EgoAnchor-Typst\pdf
typst compile --root . .\2026-EgoAnchor-Typst\egoanchor_cn_v1.typ .\2026-EgoAnchor-Typst\pdf\egoanchor_cn_v1.pdf
typst compile --root . .\2026-EgoAnchor-Typst\egoanchor_cn_v2.typ .\2026-EgoAnchor-Typst\pdf\egoanchor_cn_v2.pdf
typst compile --root . .\2026-EgoAnchor-Typst\conference.typ .\2026-EgoAnchor-Typst\pdf\conference.pdf
typst compile --root . .\2026-EgoAnchor-Typst\journal.typ .\2026-EgoAnchor-Typst\pdf\journal.pdf
```

若需要 PDF/UA 检查，可在本地 Typst 版本支持时追加 `--pdf-standard ua-1`。当前正文中的系统架构图使用本目录 `figs/pipeline.png`，后续正式投稿版需要补齐更具体的 `alt` 文本。
