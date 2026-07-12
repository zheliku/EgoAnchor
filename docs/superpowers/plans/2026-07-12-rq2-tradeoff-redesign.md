# RQ2 四轴权衡重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 RQ2 从"单一主终点判优"重构为"四轴权衡刻画"，新增运动平滑度指标（SPARC + jerk），并以实时轨迹图作为主图承载机制证据。

**Architecture:** 复用现有 `eval/research/rq2/` 纯计算管线与契约层。新增一个无副作用的 `smoothness.py` 计算模块（作用于 `display_pos/rot` 轨迹），在 `plot.py` 新增实时轨迹 hero 图函数，在 `pipeline.py` 挂接、`paper.py` 导出、`__init__.py` re-export，最后重写论文 §RQ2 与 AGENTS.md 记录。契约层、trajectory/source/lag/qc/model/paired 全部不动。

**Tech Stack:** Python 3.14 + numpy + pandas + scipy + matplotlib（Agg backend）；pixi 环境；Typst 论文；unittest。

## Global Constraints

- 单测运行必须设 `KMP_DUPLICATE_LIB_OK=TRUE`（libomp/libiomp5md 冲突），命令 `pixi run python -m unittest discover -s src -p "test_*.py" -t src`。
- Python 侧按包级入口导入：包内显式 re-export（`from .smoothness import ...`），包外 `from egoanchor.eval.research.rq2 import ...`；不深层导入。
- 代码需充分中文说明：类、成员、方法补中文 docstring。
- 命名清楚克制，不为"完整"写长名。
- 复用现有先导数据 `data/eval/rq2_data`（session_id `20260712_163657_controller_right`）；gitignore 保护，绝不删除或重采集。
- 单会话数据：全部图表保留 `_preliminary` 标识，不算置信区间，不写总体结论。
- 论文是 Typst（不是 LaTeX），路径 `2026-EgoAnchor-Typst/egoanchor_cn_v6.typ`；正文系统配置用规范术语斜体 *完整锚定* / *零阶保持（ZOH）*（不写 *Full* / *Raw-ZOH*），用"系统配置/变体"不用"条件"。
- 保留 `within_tolerance_valid_tracking_rate` 计算，仅降级定位（不删除，契约层依赖它）。
- SPARC 参数（截止频率、幅度阈值）在单测中固定，并在图注/正文说明取值来源。
- 每个任务结束提交（frequent commits）；不做旧接口/旧路径兼容。
- 生成文件 `generated/rq2_results.typ` 不手改，由 `paper.py` CLI 导出。
- **内部标签与论文术语解耦**：数据 manifest 的 `variant_labels=["Full","Raw-ZOH"]`、`config_hash`、所有代码内部标签一律不改（改了读不到先导数据）。术语映射只在正文与图注层做：
  - `Full` → 正文写 *完整锚定*（完整锚定策略）；不直接叫 EgoAnchor（ZOH 是剥离策略后的同一系统，二者都是 EgoAnchor 的系统配置）。
  - `Raw-ZOH` → 首次出现写 *零阶保持*（Zero-Order Hold, ZOH），此后写 *ZOH*。
  - `aligned raw` / `raw 误差` / `raw source` → 正文写 *时空对齐感知观测* / 感知观测误差 / 感知观测产出率；删除所有裸 "raw"。
  - Hero 图图例文字同样用规范术语（"完整锚定"/"ZOH"/"时空对齐感知观测"/"参考真值"），不写 "Full"/"Raw-ZOH"/"raw"。
- **"时空对齐"是唯一正式对齐术语**：正文不再单造"帧对齐"一词；需强调基于帧标识校正相机运动错配时，写"基于帧标识的时空对齐"。删除正文所有 `*Frame-aligned*` / `*Arrival-aligned*` 斜体标签（仅作诊断，不进主叙事）。
- **Baseline 语义**：Quest 手柄平台位姿是参考真值（标尺），不是第三个竞争系统。Hero 图 = 1 条真值线 + 2 条方法线（完整锚定 / ZOH）+ 稀疏时空对齐感知观测点；ZOH 阶梯线正是把观测点保持到下次更新得到的（同源）。

---

### Task 1: 新增 smoothness 计算模块（SPARC + jerk RMS）

**Files:**
- Create: `EgoAnchor_Python/src/egoanchor/eval/research/rq2/smoothness.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_rq2_smoothness.py`

**Interfaces:**
- Consumes: numpy、pandas；trial frame 表约定列 `render_mono_ms`、`display_pos`（list[float] 长度 3 或 None）、`has_display_pose`。
- Produces:
  - `sparc(signal: np.ndarray, dt_s: float, *, cutoff_hz: float = 10.0, amplitude_threshold: float = 0.05) -> float` — 谱弧长平滑度（越接近 0 越平滑，负值；退化输入返回 `np.nan`）。
  - `jerk_rms(positions: np.ndarray, times_s: np.ndarray) -> float` — 位置三阶差分 RMS（m/s³；样本 < 4 返回 `np.nan`）。
  - `compute_smoothness_summary(output: pd.DataFrame, *, session_id: str = "") -> pd.DataFrame` — 按 `condition × label` 汇总，列见下。

`SMOOTHNESS_COLUMNS = ["session_id", "condition", "rq2_trial_id", "label", "sample_count", "sparc_translation", "jerk_rms_translation_m_s3", "sparc_speed", "jerk_rms_speed"]`

- [ ] **Step 1: 写失败测试（SPARC 区分阶梯 vs 平滑）**

创建 `test_rq2_smoothness.py`：

```python
"""RQ2 运动平滑度指标（SPARC + jerk）单测。"""

import os
import unittest
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from egoanchor.eval.research.rq2.smoothness import (
    SMOOTHNESS_COLUMNS,
    compute_smoothness_summary,
    jerk_rms,
    sparc,
)


class TestSparc(unittest.TestCase):
    """SPARC 必须把平滑信号评为比阶梯信号更平滑（更接近 0）。"""

    def test_smooth_more_smooth_than_step(self):
        dt = 1.0 / 60.0
        t = np.arange(0.0, 4.0, dt)
        smooth = np.sin(2.0 * np.pi * 0.5 * t)
        # 8 Hz 采样零阶保持后重采样到 60 Hz：阶梯信号
        step_t = np.arange(0.0, 4.0, 1.0 / 8.0)
        step_vals = np.sin(2.0 * np.pi * 0.5 * step_t)
        idx = np.clip(np.searchsorted(step_t, t, side="right") - 1, 0, len(step_vals) - 1)
        step = step_vals[idx]
        self.assertGreater(sparc(smooth, dt), sparc(step, dt))

    def test_degenerate_returns_nan(self):
        self.assertTrue(np.isnan(sparc(np.zeros(3), 1.0 / 60.0)))
        self.assertTrue(np.isnan(sparc(np.array([1.0]), 1.0 / 60.0)))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd EgoAnchor_Python && KMP_DUPLICATE_LIB_OK=TRUE pixi run python -m unittest egoanchor.eval.tests.test_rq2_smoothness -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'egoanchor.eval.research.rq2.smoothness'`

- [ ] **Step 3: 写最小实现（SPARC + jerk）**

创建 `smoothness.py`：

