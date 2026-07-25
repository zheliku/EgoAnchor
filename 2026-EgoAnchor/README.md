EgoAnchor 中文论文工程
======================

最新中文工作稿为 `egoanchor_cn_ai_v8.tex`，使用 IEEE VR / VGTC 模板和 XeLaTeX 编译。
文件名中的 `ai` 表示该版本使用 AI 辅助撰写；该稿目前尚不可用，只供继续修改和内部审阅。
`egoanchor_cn_v6.tex`、`egoanchor_cn_v7.tex` 与 `egoanchor_cn_v8.tex` 作为旧稿保留。

目录
----

- `egoanchor_cn_ai_v8.tex`：最新中文工作稿，目前尚不可用。
- `egoanchor_cn_refs.bib`：主稿参考文献。
- `figures/`：系统图、定性 replay 和论文分析发布的独立面板。
- `tables/`：由 `copy-assets` 按 TOML 显式发布的三张 LaTeX 表。
- `pdf/egoanchor_cn_ai_v8.pdf`：与工作稿同名的编译结果，供内部审阅和 VSCode/LaTeX Workshop 打开。
- `plan.md`：当前论文路线和实验边界。
- `experiment_1_2_collection_manual_zh.md`：正式采集手册。
- `experiment_1_2_analysis_reproduction_manual_zh.md`：实验一/二复现手册。

编译
----

在本目录运行：

    latexmk -xelatex -synctex=1 -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_ai_v8.tex

也可运行 `make`。PDF、XDV、AUX 与日志都使用 `egoanchor_cn_ai_v8` 这一 basename，
统一写入 `pdf/`。工作区的 LaTeX Workshop 输出目录也配置为 `%DIR%/pdf`，可以按源文件名定位 PDF。
`make clean` 只清理辅助文件并保留最终 PDF；`make distclean` 会同时删除最终 PDF。

分析与图片
----------

论文分析由 `EgoAnchor_Python` 下的 `pixi run eval analyze` 生成八个独立 PNG/PDF 面板、
三张表和两个 figure 环境片段。`pixi run eval copy-assets` 按 `batch.toml` 发布图片和三张表格 TeX，
不会修改主稿；figure 环境片段仍由研究者审阅后手工纳入。

实验一四个面板由 LaTeX subfigure 排成一行；动态结果把 effective lag、lag-aligned RMSE、
current-time RMSE 和 residual jitter 分开解释。实验二四个面板使用等高固定画布，图 4(d)
显示全部时序策略片段，不设置隐藏数据的固定阈值。
