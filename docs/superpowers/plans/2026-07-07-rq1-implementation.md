# RQ1 静态锚定质量 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 RQ1（静态锚定质量）完整评估链路——收窄 Unity 采集脚本到 2 个静止场景、加 Full vs No-StaticLock 双变体录制、新建复用共享引擎的 Python 分析薄封装，删除陈旧重复层。

**Architecture:** 保留已验证的契约层（Unity `EvalRecorder`/`EvalJson`/`EvalSession` ↔ Python `eval/io`）与共享分析引擎（`eval/core`/`eval/metrics`/`eval/report`）。RQ1 只做「场景语义收窄 + 论文视图组织」：Unity 侧把 `RQ1MetricType` 从 5 场景收到 2 场景并接第二个 baseline runtime；Python 侧新建 `eval/research/rq1/analyze.py` 薄封装，调 `load_session` → `compute_all_metrics` → 切片 → `eval/report` 出图表。

**Tech Stack:** C#（Unity 2022+，Meta XR SDK，TMPro，Input System）、Python 3.12（pandas/numpy/matplotlib，pixi 环境）、unittest、Typst 论文。

## Global Constraints

- 论文路径 `2026-EgoAnchor-Typst/`，Typst 语言，非 LaTeX；改后本机 `typst compile` 通过。（AGENTS #11）
- Python 按包级入口导入：包外 `from egoanchor.eval... import`，不深层导入；不写包级懒导出。（AGENTS #1）
- 代码充分中文说明；类/成员/方法补中文；每个 `.toml` 参数同行中文注释。（AGENTS #2）
- 重构不兼容旧代码/旧接口/旧路径；Unity 私有 `[SerializeField]` 改名直接迁移 `.unity`/`.prefab` YAML，不加 `FormerlySerializedAs`。（AGENTS #6、项目级要求）
- 不改契约层：`EvalRecorder`/`EvalJson`/`EvalSession`/`EvalLog` 与 Python `eval/io`；不动 `eval` 字段契约（`motion_model`/`smoothing_strategy`/`quality_gate`/`has_output_pose`/`output_pos`/`output_rot`/`latest_static_locked`）。
- 不到处写 `.md` 日志。（CLAUDE.md #2）
- RQ1 只静止场景（`static_observation`、`occlusion_recovery`）；slow/fast/rotation 属 RQ2，不在 RQ1。
- 实验表述规范：斜体标签 *Full* / *No-StaticLock*；不用「条件」描述配置，用「系统配置」或「变体」。
- 每次操作完更新 `AGENTS.md`。（AGENTS #10）
- 验证命令：Python 在 `EgoAnchor_Python` 跑 `pixi run python -m unittest discover -s src -p "test_*.py" -t src`、`pixi run python -m compileall src`；Unity 在仓库根 `dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore`。

---

## 文件结构

**删除**
- `EgoAnchor_Python/src/egoanchor/eval/research/rq1/{data_loader,gt_alignment,metrics,plot_compact,plot_comprehensive,run_analysis,run_rq1}.py` 及 `__pycache__`
- `EgoAnchor_Python/RQ1_ANALYSIS_DESIGN.md`、`RQ1_COMPLETE_REPORT.md`、`RQ1_PAPER_UPDATE.md`、`analyze_rq1_data_quality.py`
- `2026-EgoAnchor-Typst/figs/rq1/fig_rq1_compact.{pdf,png}`、`fig_rq1_comprehensive.{pdf,png}`