```python
"""RQ2 运动平滑度指标：谱弧长（SPARC）与 jerk RMS。

SPARC（Balasubramanian et al. 2015, JNER）度量速度谱的弧长，越接近 0
越平滑；对幅度归一化、无量纲、抗噪。零阶保持产生的阶梯信号谱能量在高频
展宽，弧长更长（更负），因而 SPARC 能定量区分 Full 平滑曲线与 Raw-ZOH 阶梯。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from egoanchor.eval.metrics import is_pose_value

SMOOTHNESS_COLUMNS = [
    "session_id",
    "condition",
    "rq2_trial_id",
    "label",
    "sample_count",
    "sparc_translation",
    "jerk_rms_translation_m_s3",
    "sparc_speed",
    "jerk_rms_speed",
]
"""按 condition × label 汇总的平滑度字段。"""


def sparc(signal: np.ndarray, dt_s: float, *, cutoff_hz: float = 10.0,
          amplitude_threshold: float = 0.05) -> float:
    """计算一维信号的谱弧长平滑度（越接近 0 越平滑，退化返回 NaN）。"""

    values = np.asarray(signal, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 2 or dt_s <= 0.0:
        return np.nan
    values = values - float(np.mean(values))
    if not np.any(np.abs(values) > 0.0):
        return np.nan
    n_fft = int(2 ** np.ceil(np.log2(values.size * 4)))
    magnitude = np.abs(np.fft.rfft(values, n=n_fft))
    if not np.any(magnitude > 0.0):
        return np.nan
    magnitude = magnitude / float(np.max(magnitude))
    freq = np.fft.rfftfreq(n_fft, d=dt_s)
    band = freq <= cutoff_hz
    magnitude = magnitude[band]
    freq = freq[band]
    keep = magnitude >= amplitude_threshold
    if np.count_nonzero(keep) < 2:
        return np.nan
    last = np.max(np.nonzero(keep))
    magnitude = magnitude[: last + 1]
    freq = freq[: last + 1]
    df_norm = np.diff(freq) / (freq[-1] - freq[0]) if freq[-1] > freq[0] else None
    if df_norm is None:
        return np.nan
    dmag = np.diff(magnitude)
    arc = -float(np.sum(np.sqrt(df_norm ** 2 + dmag ** 2)))
    return arc


def jerk_rms(positions: np.ndarray, times_s: np.ndarray) -> float:
    """计算位置序列三阶差分（jerk）的 RMS（m/s³，样本不足返回 NaN）。"""

    pos = np.asarray(positions, dtype=float)
    times = np.asarray(times_s, dtype=float)
    if pos.ndim == 1:
        pos = pos.reshape(-1, 1)
    if pos.shape[0] < 4 or times.shape[0] != pos.shape[0]:
        return np.nan
    dt = float(np.median(np.diff(times)))
    if not np.isfinite(dt) or dt <= 0.0:
        return np.nan
    jerk = np.diff(pos, n=3, axis=0) / (dt ** 3)
    magnitude = np.linalg.norm(jerk, axis=1)
    magnitude = magnitude[np.isfinite(magnitude)]
    if magnitude.size == 0:
        return np.nan
    return float(np.sqrt(np.mean(magnitude ** 2)))


def compute_smoothness_summary(output: pd.DataFrame, *, session_id: str = "") -> pd.DataFrame:
    """按 condition × label 汇总 display 轨迹的 SPARC 与 jerk RMS。"""

    required = ("rq2_condition", "rq2_trial_id", "label")
    if output.empty or any(column not in output.columns for column in required):
        return pd.DataFrame(columns=SMOOTHNESS_COLUMNS)
    trial_id = pd.to_numeric(output["rq2_trial_id"], errors="coerce")
    motion = output.loc[
        output["rq2_condition"].fillna("none").astype(str).isin(
            ("slow_translation", "fast_motion", "rotation")
        )
        & (trial_id > 0)
    ].copy()
    if motion.empty:
        return pd.DataFrame(columns=SMOOTHNESS_COLUMNS)
    rows: list[dict[str, object]] = []
    for (condition, current_trial, label), group in motion.groupby(
        ["rq2_condition", "rq2_trial_id", "label"], sort=True
    ):
        times, series = _display_series(group)
        if times.size < 4:
            rows.append(_empty_row(session_id, condition, current_trial, label, times.size))
            continue
        dt = float(np.median(np.diff(times)))
        speed = np.linalg.norm(np.diff(series, axis=0), axis=1) / dt if dt > 0 else np.array([])
        rows.append(
            {
                "session_id": str(session_id),
                "condition": str(condition),
                "rq2_trial_id": int(current_trial),
                "label": str(label),
                "sample_count": int(times.size),
                "sparc_translation": sparc(series[:, 0], dt) if dt > 0 else np.nan,
                "jerk_rms_translation_m_s3": jerk_rms(series, times),
                "sparc_speed": sparc(speed, dt) if speed.size >= 2 and dt > 0 else np.nan,
                "jerk_rms_speed": np.nan,
            }
        )
    return pd.DataFrame.from_records(rows, columns=SMOOTHNESS_COLUMNS)


def _display_series(group: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """抽取按时间排序的有效 display 位置序列。"""

    frame = group.sort_values("render_mono_ms")
    display_mask = (
        frame["has_display_pose"].fillna(False).astype(bool)
        if "has_display_pose" in frame.columns
        else pd.Series(True, index=frame.index)
    )
    times: list[float] = []
    positions: list[list[float]] = []
    for _, row in frame[display_mask].iterrows():
        pos = row.get("display_pos", row.get("output_pos"))
        stamp = row.get("render_mono_ms")
        if is_pose_value(pos) and np.isfinite(stamp):
            times.append(float(stamp) / 1000.0)
            positions.append([float(v) for v in pos])
    if not times:
        return np.asarray([], dtype=float), np.zeros((0, 3), dtype=float)
    return np.asarray(times, dtype=float), np.asarray(positions, dtype=float)


def _empty_row(session_id: str, condition: str, trial: int, label: str,
               sample_count: int) -> dict[str, object]:
    """样本不足时的 NaN 行。"""

    return {
        "session_id": str(session_id),
        "condition": str(condition),
        "rq2_trial_id": int(trial),
        "label": str(label),
        "sample_count": int(sample_count),
        "sparc_translation": np.nan,
        "jerk_rms_translation_m_s3": np.nan,
        "sparc_speed": np.nan,
        "jerk_rms_speed": np.nan,
    }


__all__ = [
    "SMOOTHNESS_COLUMNS",
    "compute_smoothness_summary",
    "jerk_rms",
    "sparc",
]
```

- [ ] **Step 4: 补 jerk + summary 测试**

在 `test_rq2_smoothness.py` 末尾追加：

