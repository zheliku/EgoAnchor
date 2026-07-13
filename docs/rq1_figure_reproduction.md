# RQ1 静态锚定图复现手册

> 目标：让你**独立**把 `figs/rq1/fig_rq1_static.{png,pdf}` 重新生成出来，
> 并搞清楚每一步在做什么、为什么这么做。
> 适用于换新 session、换时间窗、或图坏了要重画的所有场景。

---

## 0. 一句话速查（懒人版）

在 `EgoAnchor_Python/` 目录下跑这一条，图就原地更新：

```bash
KMP_DUPLICATE_LIB_OK=TRUE pixi run python -m egoanchor.eval.research.rq1.plot_from_report \
    --report-dir data/eval/20260707_141751_controller_right/report
```

然后编译论文：

```bash
cd P:/VSCode-Project/EgoAnchor/2026-EgoAnchor
latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_v5.tex
```

换 session 只改 `--report-dir` 的路径。下面是完整原理与排错。

---

## 1. 数据从哪来：三层日志 → CSV → 图

一次采集（session）落盘三份原始 JSONL，在
`EgoAnchor_Python/data/eval/<session_id>/`：

| 文件 | 内容 |
|---|---|
| `*_unity_capture.jsonl` | Unity 每帧采集（图像帧、frame_id、时间戳） |
| `*_unity_output.jsonl` | Unity 每个渲染 tick 的**锚点输出 + 同刻控制器真值(GT)**，每个变体一行 |
| `*_python_runtime.jsonl` | Python 感知管线每帧的 pose_result |

**分析链路**（`egoanchor.eval.research.rq1.analyze`）把这三份日志读进来，
按 `condition × label` 算出全部指标，写到
`data/eval/<session_id>/report/` 下的一堆 CSV。

**画 RQ1 图只用其中一张**：`report/anchor_error_detail.csv`——逐帧的锚点误差长表。
关键列：

| 列 | 含义 |
|---|---|
| `render_mono_ms` | Unity 渲染时刻单调毫秒（图的横轴用它） |
| `condition` | 场景：`static_observation` / `occlusion_recovery` |
| `label` | 变体：`Full`（完整系统）/ `No-StaticLock`（去掉静止锁） |
| `translation_error_m` | 平移误差（米，图里 ×1000 变毫米） |
| `rotation_error_deg` | 旋转误差（度） |

> **误差口径（重要）**：误差 = 同一行里锚点输出 `output_pos/rot` 与
> 同刻控制器真值 `gt_pos/rot` 的 SE(3) 偏差。GT 与锚点是 Unity 在同一帧
> (`LateUpdate`) 采样、写在同一行、共享同一个 `render_mono_ms`。
> **没有任何时间平移 / 回溯对齐 / 插值**——这是"实时逐帧对比"。
> 所以图上 Full（蓝）相对 No-StaticLock（橙）的"相位滞后"是 Full 平滑管线
> 的真实群延迟，不是分析假象；正因为没做补偿对齐，才能看见这个滞后。

---

## 2. 为什么要单独一个绘图脚本（而不是直接跑 analyze）

完整分析链路 `analyze.py` 会 `import` 整个 metrics 引擎，而它间接
`import cv2`（`egoanchor.utils.image`）。这台机器上 opencv 安装是坏的
（`cv2` 目录空），一 import 就报 `ModuleNotFoundError: No module named 'cv2'`。

但**画图根本不需要重算指标、也不需要 cv2**——只要读那张已经算好的
`anchor_error_detail.csv`。所以代码里把绘图逻辑拆成了两块：

```
src/egoanchor/eval/research/rq1/
├── plot.py              ← 纯绘图函数 write_rq1_figure（只依赖 matplotlib/pandas/numpy）
├── plot_from_report.py  ← 轻量入口：读 CSV → 调 plot.py（不碰 cv2）
└── analyze.py           ← 完整分析链路（要 cv2，负责从原始日志算 CSV）
```

- 已经有 `report/*.csv` → 用 **`plot_from_report`**（快、无需 cv2）。
- 全新 session、还没算过指标 → 得先跑 `analyze`（需要修好 cv2）。

本手册聚焦第一种（你的 141751 已经有 CSV 了）。

---

## 3. 完整步骤

### 步骤 1：确认 CSV 存在

```bash
ls data/eval/20260707_141751_controller_right/report/anchor_error_detail.csv
```

有这个文件就能画图。没有的话见第 5 节。

### 步骤 2：跑绘图脚本

在 `EgoAnchor_Python/` 目录下：

```bash
KMP_DUPLICATE_LIB_OK=TRUE pixi run python -m egoanchor.eval.research.rq1.plot_from_report \
    --report-dir data/eval/20260707_141751_controller_right/report
```

逐段拆解：

