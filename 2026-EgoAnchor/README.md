EgoAnchor 中文论文工程
======================

最新中文工作稿为 `egoanchor_cn_final_v3.tex`，使用 IEEE VR / VGTC 模板和 XeLaTeX 编译。
该稿第 3 章已锁定，图表任务不得回退或覆盖该章。`egoanchor_cn_final_v1.tex` 与
`egoanchor_cn_final_v2.tex` 作为旧稿保留。

目录
----

- `egoanchor_cn_final_v3.tex`：当前中文工作稿。
- `egoanchor_cn_refs.bib`：主稿参考文献。
- `Makefile`：编译入口，所有中间产物统一写入 `pdf/`。
- `figures/`：系统图、定性 replay、正文组合图和独立审计子图。
- `tables/`：由统一 `copy-assets` 命令按 TOML 显式复制的 LaTeX 表。
- `pdf/egoanchor_cn_final_v3.pdf`：与工作稿同名的编译结果，供内部审阅和 VSCode/LaTeX Workshop 打开。
- `reference/`：外部评审意见与参考稿，只读引用，不参与主稿编译。
- `docs/约束.md`：写作约束清单。
- `docs/design.md`：系统与实验设计说明。
- `docs/experiment_1_2_collection_manual_zh.md`：正式采集手册。
- `docs/experiment_1_2_analysis_reproduction_manual_zh.md`：实验一/二复现手册。
- `docs/experiment_3_questionnaire_design_zh.md`：实验三问卷设计。

编译
----

在本目录运行：

    make

等价于 `latexmk -xelatex -synctex=1 -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_final_v3.tex`。
PDF、XDV、AUX 与日志都使用 `egoanchor_cn_final_v3` 这一 basename，统一写入 `pdf/`，源目录不留产物。
latexmk 自行处理 bibtex 与重跑依赖，无需手动调用 bibtex。工作区的 LaTeX Workshop 输出目录也配置为
`%DIR%/pdf`，可以按源文件名定位 PDF。`make clean` 只清理辅助文件并保留最终 PDF；
`make distclean` 会同时删除最终 PDF。编译其他稿件用 `make MAIN=egoanchor_cn_final_v2`。

编译 `reference/` 下的参考稿用：

    make ref FILE=reference/gpt-web/某个稿件.tex

该目标在原位编译，产物写入参考稿所在目录的 `pdf/`。工作目录仍是本目录，因此参考稿里的
`\input{tables/...}` 与 `\includegraphics{figures/...}` 照常解析，不要把参考稿复制到本目录根下。

分析与图片
----------

实验一/二分析由 `EgoAnchor_Python` 下的 `pixi run eval analyze exp1-2` 生成两张组合图、八个独立审计子图
及其 PNG/PDF，并生成四张 TeX 表。`pixi run eval copy-assets exp1-2` 按 `batch.toml` 复制这些资源，
不会修改主稿。正文直接引用组合 PDF，独立子图不进入论文。

实验一和实验二的组合图均为原生 `1 x 4` 布局。实验一各面板使用单个线性纵轴；动态结果把
effective lag、lag-aligned RMSE、current-time RMSE 和 residual jitter 分开解释。实验二 Figure 3(d)
只展示 Smoothed KF Extrapolation 与 Linear/SLERP，Hermite 仅保留在审计数据中。

实验三直接运行 `pixi run eval analyze exp3`，不要求先运行联合审计门禁；`validate exp3` 只是可选诊断。
唯一分析源为 `material/EgoAnchor_Experiment3_RawData_Template_v5_3.xlsx`（v5.3，24 人）。区块评分顺序固定为
`Q1–Q7 → AQ_EQ1–3 → AQ_IQ1–3`，Q10 已删除；当前工作簿使用 AQ-EQ2、TiA-RC1/RC4/UP1
的情境化措辞和互斥 B5 累计次数选项。