```python
class TestJerkRms(unittest.TestCase):
    """jerk RMS 对阶梯信号高于平滑信号。"""

    def test_step_more_jerky(self):
        dt = 1.0 / 60.0
        t = np.arange(0.0, 2.0, dt)
        smooth = np.column_stack([np.sin(t), np.zeros_like(t), np.zeros_like(t)])
        step = np.column_stack([np.round(np.sin(t) * 4) / 4, np.zeros_like(t), np.zeros_like(t)])
        self.assertGreater(jerk_rms(step, t), jerk_rms(smooth, t))

    def test_too_few_samples(self):
        self.assertTrue(np.isnan(jerk_rms(np.zeros((3, 3)), np.arange(3.0))))


class TestSmoothnessSummary(unittest.TestCase):
    """按 condition × label 分组产出稳定列。"""

    def test_columns_and_grouping(self):
        dt_ms = 1000.0 / 60.0
        n = 120
        rows = []
        for i in range(n):
            rows.append({
                "rq2_condition": "slow_translation",
                "rq2_trial_id": 1,
                "label": "Full",
                "render_mono_ms": i * dt_ms,
                "has_display_pose": True,
                "display_pos": [np.sin(i * dt_ms / 1000.0), 0.0, 0.0],
            })
        table = compute_smoothness_summary(pd.DataFrame(rows), session_id="s")
        self.assertEqual(list(table.columns), SMOOTHNESS_COLUMNS)
        self.assertEqual(len(table), 1)
        self.assertEqual(table.iloc[0]["label"], "Full")

    def test_empty_input(self):
        table = compute_smoothness_summary(pd.DataFrame())
        self.assertEqual(list(table.columns), SMOOTHNESS_COLUMNS)
        self.assertTrue(table.empty)


if __name__ == "__main__":
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    unittest.main()
```

- [ ] **Step 5: 运行全部 smoothness 测试确认通过**

Run: `cd EgoAnchor_Python && KMP_DUPLICATE_LIB_OK=TRUE pixi run python -m unittest egoanchor.eval.tests.test_rq2_smoothness -v`
Expected: PASS（6 tests）

- [ ] **Step 6: 提交**

```bash
git add EgoAnchor_Python/src/egoanchor/eval/research/rq2/smoothness.py EgoAnchor_Python/src/egoanchor/eval/tests/test_rq2_smoothness.py
git commit -m "feat(rq2): add motion smoothness metrics (SPARC + jerk RMS)"
```

---

### Task 2: 在包级入口 re-export smoothness API

**Files:**
- Modify: `EgoAnchor_Python/src/egoanchor/eval/research/rq2/__init__.py`

**Interfaces:**
- Consumes: `smoothness.py` 的 `SMOOTHNESS_COLUMNS`、`compute_smoothness_summary`。
- Produces: 包级可 `from egoanchor.eval.research.rq2 import compute_smoothness_summary`。

- [ ] **Step 1: 写失败测试（包级导入）**

创建临时验证（在下一步用命令直接验证，不建持久测试文件——包级导出由 import 成败即证）。先运行：

Run: `cd EgoAnchor_Python && KMP_DUPLICATE_LIB_OK=TRUE pixi run python -c "from egoanchor.eval.research.rq2 import compute_smoothness_summary"`
Expected: FAIL，`ImportError: cannot import name 'compute_smoothness_summary'`

- [ ] **Step 2: 添加 re-export**

编辑 `__init__.py`，在 `from .qc import ...` 之后加：

```python
from .smoothness import SMOOTHNESS_COLUMNS, compute_smoothness_summary
```

并在 `__all__` 列表中加入 `"SMOOTHNESS_COLUMNS"` 和 `"compute_smoothness_summary"`（按现有字母/逻辑顺序放置）。

- [ ] **Step 3: 运行导入确认通过**

Run: `cd EgoAnchor_Python && KMP_DUPLICATE_LIB_OK=TRUE pixi run python -c "from egoanchor.eval.research.rq2 import compute_smoothness_summary, SMOOTHNESS_COLUMNS; print('ok')"`
Expected: 输出 `ok`

- [ ] **Step 4: 提交**

```bash
git add EgoAnchor_Python/src/egoanchor/eval/research/rq2/__init__.py
git commit -m "feat(rq2): re-export smoothness API at package level"
```

---

### Task 3: pipeline 挂接 smoothness 计算，产出 rq2_smoothness 表

**Files:**
- Modify: `EgoAnchor_Python/src/egoanchor/eval/research/rq2/pipeline.py`
- Modify: `EgoAnchor_Python/src/egoanchor/eval/tests/test_rq2_analyze.py`

**Interfaces:**
- Consumes: `compute_smoothness_summary(output, session_id=...)` → `SMOOTHNESS_COLUMNS` 表。
- Produces: `run_rq2_analysis` 返回的 dict 新增键 `"rq2_smoothness"`；`_compute_session_tables` 与 `_combine_session_tables` 处理该表；CSV 落盘 `rq2_smoothness.csv`。

- [ ] **Step 1: 写失败测试（分析产物含 smoothness 表）**

在 `test_rq2_analyze.py` 找到调用 `run_rq2_analysis` 的现有测试类，新增一个测试方法（复用其 fixture/session 构造方式；若已有 `tables = run_rq2_analysis(...)`，仿照写）：

```python
    def test_smoothness_table_present(self):
        tables = self._run()  # 复用现有构造分析结果的 helper；无 helper 则内联现有测试的构造
        self.assertIn("rq2_smoothness", tables)
        self.assertEqual(
            list(tables["rq2_smoothness"].columns),
            [
                "session_id", "condition", "rq2_trial_id", "label",
                "sample_count", "sparc_translation",
                "jerk_rms_translation_m_s3", "sparc_speed", "jerk_rms_speed",
            ],
        )
```

> 若现有测试没有 `_run` helper：查看 `test_rq2_analyze.py` 里已有的 `run_rq2_analysis` 调用，复制其 session 目录构造与调用，替换断言为上面的 `assertIn` / 列断言。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd EgoAnchor_Python && KMP_DUPLICATE_LIB_OK=TRUE pixi run python -m unittest egoanchor.eval.tests.test_rq2_analyze -v`
Expected: FAIL，`KeyError: 'rq2_smoothness'` 或 `AssertionError`

- [ ] **Step 3: 在 pipeline 挂接**

编辑 `pipeline.py`：

1. 顶部 import 处加：`from .smoothness import SMOOTHNESS_COLUMNS, compute_smoothness_summary`
2. `_compute_session_tables` 内，在 `trial = compute_trial_summary(...)` 之后加：

```python
    smoothness = compute_smoothness_summary(output, session_id=session_id)
```

3. `_compute_session_tables` 的返回 dict 中加一项：`"rq2_smoothness": smoothness,`
4. `_combine_session_tables` 的 `names` 列表末尾加 `"rq2_smoothness"`。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd EgoAnchor_Python && KMP_DUPLICATE_LIB_OK=TRUE pixi run python -m unittest egoanchor.eval.tests.test_rq2_analyze -v`
Expected: PASS

- [ ] **Step 5: 端到端复跑真实数据确认 CSV 落盘**

Run: `cd EgoAnchor_Python && KMP_DUPLICATE_LIB_OK=TRUE pixi run python -m egoanchor.eval.research.rq2.analyze --session-dir data/eval/rq2_data`
Expected: 无异常；`data/eval/rq2_data/report/rq2_smoothness.csv` 生成，含三行（slow/fast/rotation × Full；Raw-ZOH 视分组而定），`sparc_translation` 为有限负值。

- [ ] **Step 6: 提交**

```bash
git add EgoAnchor_Python/src/egoanchor/eval/research/rq2/pipeline.py EgoAnchor_Python/src/egoanchor/eval/tests/test_rq2_analyze.py
git commit -m "feat(rq2): wire smoothness summary into analysis pipeline"
```