**修改**
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ1/RQ1MetricType.cs` — 5→2 场景
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ1/RQ1InputHandler.cs` — 按键 1/2/0/F7/F8
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ1/RQ1StatusUI.cs` — 对照表 2 场景
- `EgoAnchor_Unity/Assets/Scene/EgoAnchor-RQ1.unity` — 第二个 baseline runtime + recorder variants[1]（Unity MCP 操作）
- `AGENTS.md` — 更新 RQ1 分析框架描述

**新建**
- `EgoAnchor_Python/src/egoanchor/eval/research/rq1/analyze.py` — RQ1 分析薄封装 + CLI
- `EgoAnchor_Python/src/egoanchor/eval/tests/test_rq1_analyze.py` — analyze 单测

---

## Task 1: Python — 删除陈旧 rq1 层

**Files:**
- Delete: `EgoAnchor_Python/src/egoanchor/eval/research/rq1/data_loader.py`
- Delete: `EgoAnchor_Python/src/egoanchor/eval/research/rq1/gt_alignment.py`
- Delete: `EgoAnchor_Python/src/egoanchor/eval/research/rq1/metrics.py`
- Delete: `EgoAnchor_Python/src/egoanchor/eval/research/rq1/plot_compact.py`
- Delete: `EgoAnchor_Python/src/egoanchor/eval/research/rq1/plot_comprehensive.py`
- Delete: `EgoAnchor_Python/src/egoanchor/eval/research/rq1/run_analysis.py`
- Delete: `EgoAnchor_Python/src/egoanchor/eval/research/rq1/run_rq1.py`
- Delete: `EgoAnchor_Python/RQ1_ANALYSIS_DESIGN.md`, `RQ1_COMPLETE_REPORT.md`, `RQ1_PAPER_UPDATE.md`, `analyze_rq1_data_quality.py`
- Delete: `2026-EgoAnchor-Typst/figs/rq1/fig_rq1_compact.{pdf,png}`, `fig_rq1_comprehensive.{pdf,png}`
- Keep: `EgoAnchor_Python/src/egoanchor/eval/research/rq1/__init__.py`（下一 Task 复用）

**Interfaces:**
- Consumes: 无
- Produces: 空的 `rq1/` 包（只剩 `__init__.py`），供 Task 5 放 `analyze.py`

- [ ] **Step 1: 确认无外部引用**

Run: `cd EgoAnchor_Python && pixi run python -c "import egoanchor.eval; print('ok')"`
Expected: 打印 `ok`（说明 `eval` 包不依赖将删的 rq1 模块）

再 grep 确认没有其它模块 import 这些文件：

Run: `cd EgoAnchor_Python && grep -rn "research.rq1.data_loader\|research.rq1.gt_alignment\|research.rq1.metrics\|research.rq1.plot\|research.rq1.run_" src --include=*.py`
Expected: 只匹配到 `run_analysis.py` 自身内部 import（将被删），无其它调用方

- [ ] **Step 2: 删除文件**

```bash
cd EgoAnchor_Python
rm src/egoanchor/eval/research/rq1/data_loader.py
rm src/egoanchor/eval/research/rq1/gt_alignment.py
rm src/egoanchor/eval/research/rq1/metrics.py
rm src/egoanchor/eval/research/rq1/plot_compact.py
rm src/egoanchor/eval/research/rq1/plot_comprehensive.py
rm src/egoanchor/eval/research/rq1/run_analysis.py
rm src/egoanchor/eval/research/rq1/run_rq1.py
rm -rf src/egoanchor/eval/research/rq1/__pycache__
rm -f RQ1_ANALYSIS_DESIGN.md RQ1_COMPLETE_REPORT.md RQ1_PAPER_UPDATE.md analyze_rq1_data_quality.py
cd ..
rm -f "2026-EgoAnchor-Typst/figs/rq1/fig_rq1_compact.pdf" "2026-EgoAnchor-Typst/figs/rq1/fig_rq1_compact.png"
rm -f "2026-EgoAnchor-Typst/figs/rq1/fig_rq1_comprehensive.pdf" "2026-EgoAnchor-Typst/figs/rq1/fig_rq1_comprehensive.png"
```

- [ ] **Step 3: 确认 `__init__.py` 保留且包仍可导入**

Run: `cd EgoAnchor_Python && pixi run python -c "import egoanchor.eval.research.rq1; print('ok')"`
Expected: 打印 `ok`

- [ ] **Step 4: 全量测试确认无回归**

Run: `cd EgoAnchor_Python && pixi run python -m unittest discover -s src -p "test_*.py" -t src`
Expected: OK（无 import error，删除未破坏现有测试）

- [ ] **Step 5: Commit**

```bash
git add -A EgoAnchor_Python/src/egoanchor/eval/research/rq1 EgoAnchor_Python/RQ1_ANALYSIS_DESIGN.md EgoAnchor_Python/RQ1_COMPLETE_REPORT.md EgoAnchor_Python/RQ1_PAPER_UPDATE.md EgoAnchor_Python/analyze_rq1_data_quality.py "2026-EgoAnchor-Typst/figs/rq1"
git commit -m "chore(rq1): 删除陈旧的 rq1 重复分析层与旧产物

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Unity — `RQ1MetricType` 收窄到 2 场景

**Files:**
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ1/RQ1MetricType.cs`

**Interfaces:**
- Consumes: 无
- Produces: `RQ1MetricType { None=0, StaticObservation=1, OcclusionRecovery=2 }`；扩展方法 `ToLogString()`（返回 `"none"`/`"static_observation"`/`"occlusion_recovery"`）、`GetDisplayName()`、`GetDescription()`、`GetSuggestedDuration()`。供 Task 3/4 使用。

- [ ] **Step 1: 重写枚举与扩展方法**

替换整个文件内容为：

```csharp
namespace EgoAnchor.Eval.RQ1
{
    /// <summary>
    /// RQ1 评估场景类型枚举（对齐论文 egoanchor_cn_v5.typ 2026-07-07 定稿的 RQ1 结构）。
    /// <para>
    /// RQ1 只评估静止场景，共两种：<br/>
    /// 1. 长时静止观察：控制器静置桌面，用户正常头部运动<br/>
    /// 2. 遮挡恢复：用户手部遮挡目标后移开<br/>
    /// 慢速平移 / 快速挥动 / 旋转已移交 RQ2，不在 RQ1 采集。
    /// </para>
    /// </summary>
    public enum RQ1MetricType
    {
        /// <summary>无标记。</summary>
        None = 0,

        /// <summary>长时静止观察：控制器静置桌面，用户正常头部运动。</summary>
        StaticObservation = 1,

        /// <summary>遮挡恢复：用户手部遮挡目标后移开，重复若干次。</summary>
        OcclusionRecovery = 2
    }

