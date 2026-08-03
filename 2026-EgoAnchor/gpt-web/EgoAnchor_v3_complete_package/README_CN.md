# EgoAnchor 中文稿 v3：完整文件包

本文件包包含当前排版美化稿、最终图片、绘图代码、实验数据、原始表格、历史版本和两篇参考论文。

## 目录

- `manuscript/`
  - `EgoAnchor_cn_v3_polished.tex`：当前中文 LaTeX 主稿
  - `EgoAnchor_cn_v3_polished.pdf`：当前排版预览 PDF
- `figures/`
  - Teaser、系统 Pipeline、实验一、实验二、实验三的 PDF/PNG
  - `all_figures_montage.png`：全部图片总览
- `code/`
  - `make_polished_figures.py`：可移植绘图脚本，使用相对路径与 `openpyxl`
  - `make_polished_figures_original.py`：本次生成时使用的原始脚本，保留用于追溯
  - `requirements.txt`：Python 依赖
- `data/`
  - `figure_plot_data.xlsx`：实验一、实验二绘图数据
  - `experiment3_analysis.xlsx`：用户实验分析结果
  - `replay_grid_source.jpeg`、`replay_grid.pdf`、`replay_grid_metadata.json`：定性序列来源及元数据
- `tables/`
  - Fable5 v2 使用的四个原始 LaTeX 表格
- `previous_versions/`
  - v1、Fable5 v2、早期中文稿和英文初稿
- `reference_papers/`
  - SelfBlending
  - VRGaussianAvatar 双语参考稿
- `notes/`
  - 中文重构与审阅报告

## 重新生成图片

```bash
python -m pip install -r code/requirements.txt
python code/make_polished_figures.py
```

脚本会读取 `data/` 中的两个工作簿及定性序列源图，并覆盖生成 `figures/` 中的图。

## 编译论文

需要 XeLaTeX、IEEEtran、xeCJK、Noto CJK 字体及常用 LaTeX 宏包。

```bash
./build.sh
```

也可以手动执行：

```bash
cd manuscript
xelatex EgoAnchor_cn_v3_polished.tex
xelatex EgoAnchor_cn_v3_polished.tex
```

主稿中的 `graphicspath` 已设置为 `../figures/`。

## 颜色规范

- Arrival：`#4C78A8`
- Capture：`#F28E2B`
- One-Euro：`#59A14F`
- EgoAnchor：`#E15759`

全文方法颜色应保持一致。主文图优先使用矢量 PDF；PNG 用于快速预览或演示文稿。

## 数据与表述注意事项

- `0.82 mm` 是中心化静止平移泄漏/静止稳定性指标，不应写作整体追踪精度。
- 平台参考下绝对注册误差中位数为 `6.60 mm`。
- 参与者为女性 12 名、男性 12 名，年龄 `27.08 ± 4.45` 岁。
- 总体偏好为 EgoAnchor 15、One-Euro 4、无偏好 5；信任选择为 EgoAnchor 18、One-Euro 1、无偏好 5。