---

### Task 4: 实时轨迹 Hero 图（三面板 a/b/c）

**Files:**
- Modify: `EgoAnchor_Python/src/egoanchor/eval/research/rq2/plot.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_rq2_plot.py`（新建）

**Interfaces:**
- Consumes: 单 session 的 `output` DataFrame（含 `render_mono_ms`、`rq2_condition`、`rq2_trial_id`、`label`、`display_pos/rot`、`aligned_raw_pos/rot`、`gt_pos/rot`、`gt_pose_fresh`、`gt_linear_speed_m_s`）。
- Produces: `write_rq2_hero_figure(output: pd.DataFrame, output_dir: Path | str, *, preliminary: bool = True) -> Path | None` — 导出 `rq2_hero_trajectory_preliminary.pdf`/`.png`，返回 PDF 路径（无合格数据返回 None）。挂进 `write_rq2_plots` 的调用被 Task 5 处理；本任务只加函数与其独立测试。

- [ ] **Step 1: 写失败测试（hero 图函数存在且产出文件）**

创建 `test_rq2_plot.py`：

```python
"""RQ2 实时轨迹 hero 图纯绘图层单测（不依赖 cv2）。"""

import os
import sys
import unittest
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from egoanchor.eval.research.rq2.plot import write_rq2_hero_figure


def _synthetic_output() -> pd.DataFrame:
    """构造含 GT / Full / Raw-ZOH / aligned raw 的最小实时轨迹。"""

    dt_ms = 1000.0 / 60.0
    rows = []
    n = 180
    for i in range(n):
        t = i * dt_ms / 1000.0
        gt = [float(np.sin(t)), 0.1, 0.2]
        full = [float(np.sin(t - 0.29)), 0.1, 0.2]
        # Raw-ZOH：8 Hz 阶梯
        zoh_t = np.floor(t * 8) / 8
        zoh = [float(np.sin(zoh_t - 0.22)), 0.1, 0.2]
        for label, disp in (("Full", full), ("Raw-ZOH", zoh)):
            rows.append({
                "rq2_condition": "slow_translation",
                "rq2_trial_id": 1,
                "label": label,
                "is_primary": label == "Full",
                "render_mono_ms": i * dt_ms,
                "has_display_pose": True,
                "display_pos": disp,
                "display_rot": [0.0, 0.0, 0.0, 1.0],
                "aligned_raw_pos": gt if (label == "Full" and i % 8 == 0) else None,
                "aligned_raw_rot": [0.0, 0.0, 0.0, 1.0] if (label == "Full" and i % 8 == 0) else None,
                "gt_pos": gt,
                "gt_rot": [0.0, 0.0, 0.0, 1.0],
                "gt_pose_fresh": True,
                "gt_linear_speed_m_s": abs(float(np.cos(t))),
            })
    return pd.DataFrame(rows)


class TestHeroFigure(unittest.TestCase):
    def test_writes_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_rq2_hero_figure(_synthetic_output(), tmp)
            self.assertIsNotNone(path)
            self.assertTrue(Path(path).exists())
            self.assertTrue((Path(tmp) / "rq2_hero_trajectory_preliminary.png").exists())

    def test_empty_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(write_rq2_hero_figure(pd.DataFrame(), tmp))


if __name__ == "__main__":
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd EgoAnchor_Python && KMP_DUPLICATE_LIB_OK=TRUE pixi run python -m unittest egoanchor.eval.tests.test_rq2_plot -v`
Expected: FAIL，`ImportError: cannot import name 'write_rq2_hero_figure'`

- [ ] **Step 3: 实现 hero 图函数**

在 `plot.py` 顶部现有 import 后确保有 `from egoanchor.eval.metrics import is_pose_value`（若无则加）。在文件中新增函数（放在 `write_rq2_plots` 之后）：

```python
def write_rq2_hero_figure(
    output: pd.DataFrame,
    output_dir: Path | str,
    *,
    preliminary: bool = True,
) -> Path | None:
    """导出实时轨迹 hero 图：GT / Full / Raw-ZOH / 稀疏 raw 观测的时序对比。

    三面板：(a) 平移分量 X–t（慢速平移 trial），(b) 平移分量 X–t（快速运动
    trial），(c) 参考线速度–t。一眼对比 Full 平滑曲线与 Raw-ZOH 阶梯跳变，
    并诚实暴露 Full 的相位滞后。单会话数据默认带 _preliminary 标识。
    """

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    slow = _select_trial(output, "slow_translation")
    fast = _select_trial(output, "fast_motion")
    if slow is None and fast is None:
        return None
    fig, axes = plt.subplots(3, 1, figsize=(7.2, 8.4), sharex=False)
    _plot_trajectory_panel(axes[0], slow, title="(a) 慢速平移：X 分量")
    _plot_trajectory_panel(axes[1], fast, title="(b) 快速运动：X 分量")
    _plot_speed_panel(axes[2], slow if slow is not None else fast,
                      title="(c) 参考线速度")
    if preliminary:
        fig.suptitle("RQ2 实时轨迹（单会话先导，不用于总体推断）",
                     color="crimson", fontsize=11)
    suffix = "_preliminary" if preliminary else ""
    stem = f"rq2_hero_trajectory{suffix}"
    _save(fig, destination / stem)
    return destination / f"{stem}.pdf"


def _select_trial(output: pd.DataFrame, condition: str) -> pd.DataFrame | None:
    """选出指定 condition 的首个合法 trial（含各变体）。"""

    if output.empty or "rq2_condition" not in output.columns:
        return None
    trial_id = pd.to_numeric(output.get("rq2_trial_id"), errors="coerce")
    subset = output[
        output["rq2_condition"].fillna("none").astype(str).eq(condition)
        & (trial_id > 0)
    ].copy()
    if subset.empty:
        return None
    first_trial = int(pd.to_numeric(subset["rq2_trial_id"], errors="coerce").min())
    return subset[pd.to_numeric(subset["rq2_trial_id"], errors="coerce").eq(first_trial)]


def _component_series(frame: pd.DataFrame, column: str, index: int,
                      *, mask_column: str | None = None):
    """抽取按时间排序的 (t_s, 分量值) 序列，供轨迹面板绘制。"""

    ordered = frame.sort_values("render_mono_ms")
    if mask_column is not None and mask_column in ordered.columns:
        ordered = ordered[ordered[mask_column].fillna(False).astype(bool)]
    times: list[float] = []
    values: list[float] = []
    for _, row in ordered.iterrows():
        vec = row.get(column)
        stamp = row.get("render_mono_ms")
        if is_pose_value(vec) and np.isfinite(stamp):
            times.append(float(stamp) / 1000.0)
            values.append(float(vec[index]))
    return np.asarray(times, dtype=float), np.asarray(values, dtype=float)


def _plot_trajectory_panel(ax, trial: pd.DataFrame | None, *, title: str) -> None:
    """在一个子图上叠加 GT / Full / Raw-ZOH / 稀疏 raw 观测。"""

    ax.set_title(title, fontsize=10, loc="left")
    ax.set_ylabel("X (m)")
    ax.set_xlabel("t (s)")
    if trial is None or trial.empty:
        ax.text(0.5, 0.5, "无合格 trial", ha="center", va="center", transform=ax.transAxes)
        return
    t0 = float(pd.to_numeric(trial["render_mono_ms"], errors="coerce").min()) / 1000.0
    full = trial[trial["label"].astype(str).eq("Full")]
    zoh = trial[trial["label"].astype(str).eq("Raw-ZOH")]
    gt_t, gt_v = _component_series(full, "gt_pos", 0)
    if gt_t.size:
        ax.plot(gt_t - t0, gt_v, color="0.2", linewidth=1.4, label="GT 参考")
    full_t, full_v = _component_series(full, "display_pos", 0, mask_column="has_display_pose")
    if full_t.size:
        ax.plot(full_t - t0, full_v, color="tab:blue", linewidth=1.2, label="Full 显示")
    zoh_t, zoh_v = _component_series(zoh, "display_pos", 0, mask_column="has_display_pose")
    if zoh_t.size:
        ax.plot(zoh_t - t0, zoh_v, color="tab:orange", linewidth=1.0,
                linestyle="--", drawstyle="steps-post", label="Raw-ZOH 显示")
    raw_t, raw_v = _component_series(full, "aligned_raw_pos", 0)
    if raw_t.size:
        ax.scatter(raw_t - t0, raw_v, s=14, color="tab:green", zorder=5,
                   label="raw 观测 (~8 Hz)")
    ax.legend(fontsize=7, loc="best")


def _plot_speed_panel(ax, trial: pd.DataFrame | None, *, title: str) -> None:
    """绘制参考线速度–t，作为运动强度背景。"""

    ax.set_title(title, fontsize=10, loc="left")
    ax.set_ylabel("speed (m/s)")
    ax.set_xlabel("t (s)")
    if trial is None or trial.empty:
        ax.text(0.5, 0.5, "无合格 trial", ha="center", va="center", transform=ax.transAxes)
        return
    full = trial[trial["label"].astype(str).eq("Full")].sort_values("render_mono_ms")
    t0 = float(pd.to_numeric(full["render_mono_ms"], errors="coerce").min()) / 1000.0
    times = pd.to_numeric(full["render_mono_ms"], errors="coerce").to_numpy(dtype=float) / 1000.0
    speed = pd.to_numeric(full.get("gt_linear_speed_m_s"), errors="coerce").to_numpy(dtype=float)
    finite = np.isfinite(times) & np.isfinite(speed)
    if np.any(finite):
        ax.plot(times[finite] - t0, speed[finite], color="tab:purple", linewidth=1.0)
```