    /// <summary>
    /// RQ1MetricType 扩展方法。
    /// </summary>
    public static class RQ1MetricTypeExtensions
    {
        /// <summary>转换为日志字段字符串（snake_case），与 Python 侧场景标签一致。</summary>
        public static string ToLogString(this RQ1MetricType type)
        {
            return type switch
            {
                RQ1MetricType.StaticObservation => "static_observation",
                RQ1MetricType.OcclusionRecovery => "occlusion_recovery",
                _ => "none"
            };
        }

        /// <summary>获取建议时长（秒）；遮挡恢复为单次事件返回 0。</summary>
        public static int GetSuggestedDuration(this RQ1MetricType type)
        {
            return type switch
            {
                RQ1MetricType.StaticObservation => 80,
                RQ1MetricType.OcclusionRecovery => 0,
                _ => 0
            };
        }

        /// <summary>获取显示名称。</summary>
        public static string GetDisplayName(this RQ1MetricType type)
        {
            return type switch
            {
                RQ1MetricType.StaticObservation => "Static",
                RQ1MetricType.OcclusionRecovery => "Occlusion",
                _ => "None"
            };
        }

        /// <summary>获取描述信息。</summary>
        public static string GetDescription(this RQ1MetricType type)
        {
            return type switch
            {
                RQ1MetricType.StaticObservation => "Static on table, normal head movement",
                RQ1MetricType.OcclusionRecovery => "Occlude target then reveal, repeat",
                _ => ""
            };
        }
    }
}
```

- [ ] **Step 2: 编译验证**

Run: `dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore`
Expected: 报错——`RQ1InputHandler.cs`/`RQ1StatusUI.cs` 仍引用已删的 `SlowTranslation`/`FastMotion`/`Rotation`。这确认了后续 Task 3/4 的必要性；先记录错误位置，不要在本 Task 修复它们。

> 注：本 Task 单独编译会失败是预期的，因为 3/4 场景引用还在。Task 2/3/4 是一组连续改动，编译门放在 Task 4 末尾。若使用 subagent 逐任务执行，Task 2 只做本文件改动并提交，编译门延后。

- [ ] **Step 3: Commit**

```bash
git add EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ1/RQ1MetricType.cs
git commit -m "refactor(rq1): RQ1MetricType 收窄为 static/occlusion 两场景

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Unity — `RQ1InputHandler` 按键收窄

**Files:**
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ1/RQ1InputHandler.cs`

**Interfaces:**
- Consumes: `RQ1MetricType.StaticObservation`/`OcclusionRecovery`（Task 2）；`RQ1MetricSelector.SetMetric`/`ClearMetric`；`EvalSession.StartSession`/`StopSession`
- Produces: 按键映射 1=StaticObservation、2=OcclusionRecovery、0=Clear、F7=Start、F8=Stop

- [ ] **Step 1: 删除 metric3/4/5 的 action 字段与回调**

在 `RQ1InputHandler.cs` 中删除 `metric3Action`、`metric4Action`、`metric5Action` 三个 `[SerializeField]` 字段（含其 `[Tooltip]`）。保留 `metric1Action`、`metric2Action`、`clearMetricAction`、`startRecordingAction`、`stopRecordingAction`。

把 `metric2Action` 的 Tooltip 从 `"Set metric: Slow Translation"` 改为 `"Set metric: Occlusion Recovery"`。

- [ ] **Step 2: 更新 OnEnable 回调注册**

把 `OnEnable()` 中的回调注册段改为：

```csharp
            // Register callbacks
            metric1Action.performed += _ => selector?.SetMetric(RQ1MetricType.StaticObservation);
            metric2Action.performed += _ => selector?.SetMetric(RQ1MetricType.OcclusionRecovery);
            clearMetricAction.performed += _ => selector?.ClearMetric();
            startRecordingAction.performed += _ => evalSession?.StartSession();
            stopRecordingAction.performed += _ => evalSession?.StopSession();

            // Enable all actions
            metric1Action.Enable();
            metric2Action.Enable();
            clearMetricAction.Enable();
            startRecordingAction.Enable();
            stopRecordingAction.Enable();
```

- [ ] **Step 3: 更新 OnDisable**

把 `OnDisable()` 改为只 Disable 保留的 action：

```csharp
        private void OnDisable()
        {
            // Disable all actions
            metric1Action.Disable();
            metric2Action.Disable();
            clearMetricAction.Disable();
            startRecordingAction.Disable();
            stopRecordingAction.Disable();
        }
```

- [ ] **Step 4: Commit**

```bash
git add EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ1/RQ1InputHandler.cs
git commit -m "refactor(rq1): RQ1InputHandler 按键收窄到 1/2/0/F7/F8

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Unity — `RQ1StatusUI` 对照表收窄 + 编译门