| 片段 | 作用 |
|---|---|
| `KMP_DUPLICATE_LIB_OK=TRUE` | 绕开这台机器 libomp/libiomp5md 冲突崩溃（老坑） |
| `pixi run python` | 用 pixi 环境的 Python（有 pandas/matplotlib） |
| `-m ...plot_from_report` | 跑绘图入口模块 |
| `--report-dir <路径>` | 指向 report 目录。**换 session 只改这里** |

成功会打印：

```
wrote P:\...\2026-EgoAnchor\figs\rq1\fig_rq1_static.pdf
wrote P:\...\2026-EgoAnchor\figs\rq1\fig_rq1_static.png
```

图默认写到 `2026-EgoAnchor/figs/rq1/fig_rq1_static.{png,pdf}`，
**原地覆盖**旧图。想换输出位置加 `--figs-dir <目录>`。

### 步骤 3：LaTeX 里放图（已配好，讲原理）

`egoanchor_cn_v5.tex` 里用 `figure*` + `includegraphics` 引用：

```latex
\begin{figure*}[t]
  \centering
  \includegraphics[width=\textwidth]{figs/rq1/fig_rq1_static.png}
  \caption{...}
  \label{fig:rq1-static}
\end{figure*}
```

因为文件名和路径不变，重跑步骤 2 后图片会原地覆盖，LaTeX 引用不用修改。

### 步骤 4：编译论文

```bash
cd P:/VSCode-Project/EgoAnchor/2026-EgoAnchor
latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_v5.tex
```

`--root .` 让 `#image` 的相对路径从仓库根解析。字体 warning（helvetica /
liberation sans）可忽略，exit 0 即成功。

---

## 4. 两个旋钮

### 4.1 完整序列 vs 稳态窗口

- **默认 = 完整序列**（不取最优区间），正是论文当前口径。
- 临时只看某段：加 `--static-window 50 75`（相对该场景起点的秒数）。
  只影响 static 列；遮挡列永远画完整（它的尖峰正是要展示的缺陷）。
- 想永久改默认：`plot.py` 顶部 `STATIC_STEADY_WINDOW_S`
  （`None` = 完整；`(50.0, 75.0)` = 旧稳态窗口）。
  **改了要图文同步**：正文数字也得跟着窗口重算。

### 4.2 换 session

只改 `--report-dir` 的路径。前提是那个 session 的
`report/anchor_error_detail.csv` 已生成。

---

## 5. 如果是全新 session（还没有 CSV）

需要先跑完整分析算出 CSV，但这一步要 cv2：

```bash
KMP_DUPLICATE_LIB_OK=TRUE pixi run python -m egoanchor.eval.research.rq1.analyze \
    --session-dir data/eval/<新session_id>
```

它会同时写 `report/*.csv` 和图。若报 `No module named 'cv2'`，
先修 opencv：

```bash
pixi run python -c "import cv2; print(cv2.__version__)"   # 验证
# 坏的话重装：
pixi run pip install --force-reinstall opencv-python
```

CSV 一旦生成，之后重画图就回到第 3 节的轻量路径，不再需要 cv2。

---

## 6. 正文数字从哪核对

图和正文必须同源。正文里的中位数/P95/倍数都来自 report 里的汇总 CSV：

| 正文指标 | 来源 CSV |
|---|---|
| 平移/旋转 中位数·P95 | `anchor_error_summary.csv` |
| 位置/旋转 1 Hz 高通 RMS | `jitter_summary.csv` |
| 生命周期状态占比 | 从 `anchor_error_detail.csv` 的 `anchor_state` 列按 occlusion 段统计 |

`slip_summary.csv` 仍会生成固定针孔模型下的像素等效像面代理，但它不是真实头显面板误差，当前不进入论文主表。改了 session 或窗口后，务必打开上述 CSV 重新核对正文里的每个数字。

---

## 7. 验证（改完怎么自检）

```bash
# 绘图与抖动逻辑单元测试
KMP_DUPLICATE_LIB_OK=TRUE pixi run python -m unittest egoanchor.eval.tests.test_rq1_plot egoanchor.eval.tests.test_jitter -v

# 论文能否编过
cd ../2026-EgoAnchor
latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_v6.tex
```

两个都过 = 图和论文都健康。

---

## 附：当前基线（2026-07-13）

- 使用 session：`20260707_141751_controller_right`，共 10,108 个 Unity 渲染帧；静止/遮挡分别纳入 4,306 / 4,374 个有效帧
- 口径：正文统计使用完整序列；局部 XYZ-t 图固定取首个连续 180 帧锁定窗口（550–729，2.99 s），选窗不读取误差
- 静止 Full：平移中位 5.8mm / P95 6.6mm，旋转中位 2.1° / P95 2.9°
- 连续静止段 HP-RMS（位置 / 旋转）：Full 0.02mm / 0.02°，No-StaticLock 0.71mm / 0.69°
- 遮挡 No-StaticLock：平移 P95 19.3mm、旋转 P95 17.2°
- 生命周期（Full）：Coasting 48% / Searching 32% / FrozenUncertain 15% / Lost 5%
- 当前标注没有独立的目标重新可见 marker，不报告遮挡恢复时间