确认 `plot.py` 中已存在 `_save(fig, path_without_ext)` 辅助（现有 `_plot_accuracy` 已调用它）。若 `_save` 只存 PDF，需确认它同时存 PNG——检查现有实现；若只存一种，在 `_save` 内补另一种（不改其签名）。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd EgoAnchor_Python && KMP_DUPLICATE_LIB_OK=TRUE pixi run python -m unittest egoanchor.eval.tests.test_rq2_plot -v`
Expected: PASS（2 tests）

> 若 `test_writes_pdf` 因 `_save` 只产 PDF 而缺 PNG 失败：查看 `plot.py` 的 `_save` 定义，确认它 `fig.savefig(f"{path}.pdf")` 与 `fig.savefig(f"{path}.png")` 都调用；缺则补齐。

- [ ] **Step 5: 提交**

```bash
git add EgoAnchor_Python/src/egoanchor/eval/research/rq2/plot.py EgoAnchor_Python/src/egoanchor/eval/tests/test_rq2_plot.py
git commit -m "feat(rq2): add realtime trajectory hero figure"
```

---

### Task 5: 在分析入口导出 hero 图

**Files:**
- Modify: `EgoAnchor_Python/src/egoanchor/eval/research/rq2/pipeline.py`

**Interfaces:**
- Consumes: `write_rq2_hero_figure(output, output_dir)`（Task 4）；`run_rq2_analysis` 已有的 `output_dir` 与单 session output。
- Produces: 真实分析运行后 `report/rq2_hero_trajectory_preliminary.pdf` 生成。

- [ ] **Step 1: 挂接 hero 图导出**

在 `pipeline.py` 顶部 import 处，把 `from .plot import write_rq2_plots` 改为 `from .plot import write_rq2_hero_figure, write_rq2_plots`。

`run_rq2_analysis` 需要拿到单 session 的合并 output 来画 hero 图。由于 hero 图只用单个先导 session，最直接：在 `run_rq2_analysis` 里保留每个 session 的 output。修改 `_compute_session_tables` 已返回表，但没有原始 output。为最小改动，在 `run_rq2_analysis` 的 session 循环中直接调用 hero 图（此处已有 `logs`）：

在 `run_rq2_analysis` 内，找到 `output_dir = _report_dir(...)` 与 `write_rq2_plots(combined, output_dir)`。在 `write_rq2_plots(combined, output_dir)` 之后加：

```python
    if len(paths) == 1:
        hero_output = annotate_active_motion(load_session(paths[0]).output)
        write_rq2_hero_figure(hero_output, output_dir)
```

> 说明：hero 图是单会话机制展示，多 session 联合分析不产出（与 `_preliminary` 定位一致）。`annotate_active_motion` 与 `load_session` 已在 pipeline 顶部导入。

- [ ] **Step 2: 端到端复跑确认 hero 图产出**

Run: `cd EgoAnchor_Python && KMP_DUPLICATE_LIB_OK=TRUE pixi run python -m egoanchor.eval.research.rq2.analyze --session-dir data/eval/rq2_data`
Expected: 无异常；`data/eval/rq2_data/report/rq2_hero_trajectory_preliminary.pdf` 与 `.png` 生成。

- [ ] **Step 3: 人工核对图内容**

Read: `data/eval/rq2_data/report/rq2_hero_trajectory_preliminary.png`
Expected: 三面板；(a)(b) 见 GT 曲线、Full 平滑曲线、Raw-ZOH 阶梯虚线、绿色稀疏 raw 点；(c) 线速度曲线；顶部红色 preliminary 标题。

- [ ] **Step 4: 提交**

```bash
git add EgoAnchor_Python/src/egoanchor/eval/research/rq2/pipeline.py
git commit -m "feat(rq2): export hero trajectory figure from analysis entry"
```

---

### Task 6: paper.py 导出四轴权衡指标到 Typst

**Files:**
- Create: `EgoAnchor_Python/src/egoanchor/eval/research/rq2/paper.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_rq2_paper.py`（新建）

**Interfaces:**
- Consumes: `run_rq2_analysis` 返回的 combined dict（含 `rq2_trial_summary`、`rq2_smoothness`）。
- Produces:
  - `build_rq2_typst_snapshot(tables: dict[str, pd.DataFrame]) -> str` — 生成 `#let rq2-... = [...]` Typst 变量文本（含 SPARC、jerk、四轴汇总数值）。
  - `write_rq2_typst(tables, path: Path | str) -> Path` — 写入 `generated/rq2_results.typ`。
  - CLI：`python -m egoanchor.eval.research.rq2.paper --session-dir <dir> --typst-output <path>`。