**Files:**
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ1/RQ1StatusUI.cs`

**Interfaces:**
- Consumes: `RQ1MetricType`（Task 2）
- Produces: 按键对照表只列 2 场景

- [ ] **Step 1: 更新 UpdateKeyBindings 的对照表**

把 `UpdateKeyBindings()` 方法体中的 `AppendMetricRow` 调用段替换为：

```csharp
            AppendMetricRow(sb, "[1]", RQ1MetricType.StaticObservation, "80s",    active);
            AppendMetricRow(sb, "[2]", RQ1MetricType.OcclusionRecovery, "Single", active);
            sb.AppendLine();
            sb.AppendLine("[0]  Clear Marking");
            sb.Append("[F7] Start Recording   [F8] Stop Recording");
```

删除原来对 `SlowTranslation`/`FastMotion`/`Rotation` 的三行 `AppendMetricRow` 调用。

- [ ] **Step 2: 全量编译门**

Run: `dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore`
Expected: Build succeeded, 0 Error（Task 2/3/4 合起来消除了所有 3/4/5 场景引用）

- [ ] **Step 3: Commit**

```bash
git add EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ1/RQ1StatusUI.cs
git commit -m "refactor(rq1): RQ1StatusUI 对照表收窄到 2 场景

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Python — `analyze.py` 场景切片与恢复事件合成（TDD）

**Files:**
- Create: `EgoAnchor_Python/src/egoanchor/eval/research/rq1/analyze.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/tests/test_rq1_analyze.py`

**Interfaces:**
- Consumes:
  - `from egoanchor.eval.io import load_session, SessionLogs`（`SessionLogs.output` 有 `rq1_metric`/`render_mono_ms` 列；`SessionLogs.manifest` 是 dict）
  - `from egoanchor.eval.metrics import compute_all_metrics`（返回 `MetricsResult`，`.tables` dict 键含 `anchor_error_summary`/`jitter_summary`/`slip_summary`/`latency_summary`/`recovery_summary`）
  - anchor_error_summary 列：`condition,label,n,translation_rmse_m,translation_median_m,translation_p95_m,rotation_rmse_deg,rotation_median_deg,rotation_p95_deg`
  - jitter_summary 列：`condition,label,n,position_jitter_rms_m,position_jitter_std_m,rotation_jitter_rms_deg,insufficient_data`
  - slip_summary 列：`condition,label,n,slip_rms_px,slip_peak_px,insufficient_data`
  - latency_summary 含：`condition,label,capture_to_apply_p50_ms,capture_to_apply_p95_ms,perception_total_p50_ms,...`
  - recovery_summary 列：`event_type,event_mono_ms,condition,label,recovery_time_ms,threshold_m,insufficient_data`
- Produces:
  - `RQ1_CONDITIONS = ("static_observation", "occlusion_recovery")`
  - `synthesize_occlusion_markers(output: pd.DataFrame) -> list[dict]` — 从 `rq1_metric=="occlusion_recovery"` 连续段起点合成 `[{"type": "occlusion_recovery", "mono_ms": <段首 render_mono_ms>}, ...]`
  - `filter_rq1_tables(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]` — 每张 summary 表按 `condition ∈ RQ1_CONDITIONS` 过滤
  - `run_rq1_analysis(session_dir, *, figs_dir=None) -> dict` — 全链路：load → 合成 markers 注入 manifest → compute → 过滤 → 返回 RQ1 tables dict
  - `main(argv=None) -> int` — CLI（`--session-dir`、可选 `--figs-dir`）

- [ ] **Step 1: 写失败测试（marker 合成）**

创建 `EgoAnchor_Python/src/egoanchor/eval/tests/test_rq1_analyze.py`：

```python
"""RQ1 analyze 薄封装测试。"""

from __future__ import annotations

import unittest

import pandas as pd

from egoanchor.eval.research.rq1.analyze import (
    RQ1_CONDITIONS,
    filter_rq1_tables,
    synthesize_occlusion_markers,
)


class SynthesizeOcclusionMarkersTest(unittest.TestCase):
    """从 rq1_metric 段起点合成遮挡事件 marker。"""

    def test_one_marker_per_contiguous_occlusion_run(self) -> None:
        """每个连续 occlusion_recovery 段生成一个 marker，mono_ms 取段首。"""

        output = pd.DataFrame(
            {
                "render_mono_ms": [0.0, 10.0, 20.0, 30.0, 40.0, 50.0],
                "rq1_metric": [
                    "static_observation",
                    "occlusion_recovery",
                    "occlusion_recovery",
                    "none",
                    "occlusion_recovery",
                    "occlusion_recovery",
                ],
            }
        )

        markers = synthesize_occlusion_markers(output)

        self.assertEqual(len(markers), 2)
        self.assertEqual(markers[0]["type"], "occlusion_recovery")
        self.assertAlmostEqual(markers[0]["mono_ms"], 10.0)
        self.assertAlmostEqual(markers[1]["mono_ms"], 40.0)

    def test_no_occlusion_returns_empty(self) -> None:
        """无遮挡段时返回空列表。"""

        output = pd.DataFrame(
            {"render_mono_ms": [0.0, 10.0], "rq1_metric": ["static_observation", "none"]}
        )
        self.assertEqual(synthesize_occlusion_markers(output), [])

    def test_missing_column_returns_empty(self) -> None:
        """缺少 rq1_metric 列时返回空列表，不抛异常。"""

        output = pd.DataFrame({"render_mono_ms": [0.0, 10.0]})
        self.assertEqual(synthesize_occlusion_markers(output), [])


class FilterRq1TablesTest(unittest.TestCase):
    """RQ1 只保留 static_observation / occlusion_recovery 场景行。"""

    def test_keeps_only_rq1_conditions(self) -> None:
        """过滤掉非 RQ1 场景（如 slow_translation）。"""

        tables = {
            "anchor_error_summary": pd.DataFrame(
                {
                    "condition": ["static_observation", "slow_translation", "occlusion_recovery"],
                    "label": ["Full", "Full", "Full"],
                    "translation_median_m": [0.006, 0.03, 0.004],
                }
            ),
            "jitter_summary": pd.DataFrame(
                {"condition": ["static_observation", "rotation"], "label": ["Full", "Full"], "position_jitter_rms_m": [0.0004, 0.01]}
            ),
        }

        filtered = filter_rq1_tables(tables)

        self.assertEqual(set(filtered["anchor_error_summary"]["condition"]), set(RQ1_CONDITIONS) & {"static_observation", "occlusion_recovery"})
        self.assertNotIn("slow_translation", set(filtered["anchor_error_summary"]["condition"]))
        self.assertNotIn("rotation", set(filtered["jitter_summary"]["condition"]))

    def test_table_without_condition_column_passes_through(self) -> None:
        """没有 condition 列的表原样保留。"""

        tables = {"misc": pd.DataFrame({"x": [1, 2]})}
        filtered = filter_rq1_tables(tables)
        self.assertEqual(len(filtered["misc"]), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd EgoAnchor_Python && pixi run python -m unittest egoanchor.eval.tests.test_rq1_analyze -v`