> 注：旧 `paper.py` 已在 git 清理阶段删除。本任务重建，只导出新四轴指标，不生成结论性叙事。仅使用通过 QC 的 trial。
>
> **术语与内部标签解耦**：`_LABEL_PREFIX` 的键仍是数据内部标签 `Full` / `Raw-ZOH`（不改，否则读不到数据）；变量名前缀 `full` / `raw` 只是内部 slug，不出现在正文。正文规范术语（*完整锚定* / *零阶保持 ZOH* / *时空对齐感知观测*）由 Task 7 在 typ 正文层直接书写，不依赖变量名。快照只导出数值，不导出术语字符串。

- [ ] **Step 1: 写失败测试（snapshot 含 SPARC 变量）**

创建 `test_rq2_paper.py`：

```python
"""RQ2 Typst 数值快照导出单测。"""

import os
import sys
import unittest
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from egoanchor.eval.research.rq2.paper import build_rq2_typst_snapshot, write_rq2_typst


def _tables() -> dict[str, pd.DataFrame]:
    trial = pd.DataFrame([
        {"session_id": "s", "condition": "slow_translation", "rq2_trial_id": 1,
         "label": "Full", "audit_accepted": True,
         "within_tolerance_valid_tracking_rate": 0.448,
         "display_update_rate_hz": 60.0, "display_hold_fraction": 0.034,
         "display_translation_p95_m": 0.116, "display_rotation_p95_deg": 15.5},
        {"session_id": "s", "condition": "slow_translation", "rq2_trial_id": 1,
         "label": "Raw-ZOH", "audit_accepted": True,
         "within_tolerance_valid_tracking_rate": 0.649,
         "display_update_rate_hz": 8.5, "display_hold_fraction": 0.86,
         "display_translation_p95_m": 0.077, "display_rotation_p95_deg": 12.7},
    ])
    smooth = pd.DataFrame([
        {"session_id": "s", "condition": "slow_translation", "rq2_trial_id": 1,
         "label": "Full", "sparc_translation": -3.2,
         "jerk_rms_translation_m_s3": 1.1, "sparc_speed": -4.0, "jerk_rms_speed": np.nan},
        {"session_id": "s", "condition": "slow_translation", "rq2_trial_id": 1,
         "label": "Raw-ZOH", "sparc_translation": -9.8,
         "jerk_rms_translation_m_s3": 25.0, "sparc_speed": -12.0, "jerk_rms_speed": np.nan},
    ])
    return {"rq2_trial_summary": trial, "rq2_smoothness": smooth}


class TestSnapshot(unittest.TestCase):
    def test_contains_sparc_variable(self):
        text = build_rq2_typst_snapshot(_tables())
        self.assertIn("rq2-full-sparc-translation-slow", text)
        self.assertIn("rq2-raw-sparc-translation-slow", text)

    def test_write_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_rq2_typst(_tables(), Path(tmp) / "rq2_results.typ")
            self.assertTrue(Path(path).exists())
            self.assertIn("#let", Path(path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd EgoAnchor_Python && KMP_DUPLICATE_LIB_OK=TRUE pixi run python -m unittest egoanchor.eval.tests.test_rq2_paper -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'egoanchor.eval.research.rq2.paper'`

- [ ] **Step 3: 实现 paper.py**

创建 `paper.py`：

```python
"""RQ2 四轴权衡数值的 Typst 快照导出。

只使用通过 QC 的 trial，先在 condition 内等 trial 权重汇总；不生成结论性叙事。
生成文件 generated/rq2_results.typ 不得手改。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from .pipeline import run_rq2_analysis

_CONDITION_SUFFIX = {
    "slow_translation": "slow",
    "fast_motion": "fast",
    "rotation": "rotation",
}
_LABEL_PREFIX = {"Full": "full", "Raw-ZOH": "raw"}


def build_rq2_typst_snapshot(tables: dict[str, pd.DataFrame]) -> str:
    """把四轴指标渲染为 #let Typst 变量文本。"""

    lines: list[str] = [
        "// 本文件由 egoanchor.eval.research.rq2.paper 生成，请勿手改。",
        "",
    ]
    trial = _accepted(tables.get("rq2_trial_summary", pd.DataFrame()))
    smooth = tables.get("rq2_smoothness", pd.DataFrame())
    lines.extend(_metric_lines(trial, "within_tolerance_valid_tracking_rate",
                               "rate", scale=100.0, digits=1))
    lines.extend(_metric_lines(trial, "display_update_rate_hz",
                               "update", scale=1.0, digits=1))
    lines.extend(_metric_lines(trial, "display_hold_fraction",
                               "hold", scale=100.0, digits=1))
    lines.extend(_metric_lines(trial, "display_translation_p95_m",
                               "translation-p95", scale=1000.0, digits=1))
    lines.extend(_metric_lines(trial, "display_rotation_p95_deg",
                               "rotation-p95", scale=1.0, digits=1))
    lines.extend(_metric_lines(smooth, "sparc_translation",
                               "sparc-translation", scale=1.0, digits=2))
    lines.extend(_metric_lines(smooth, "jerk_rms_translation_m_s3",
                               "jerk-translation", scale=1.0, digits=1))
    return "\n".join(lines) + "\n"


def write_rq2_typst(tables: dict[str, pd.DataFrame], path: Path | str) -> Path:
    """把快照写入指定 Typst 文件。"""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(build_rq2_typst_snapshot(tables), encoding="utf-8")
    return destination


def _accepted(trial: pd.DataFrame) -> pd.DataFrame:
    """仅保留通过 audit 的 trial 行。"""

    if trial.empty or "audit_accepted" not in trial.columns:
        return trial
    return trial[trial["audit_accepted"].fillna(False).astype(bool)].copy()


def _metric_lines(table: pd.DataFrame, column: str, metric_slug: str,
                  *, scale: float, digits: int) -> list[str]:
    """为一个指标在 label × condition 上生成 #let 行。"""

    if table.empty or column not in table.columns:
        return []
    lines: list[str] = []
    grouped = table.groupby(["label", "condition"], sort=True)[column].mean()
    for (label, condition), value in grouped.items():
        prefix = _LABEL_PREFIX.get(str(label))
        suffix = _CONDITION_SUFFIX.get(str(condition))
        if prefix is None or suffix is None:
            continue
        name = f"rq2-{prefix}-{metric_slug}-{suffix}"
        rendered = "NaN" if not np.isfinite(value) else f"{value * scale:.{digits}f}"
        lines.append(f'#let {name} = [{rendered}]')
    return lines


def main(argv: list[str] | None = None) -> int:
    """CLI：分析 session 并导出 Typst 快照。"""

    parser = argparse.ArgumentParser(description="导出 RQ2 四轴权衡 Typst 快照")
    parser.add_argument("--session-dir", action="append", required=True)
    parser.add_argument("--typst-output", required=True)
    parser.add_argument("--report-dir", default=None)
    args = parser.parse_args(argv)
    tables = run_rq2_analysis(args.session_dir, report_dir=args.report_dir)
    path = write_rq2_typst(tables, args.typst_output)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_rq2_typst_snapshot", "main", "write_rq2_typst"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd EgoAnchor_Python && KMP_DUPLICATE_LIB_OK=TRUE pixi run python -m unittest egoanchor.eval.tests.test_rq2_paper -v`
Expected: PASS（2 tests）

- [ ] **Step 5: 端到端生成真实快照**

Run: `cd EgoAnchor_Python && KMP_DUPLICATE_LIB_OK=TRUE pixi run python -m egoanchor.eval.research.rq2.paper --session-dir data/eval/rq2_data --typst-output ../2026-EgoAnchor-Typst/generated/rq2_results.typ`
Expected: 输出 `wrote .../rq2_results.typ`；文件含 `#let rq2-full-sparc-translation-slow = [...]` 等变量。

- [ ] **Step 6: 提交**

```bash
git add EgoAnchor_Python/src/egoanchor/eval/research/rq2/paper.py EgoAnchor_Python/src/egoanchor/eval/tests/test_rq2_paper.py 2026-EgoAnchor-Typst/generated/rq2_results.typ
git commit -m "feat(rq2): export four-axis tradeoff metrics to Typst snapshot"
```

---

### Task 7: 论文 §RQ2 设计与结果重写

**Files:**
- Modify: `2026-EgoAnchor-Typst/egoanchor_cn_v6.typ`（§RQ2 研究问题、§动态实验设计、§RQ2 结果）
- Modify: `2026-EgoAnchor-Typst/egoanchor_cn_v6.typ` 顶部 import（引入 `generated/rq2_results.typ`）
- Reference: `data/eval/rq2_data/report/rq2_hero_trajectory_preliminary.pdf`（复制到 `figs/rq2/`）

**Interfaces:**
- Consumes: Task 6 生成的 `generated/rq2_results.typ` 变量；Task 5 生成的 hero 图 PDF。
- Produces: 编译通过的 `pdf/egoanchor_cn_v6.pdf`，§RQ2 呈现四轴权衡叙事 + hero 主图。

- [ ] **Step 1: 复制 hero 图到 figs 目录**

```bash
mkdir -p 2026-EgoAnchor-Typst/figs/rq2
cp EgoAnchor_Python/data/eval/rq2_data/report/rq2_hero_trajectory_preliminary.pdf 2026-EgoAnchor-Typst/figs/rq2/
```

- [ ] **Step 2: 确认 typ 顶部已 import generated 快照**

Grep `egoanchor_cn_v6.typ` 是否已有 `#import "generated/rq2_results.typ"` 或 `#include`。当前正文用 `#rq2-full-rate-slow` 等变量说明已有 import 机制；确认变量来源文件路径与 Task 6 输出一致（`generated/rq2_results.typ`）。若变量名从旧 `rq2-full-rate-slow` 改为新命名，需同步替换正文引用。

> 注：本任务采用**新变量命名**（Task 6 定义的 `rq2-full-rate-slow` 实为 `rq2-full-rate-slow`？）——核对 Task 6 `_metric_slug`：within-tolerance 用 metric_slug=`rate`，故变量名是 `rq2-full-rate-slow`。与旧正文 `#rq2-full-rate-slow` 一致，无需改名。新增变量：`rq2-full-sparc-translation-slow`、`rq2-full-jerk-translation-slow`、`rq2-full-update-slow`、`rq2-full-hold-slow` 等。

- [ ] **Step 3: 全文术语统一（先做，贯穿全文而非仅 RQ2 段）**

在 `egoanchor_cn_v6.typ` 全文执行术语规范化（grep 定位每处，逐一改）：

- 正文出现的 `*Raw-ZOH*` 斜体标签 → 首次出现写 *零阶保持*（Zero-Order Hold, ZOH），此后写 *ZOH*。（注：数据/代码内部标签 `Raw-ZOH` 不在正文，无需改；这里只改 typ 正文。）
- 裸 "raw 误差" / "raw 感知误差" / "raw source" / "aligned raw" → *时空对齐感知观测* / 感知观测误差 / 感知观测产出率。
- `*Frame-aligned*` / `*Arrival-aligned*` 斜体变体标签：从正文主叙事删除；确需提及相机取样时刻诊断时，表述为"基于帧标识的时空对齐诊断"，不作为实验变体。
- "帧对齐"单独成词处 → "基于帧标识的时空对齐"（§设计启示、§时间一致性的边界两处 discussion 段落也一并统一）。
- *Full* 保留斜体，但首次出现补一句定位："*完整锚定*（下称 *Full*，即包含运动估计、时序平滑与静止锚定的完整策略）"，明确它是同一系统的一个配置，*ZOH* 是剥离这些策略后的同一系统。

Run（定位所有待改处）: `cd p:/VSCode-Project/EgoAnchor && grep -n "Raw-ZOH\|raw 误差\|raw 感知\|raw source\|aligned raw\|Frame-aligned\|Arrival-aligned\|帧对齐" 2026-EgoAnchor-Typst/egoanchor_cn_v6.typ`
Expected: 列出全部待改行；逐行用 Edit 改为规范术语。

- [ ] **Step 4: 重写 §动态实验设计段**

把"误差容限内有效追踪率为主终点"框架改为四轴权衡刻画。替换该段核心表述为：

```
RQ2 不以单一主终点判定优劣，而是刻画完整锚定策略相对零阶保持（Zero-Order Hold, ZOH）参照的四轴权衡：连续性（显示更新率、保持帧占比、生命周期状态）、运动平滑度（谱弧长 SPARC 与 jerk 均方根）、响应延迟（策略目标延迟与经验响应滞后）与当前时刻配准精度（平移/旋转 P95、误差容限内有效追踪率）。四轴各有占优侧，互补呈现代价与收益，何者更优取决于任务，由 RQ3 用户研究检验主观偏好。
```

保留原有先导数据与三类运动、时间语义、清洗规则段落，只把"主终点"表述统一为"四轴权衡中的精度轴"，并把该段内 `*Raw-ZOH*` / `raw` 术语按 Step 3 规范替换。

- [ ] **Step 4: 重写 §RQ2 结果段（第 381–407 行区域）**

- 把 hero 图设为主图（替换现有 `rq2_accuracy_primary_preliminary` + `rq2_paired_tradeoff_preliminary` 双图 figure 为 hero 图 figure），图注说明四轴权衡与相位滞后的诚实呈现。
- 结果按四轴顺序叙述：连续性（*完整锚定* 占优）→ 平滑度（*完整锚定* 占优，引用新 SPARC/jerk 变量）→ 延迟（*完整锚定* 付出）→ 精度（*ZOH* 略优，降级表述，不写"失败"）。
- 删除"主终点均低于 *ZOH*"的负面框架，改为"以精度与延迟为代价换取连续性与平滑度"。
- 引入 SPARC 变量：`平滑度上 *完整锚定* 的 SPARC 为 #rq2-full-sparc-translation-slow，*ZOH* 为 #rq2-raw-sparc-translation-slow（越接近 0 越平滑），jerk 均方根 #rq2-full-jerk-translation-slow 对 #rq2-raw-jerk-translation-slow m/s³`。
- 保留 `_preliminary` 与单会话免责表述。
- **术语铁律**：正文一律用 *完整锚定* / *零阶保持（ZOH）*，禁止出现 `*Full*`、`*Raw-ZOH*`、裸 "raw"、`*Frame-aligned*` / `*Arrival-aligned*`；感知观测统称"时空对齐感知观测"。

具体替换文本（结果段开头示例，保持学术凝练；首次出现处标注 ZOH 英文全称）：