Expected: FAIL — `ModuleNotFoundError` 或 `ImportError`（`analyze` 尚不存在）

- [ ] **Step 3: 写 analyze.py 最小实现**

创建 `EgoAnchor_Python/src/egoanchor/eval/research/rq1/analyze.py`：

```python
"""RQ1（静态锚定质量）分析薄封装。

本模块不重算任何指标：调用共享引擎 :func:`egoanchor.eval.metrics.compute_all_metrics`
产出全部指标，再按 RQ1 关注的静止场景（``static_observation``、``occlusion_recovery``）
过滤，并把 *Full* vs *No-StaticLock* 双变体逐场景对比组织成论文视图。

遮挡恢复恢复时间依赖 ``manifest.event_markers``，而 Unity 契约层当前恒写空数组；
因此本模块从 ``rq1_metric == "occlusion_recovery"`` 段的起始时刻在内存合成 marker，
注入临时 manifest 后再交给共享引擎的 recovery 指标，无需改动契约层。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    # 直接执行本脚本时，把 src/ 加入 sys.path 以解析 egoanchor 包。
    # 本文件位于 src/egoanchor/eval/research/rq1/analyze.py，src = parents[4]。
    _package_root = Path(__file__).resolve().parents[4]
    if str(_package_root) not in sys.path:
        sys.path.insert(0, str(_package_root))

from egoanchor.eval.io import SessionLogs, load_session
from egoanchor.eval.metrics import compute_all_metrics
from egoanchor.eval.report import write_figures, write_sanity, write_tables


# RQ1 只评估静止场景；slow/fast/rotation 属 RQ2。
RQ1_CONDITIONS: tuple[str, ...] = ("static_observation", "occlusion_recovery")

# 论文图导出默认目录（相对仓库根）。
DEFAULT_FIGS_DIR = Path("2026-EgoAnchor-Typst/figs/rq1")


def synthesize_occlusion_markers(output: pd.DataFrame) -> list[dict[str, Any]]:
    """从 ``rq1_metric == "occlusion_recovery"`` 连续段起点合成事件 marker。

    每个连续遮挡段生成一个 ``{"type": "occlusion_recovery", "mono_ms": <段首 render_mono_ms>}``，
    供 :func:`egoanchor.eval.metrics.recovery.compute_recovery` 计算恢复时间。

    Args:
        output: 含 ``rq1_metric`` 与 ``render_mono_ms`` 列的 output 长表。

    Returns:
        marker 字典列表，按时间升序；无遮挡段或缺列时返回空列表。
    """

    if output.empty or "rq1_metric" not in output.columns or "render_mono_ms" not in output.columns:
        return []

    work = output.sort_values("render_mono_ms").copy()
    metric = work["rq1_metric"].fillna("none").astype(str)
    run_id = (metric != metric.shift()).cumsum()

    markers: list[dict[str, Any]] = []
    for _, group in work.groupby(run_id, sort=False):
        if str(group["rq1_metric"].iloc[0]) != "occlusion_recovery":
            continue
        markers.append(
            {"type": "occlusion_recovery", "mono_ms": float(group["render_mono_ms"].iloc[0])}
        )
    return markers


def filter_rq1_tables(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """把每张含 ``condition`` 列的表过滤到 RQ1 场景；无该列的表原样保留。"""

    filtered: dict[str, pd.DataFrame] = {}
    for name, table in tables.items():
        if isinstance(table, pd.DataFrame) and "condition" in table.columns:
            filtered[name] = table[table["condition"].isin(RQ1_CONDITIONS)].reset_index(drop=True)
        else:
            filtered[name] = table
    return filtered


def _inject_markers(logs: SessionLogs) -> SessionLogs:
    """把合成的遮挡 marker 注入 manifest 的 event_markers（不改原 logs 引用）。"""

    markers = synthesize_occlusion_markers(logs.output)
    if not markers:
        return logs
    manifest = dict(logs.manifest)
    manifest["event_markers"] = list(manifest.get("event_markers", [])) + markers
    return SessionLogs(capture=logs.capture, output=logs.output, pose=logs.pose, manifest=manifest)


def run_rq1_analysis(
    session_dir: Path | str,
    *,
    report_dir: Path | str | None = None,
    figs_dir: Path | str | None = None,
) -> dict[str, pd.DataFrame]:
    """运行 RQ1 全链路分析：加载 → 合成遮挡 marker → 计算 → 过滤 → 导出。

    Args:
        session_dir: ``data/eval/<session_id>`` 目录。
        report_dir: CSV/summary 输出目录，默认 ``<session_dir>/report``。
        figs_dir: 论文图输出目录，默认仓库根 ``2026-EgoAnchor-Typst/figs/rq1``。

    Returns:
        过滤到 RQ1 场景后的 tables dict。
    """

    session_path = Path(session_dir)
    logs = _inject_markers(load_session(session_path))
    result = compute_all_metrics(logs)

    out_report = Path(report_dir) if report_dir is not None else session_path / "report"
    write_tables(result, out_report)
    write_sanity(result, out_report)

    figs = Path(figs_dir) if figs_dir is not None else DEFAULT_FIGS_DIR
    write_figures(result, figs)

    return filter_rq1_tables(result.tables)


def main(argv: list[str] | None = None) -> int:
    """CLI 主函数。"""

    parser = argparse.ArgumentParser(description="Run EgoAnchor RQ1 static anchoring analysis.")
    parser.add_argument("--session-dir", required=True, help="data/eval/<session_id> 目录。")
    parser.add_argument("--report-dir", default=None, help="可选 report 输出目录，默认 <session_dir>/report。")
    parser.add_argument("--figs-dir", default=None, help="可选论文图目录，默认 2026-EgoAnchor-Typst/figs/rq1。")
    args = parser.parse_args(argv)

    tables = run_rq1_analysis(
        Path(args.session_dir),
        report_dir=Path(args.report_dir) if args.report_dir else None,
        figs_dir=Path(args.figs_dir) if args.figs_dir else None,
    )

    accuracy = tables.get("anchor_error_summary", pd.DataFrame())
    print("RQ1 anchor_error_summary (static scenes, Full vs No-StaticLock):")
    print(accuracy.to_string(index=False) if not accuracy.empty else "  <no data>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd EgoAnchor_Python && pixi run python -m unittest egoanchor.eval.tests.test_rq1_analyze -v`
Expected: OK（3+2 个测试通过）

- [ ] **Step 5: compileall + 全量测试**

Run: `cd EgoAnchor_Python && pixi run python -m compileall src/egoanchor/eval/research/rq1/analyze.py && pixi run python -m unittest discover -s src -p "test_*.py" -t src`
Expected: 两条都 OK

- [ ] **Step 6: Commit**

```bash
git add EgoAnchor_Python/src/egoanchor/eval/research/rq1/analyze.py EgoAnchor_Python/src/egoanchor/eval/tests/test_rq1_analyze.py
git commit -m "feat(rq1): 新增复用共享引擎的 RQ1 分析薄封装

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Python — 用真实 session 冒烟 analyze

**Files:**
- 无代码改动（冒烟验证）

**Interfaces:**
- Consumes: `run_rq1_analysis`（Task 5）；现有 session `EgoAnchor_Python/data/eval/20260706_163825_controller_right`

- [ ] **Step 1: 确认 session 存在**

Run: `ls EgoAnchor_Python/data/eval/20260706_163825_controller_right/*.jsonl`
Expected: 列出 `_unity_capture.jsonl`、`_unity_output.jsonl`、`_python_runtime.jsonl`

> 若该 session 不存在（可能已在别处清理），跳过本 Task，改为在 Task 8 采集真机数据后首次运行 analyze 作为冒烟。

- [ ] **Step 2: 跑 analyze CLI**

Run: `cd EgoAnchor_Python && pixi run python -m egoanchor.eval.research.rq1.analyze --session-dir data/eval/20260706_163825_controller_right --figs-dir data/eval/20260706_163825_controller_right/rq1_smoke_figs`
Expected: 打印 `RQ1 anchor_error_summary (...)` 表；无异常退出（exit 0）。注意：该旧 session 场景标注可能仍是旧 5 场景，过滤后只保留 static_observation/occlusion_recovery 行——可能为空，属正常，只验证链路不崩。

- [ ] **Step 3: 清理冒烟产物**

```bash
rm -rf EgoAnchor_Python/data/eval/20260706_163825_controller_right/rq1_smoke_figs
```

- [ ] **Step 4: 无需 commit（无代码改动）**

---

## Task 7: Unity — `EgoAnchor-RQ1.unity` 双变体接线（Unity MCP）

**Files:**
- Modify: `EgoAnchor_Unity/Assets/Scene/EgoAnchor-RQ1.unity`（经 Unity 编辑器/MCP 保存）

**Interfaces:**
- Consumes: 现有 primary `PoseToAnchorRuntime`（Full）、`EvalRecorder.variants`、`EgoAnchorStaticLockModule`
- Produces: 场景内两个 runtime + recorder variants[0]=Full(primary)/variants[1]=No-StaticLock

> 本 Task 是交互式 Unity 操作，由主 agent 用 Unity MCP 逐步执行并核对，不适合 subagent 盲跑。每步操作后用 `find_gameobjects` / components 资源核对。

- [ ] **Step 1: 盘点现有 RQ1 场景结构**

用 `find_gameobjects`（by_component `PoseToAnchorRuntime`、`EvalRecorder`、`EgoAnchorStaticLockModule`、`DynamicObjectAnchor`）确认当前只有一个 runtime，记录其 GameObject 名、锚点 Transform 名、StaticLock 模块参数。

- [ ] **Step 2: 复制出 baseline runtime 分支**

复制 Full 的 runtime GameObject 及其 anchor Transform 子树为一份 baseline（命名如 `AnchorRuntime_NoStaticLock` / `DynamicObjectAnchor_NoStaticLock`）。baseline 订阅同一 pose 流（同 `AnchorRuntimeHub`），motion model × smoothing strategy 与 Full 完全一致。

- [ ] **Step 3: 关闭 baseline 的静止锚定**

baseline 分支上把 `EgoAnchorStaticLockModule.lockEnabled` 设为 `false`（或移除该模块）。其余 policy 参数保持与 Full 逐项相同。

- [ ] **Step 4: 接线 recorder variants**

`EvalRecorder.variants` 设为 2 项：
- `variants[0]`: `label="Full"`, `isPrimary=true`, runtime=Full runtime, anchorTransform=Full 锚点
- `variants[1]`: `label="No-StaticLock"`, `isPrimary=false`, runtime=baseline runtime, anchorTransform=baseline 锚点

- [ ] **Step 5: 核对实时面板与输入接线**

确认 `RQ1LiveStats.recorder` 指向该 `EvalRecorder`（primary 即 Full）；`RQ1InputHandler` 的 metric1/metric2/clear/start/stop action 有键位绑定（1/2/0/F7/F8），`RQ1StatusUI` 引用 selector 与 session。

- [ ] **Step 6: 保存场景 + Play 冒烟**

保存场景。进入 Play（连 Quest Link 或有 pose 源时）：观察实时面板刷新；观察 `unity_output` 每行 variants 数组含 `Full` 与 `No-StaticLock` 两个 label（可短录一段后 `grep '"label":"No-StaticLock"'` 确认）。

- [ ] **Step 7: Commit**

```bash
git add EgoAnchor_Unity/Assets/Scene/EgoAnchor-RQ1.unity
git commit -m "feat(rq1): RQ1 场景加 No-StaticLock baseline 双变体录制

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: 采集真机数据（用户执行）

**Files:** 无代码改动

- [ ] **Step 1:** 启动 Python server：`cd EgoAnchor_Python && pixi run python .\src\run_server.py --object controller_right`（`eval_session_enabled=true`）
- [ ] **Step 2:** Unity 进 `EgoAnchor-RQ1.unity` Play；`autoStart` 收首个 PoseResult 自动录制并复用 Python session_id
- [ ] **Step 3:** 按 **1** 标注长时静止观察段（控制器静置桌面、正常头动，约 60–80s）
- [ ] **Step 4:** 按 **2** 标注遮挡恢复段：遮挡目标再移开，重复若干次
- [ ] **Step 5:** F8 停止，写 manifest。数据落 `EgoAnchor_Python/data/eval/<session_id>/`
- [ ] **Step 6:** 告知主 agent session_id，进入 Task 9

---

## Task 9: 分析真机数据 + 论文更新 + 绘图

**Files:**
- Modify: `2026-EgoAnchor-Typst/egoanchor_cn_v5.typ`（§6.1，约 337–357 行）
- Create: `2026-EgoAnchor-Typst/figs/rq1/*.{pdf,png}`（analyze 产出）

**Interfaces:**
- Consumes: Task 8 的 `<session_id>`；`run_rq1_analysis`（Task 5）

- [ ] **Step 1: 跑 RQ1 分析**

Run: `cd EgoAnchor_Python && pixi run python -m egoanchor.eval.research.rq1.analyze --session-dir data/eval/<session_id>`
Expected: 打印 anchor_error_summary（含 static_observation 与 occlusion_recovery × Full/No-StaticLock 行）；`report/` 出 CSV/summary；`figs/rq1/` 出图

- [ ] **Step 2: 记录关键实测值**

从 `report/` 读出：static_observation 的 `translation_median_m`/`translation_p95_m`、`rotation_median_deg`/`rotation_p95_deg`；`jitter_summary` 的 Full vs No-StaticLock `position_jitter_rms_m`；`slip_summary` 的 `slip_rms_px`；`recovery_summary` 的 occlusion `recovery_time_ms`；`latency_summary` 的 `capture_to_apply_p50_ms`。

- [ ] **Step 3: 更新论文 §6.1 占位符**

在 `egoanchor_cn_v5.typ` §6.1（337–357 行）用实测值替换 X/Y/Z/W 占位符：绝对精度、静止抖动 Full vs No-StaticLock、屏幕漂移、遮挡恢复时间。使用斜体 *Full* / *No-StaticLock*，「系统配置/变体」表述，不用「条件」。

- [ ] **Step 4: 替换图 placeholder**

把 `<fig:rq1-static>` 的 `#box(... Figure placeholder ...)` 换成 `#image("figs/rq1/<figure>.pdf", ...)`，图内容：(A) 长期稳定性误差时间线、(B) Full vs No-StaticLock 抖动+屏幕漂移对比、(C) 遮挡恢复误差曲线。若共享引擎默认图不满足 2×2 论文排版，在 analyze.py 增补一个 RQ1 专用组图函数（仍只消费已算好的 tables，不重算指标），补对应测试。

- [ ] **Step 5: Typst 编译验证**

Run: `typst compile --root . .\2026-EgoAnchor-Typst\egoanchor_cn_v5.typ .\2026-EgoAnchor-Typst\pdf\egoanchor_cn_v5.pdf`
Expected: 编译成功，无 error；PDF 生成

- [ ] **Step 6: Commit**

```bash
git add "2026-EgoAnchor-Typst/egoanchor_cn_v5.typ" "2026-EgoAnchor-Typst/figs/rq1" EgoAnchor_Python/data/eval/<session_id>/report
git commit -m "docs(rq1): 用实测数据更新 §6.1 与静态锚定质量图

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: 更新 AGENTS.md

**Files:**
- Modify: `AGENTS.md`（RQ1 分析框架章节，约 236–293 行）

**Interfaces:**
- Consumes: 前序所有 Task 的最终事实

- [ ] **Step 1: 重写 RQ1 分析框架描述**

把 AGENTS.md 中「RQ1 分析框架」相关段落更新为当前事实：
- RQ1 只 2 场景（static_observation/occlusion_recovery），slow/fast/rotation 属 RQ2
- 分析入口：`eval/research/rq1/analyze.py`（薄封装，复用 `eval/core|metrics|report`），删除旧 `data_loader/gt_alignment/metrics/plot_*/run_analysis/run_rq1`
- 消融：Full vs No-StaticLock 双变体同帧录制（recorder variants[0]/[1]）
- 遮挡 marker 由 analyze 从 `rq1_metric` 段起点内存合成，不改契约层
- 运行命令：`pixi run python -m egoanchor.eval.research.rq1.analyze --session-dir ...`
- 删除对旧 `RQ1MetricType` 5 场景、旧 `run_rq1.py`/`analyze.py`（单 session）链路的描述

保留仍然成立的历史坑条目（GT keep-alive、`gt_pose_valid` 信任、`EvalSession` 单一录制真理、`RQ1MetricSelector` 不自持录制状态等）。

- [ ] **Step 2: Commit**

```bash
git add AGENTS.md
git commit -m "docs: 更新 AGENTS.md RQ1 分析框架为当前实现

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec 覆盖：**
- 删除陈旧层 → Task 1 ✓
- RQ1MetricType 5→2 → Task 2 ✓
- RQ1InputHandler 按键收窄 → Task 3 ✓
- RQ1StatusUI 对照表收窄 → Task 4 ✓
- analyze.py 薄封装（切片+marker 合成） → Task 5 ✓
- 遮挡事件 marker 合成（真实缺口） → Task 5（`synthesize_occlusion_markers`）✓
- 真实 session 冒烟 → Task 6 ✓
- 场景双变体接线 → Task 7 ✓
- 采集工作流 → Task 8 ✓
- 论文更新 + 绘图 + typst 编译 → Task 9 ✓
- 保留契约层/共享引擎/RQ1LiveStats → 无删除任务触及，约束已写入 Global Constraints ✓
- RQ2/RQ3 铺路 → analyze 只做过滤+视图组织，通用能力留引擎（Task 5 设计）✓
- AGENTS.md 更新 → Task 10 ✓

**占位符扫描：** 无 TBD/TODO；除用户真机数据的 `<session_id>` 与实测数值（Task 8/9 本质依赖运行时数据，已标注来源）外，代码步骤均含完整实现。

**类型一致性：** `synthesize_occlusion_markers`/`filter_rq1_tables`/`run_rq1_analysis`/`RQ1_CONDITIONS`/`main` 在 Task 5 定义并在测试与 CLI 中一致引用；`SessionLogs` 字段（capture/output/pose/manifest）与 `eval/io` 定义一致；summary 表列名均取自实际源码（anchor_error/jitter/slip/latency/recovery）。`RQ1MetricType` 成员（None/StaticObservation/OcclusionRecovery）在 Task 2 定义，Task 3/4 一致引用。