```
== RQ2：动态追踪能力

当前数据为单一先导会话，每类运动各一个长试次，用于机制展示而非总体推断。三个试次均通过预定质量审计。@fig:rq2-dynamic 以实时轨迹对比系统输出：*完整锚定* 输出约 60 Hz 平滑连续曲线，*零阶保持*（Zero-Order Hold, ZOH）呈约 8 Hz 阶梯跳变，稀疏时空对齐感知观测点与平台参考轨迹叠加其上。图同时诚实显示 *完整锚定* 的相位滞后。

*连续性。* *完整锚定* 将显示更新率提高至 #rq2-full-update-slow Hz，*ZOH* 仅 #rq2-raw-update-slow Hz；保持帧比例从 *ZOH* 的 #rq2-raw-hold-slow% 降至 *完整锚定* 的 #rq2-full-hold-slow%。

*运动平滑度。* *完整锚定* 的平移 SPARC 为 #rq2-full-sparc-translation-slow、*ZOH* 为 #rq2-raw-sparc-translation-slow（越接近 0 越平滑）；jerk 均方根分别为 #rq2-full-jerk-translation-slow 与 #rq2-raw-jerk-translation-slow m/s³。零阶保持的阶梯跳变在谱域展宽，平滑度显著劣于完整策略。

*响应延迟。* 完整策略以历史目标时刻输出换取平滑，中位目标延迟高于零阶保持约 66 ms。

*当前时刻精度。* 在瞬时配准精度轴上，延迟更小的 *ZOH* 略优：低速平移误差容限内有效追踪率 #rq2-raw-rate-slow% 对 *完整锚定* 的 #rq2-full-rate-slow%。两配置共享同一感知流与参考轨迹，该差异源于延迟—平滑权衡而非操作差异。
```

（fast/rotation 的对应变量按需补充，控制篇幅。）

- [ ] **Step 5: 更新 hero 图 figure 块**

替换 `<fig:rq2-dynamic>` 的 image 引用为：

```
  align(center)[
    #image("figs/rq2/rq2_hero_trajectory_preliminary.pdf", width: 100%)
  ],
  caption: [RQ2 单会话先导实时轨迹。平台参考（深灰）、*完整锚定* 显示（蓝，约 60 Hz 平滑）、*ZOH* 显示（橙虚线，约 8 Hz 阶梯）与稀疏时空对齐感知观测（绿点）叠加。(a) 慢速平移、(b) 快速运动的 X 分量，(c) 参考线速度。图诚实显示 *完整锚定* 的相位滞后。红色标题标明先导数据不用于总体推断。],
```

- [ ] **Step 6: 编译论文确认通过**

Run: `cd p:/VSCode-Project/EgoAnchor && typst compile --root . 2026-EgoAnchor-Typst/egoanchor_cn_v6.typ 2026-EgoAnchor-Typst/pdf/egoanchor_cn_v6.pdf`
Expected: 无错误退出，生成 PDF。若报 `unknown variable rq2-full-sparc-...`，核对 Task 6 变量名与正文引用一致。

- [ ] **Step 7: 提交**

```bash
git add 2026-EgoAnchor-Typst/egoanchor_cn_v6.typ 2026-EgoAnchor-Typst/figs/rq2/ 2026-EgoAnchor-Typst/pdf/egoanchor_cn_v6.pdf
git commit -m "docs(paper): rewrite RQ2 as four-axis tradeoff with realtime hero figure"
```

---

### Task 8: 更新 AGENTS.md RQ2 段与全量验证

**Files:**
- Modify: `AGENTS.md`（§RQ2 分析框架，把"主终点"改为"四轴权衡"，记录 smoothness/SPARC/hero 图）

**Interfaces:**
- Consumes: 前序全部改动。
- Produces: AGENTS.md 反映新事实；全量测试与编译通过。

- [ ] **Step 1: 更新 AGENTS.md RQ2 段**

在 `### RQ2 分析框架` 段：
- 把"动态主终点 `within_tolerance_valid_tracking_rate`"表述改为"RQ2 刻画四轴权衡（连续性、平滑度、延迟、精度）；`within_tolerance_valid_tracking_rate` 降级为精度轴的一项，不再是唯一主终点"。
- 在输出表清单加 `rq2_smoothness`（SPARC + jerk RMS，作用于 display 轨迹）。
- 记录 hero 图 `rq2_hero_trajectory_preliminary`（实时轨迹主图，单会话机制展示）。
- 记录 `paper.py` 重建，导出四轴指标到 `generated/rq2_results.typ`。
- 若旧条目描述"四组图为 rq2_accuracy_primary..."，更新为"主图为 rq2_hero_trajectory；辅助图保留 accuracy/paired/delay/envelope"。

- [ ] **Step 2: Python 全量单测**

Run: `cd EgoAnchor_Python && KMP_DUPLICATE_LIB_OK=TRUE pixi run python -m unittest discover -s src -p "test_*.py" -t src`
Expected: 全部 PASS（含新增 smoothness/plot/paper 测试）

- [ ] **Step 3: compileall 检查**

Run: `cd EgoAnchor_Python && pixi run python -m compileall src/egoanchor/eval/research/rq2`
Expected: 无语法错误

- [ ] **Step 4: Typst 编译**

Run: `cd p:/VSCode-Project/EgoAnchor && typst compile --root . 2026-EgoAnchor-Typst/egoanchor_cn_v6.typ 2026-EgoAnchor-Typst/pdf/egoanchor_cn_v6.pdf`
Expected: 无错误

- [ ] **Step 5: 提交**

```bash
git add AGENTS.md
git commit -m "docs(agents): record RQ2 four-axis tradeoff redesign and smoothness metrics"
```

---

## Self-Review

**Spec coverage:**
- §二 新主张（四轴权衡）→ Task 7 正文重写 ✓
- §三 四轴指标（SPARC + jerk 新增）→ Task 1 + Task 3 ✓；精度轴降级 → Task 7/8 ✓
- §四 realtime hero 图 → Task 4 + Task 5 ✓
- §五 保留辅助图/表、目标时刻诊断、`_preliminary` → 保留现有 `write_rq2_plots`，Task 7 保留免责 ✓
- §六 代码改动范围（smoothness.py / plot.py / pipeline.py / paper.py / __init__.py / AGENTS.md / typ）→ Task 1–8 全覆盖 ✓
- §七 论文正文重写 → Task 7 ✓
- §八 git 清理 → 已在计划前完成（会话中执行）✓
- §九 验证（单测、CLI 复跑、Typst 编译）→ Task 8 ✓
- §十 风险（SPARC 参数固定于单测、`_preliminary`、RQ2→RQ3 桥接）→ Task 1 固定参数、Task 7 桥接句 ✓

**Placeholder scan:** 无 TBD/TODO；所有代码步骤含完整代码。Task 3 Step 1 对 `_run` helper 有条件说明（因未读全 test_rq2_analyze.py），给出 fallback 指令。

**Type consistency:** `compute_smoothness_summary(output, session_id=...)`、`SMOOTHNESS_COLUMNS`、`write_rq2_hero_figure(output, output_dir, preliminary=)`、`build_rq2_typst_snapshot(tables)`、`write_rq2_typst(tables, path)` 在定义任务与消费任务间签名一致 ✓。变量命名 `rq2-{prefix}-{slug}-{suffix}` 在 Task 6 定义、Task 7 消费一致 ✓。
