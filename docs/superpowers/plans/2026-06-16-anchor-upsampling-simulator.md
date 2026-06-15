# Anchor Upsampling Simulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `EgoAnchor_Tools` 中新增一个 C# baseline 离线实时模拟器，用已录 Unity aligned raw pose 按约 5fps 输入，并按日志中真实 `render_mono_ms` 时间轴生成连续 render pose，输出各 baseline 曲线和摘要。

**Architecture:** 工具只读取 eval JSONL，不修改 Unity runtime。输入观测只取 primary variant 的 `aligned_raw_pos/aligned_raw_rot/source_capture_mono_ms/reliability_score`，按 `source_frame_id` 去重后按时间送入算法；render loop 优先逐帧复用 Unity 日志中的 `render_mono_ms`，保留真实非均匀约 60fps 时间轴，每帧只调用 baseline 的实时 `PredictAt(renderTime)`。输出包括 JSONL、CSV、SVG 曲线和算法说明。EgoAnchor/pose score 优化先不实现，等 baseline 曲线结果出来后再设计。

**Tech Stack:** .NET 8 C# console、UnityEngine `Vector3/Pose/Quaternion`、现有 `EgoAnchor.Policy` core/estimator/output 模块、`System.Text.Json`、手写 SVG 曲线输出。

---

## File Structure

### Create
- `EgoAnchor_Tools/anchor_upsample_sim/AnchorUpsampleSim.csproj`：工具项目，引用 UnityEngine 与现有 Policy 源文件。
- `EgoAnchor_Tools/anchor_upsample_sim/Program.cs`：CLI、数据加载、实时模拟 loop、JSONL/CSV/SVG/Markdown 输出。

### Read Only Inputs
- `EgoAnchor_Python/data/eval/20260614_130324_controller_right/*_unity_output.jsonl`
- `EgoAnchor_Python/data/eval/offline_data/*_unity_output.jsonl`

### Verification Outputs
- `<session>/anchor_upsample_sim/upsample_sim_output.jsonl`
- `<session>/anchor_upsample_sim/upsample_sim_summary.csv`
- `<session>/anchor_upsample_sim/algorithm_notes.md`
- `<session>/anchor_upsample_sim/charts/*.svg`

---

## Task 1: Add Tool Project And Self Test

**Files:**
- Create: `EgoAnchor_Tools/anchor_upsample_sim/AnchorUpsampleSim.csproj`
- Create: `EgoAnchor_Tools/anchor_upsample_sim/Program.cs`

- [ ] **Step 1: Write self-test behavior first**

`Program.cs` must support:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_upsample_sim\AnchorUpsampleSim.csproj -- --self-test
```

Expected behavior after implementation:
- builds a synthetic 5Hz observation stream,
- runs prediction on a non-uniform recorded render timeline,
- verifies `raw_none` repeats between observations,
- verifies `kalman_prediction` changes between observations after two samples,
- verifies `dead_reckoning_spline` produces continuous correction output,
- verifies `oneeuro_prediction` produces continuous prediction output,
- verifies each render row contains a normalized quaternion.

- [ ] **Step 2: Run self-test before implementation**

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_upsample_sim\AnchorUpsampleSim.csproj -- --self-test
```

Expected: FAIL before tool implementation exists or before checks pass.

- [ ] **Step 3: Implement the minimal tool skeleton**

Add project references matching `anchor_replay`: UnityEngine assemblies and existing `Policy/Core`, `Policy/Gate`, `Policy/Estimator`, `Policy/Output`.

- [ ] **Step 4: Run self-test after implementation**

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_upsample_sim\AnchorUpsampleSim.csproj -- --self-test
```

Expected: PASS and prints `Anchor upsample simulator self-test passed.`

---

## Task 2: Load Real Session Observations Correctly

**Files:**
- Modify: `EgoAnchor_Tools/anchor_upsample_sim/Program.cs`

- [ ] **Step 1: Parse session output log**

Find exactly one `*_unity_output.jsonl` in `--session`. For each row, inspect `variants[]`, select `is_primary=true`, require `has_aligned_raw=true`, then read:

```text
source_frame_id
source_capture_mono_ms
aligned_raw_pos
aligned_raw_rot
reliability_score
latest_phase
```

- [ ] **Step 2: Deduplicate by source frame**

Only the first row for each `source_frame_id` becomes an observation. This preserves low-frequency input and avoids feeding the same observation once per render row.

- [ ] **Step 3: Preserve recorded render clock**

Store every source row's `render_mono_ms` and use those recorded render timestamps as the simulation timeline. The render loop must not synthesize fixed 60Hz ticks for real sessions and must not reuse existing `stable_pos/stable_rot`.

---

## Task 3: Implement Baseline Algorithms

**Files:**
- Modify: `EgoAnchor_Tools/anchor_upsample_sim/Program.cs`

- [ ] **Step 1: Implement requested baseline predictors**

Add four predictors:
- `raw_none`: 什么都不处理，最近一次观测 pose 的 zero-order hold。
- `kalman_prediction`: 常速度 Kalman Filter Prediction；每次观测校正位置/旋转误差态，render tick 用状态方程前推。
- `dead_reckoning_spline`: 航位推测 + 样条修正；两次观测之间用速度预测，新观测到达后用短窗口 Hermite smooth correction 逐步吸收预测误差。
- `oneeuro_prediction`: One Euro Filter + 预测模型；观测到达时更新自适应低通状态，render tick 用滤波速度做有界前推。

Each predictor must expose `Accept(observation)` and `Predict(renderTime)`.

---

## Task 4: Write Outputs And Charts

**Files:**
- Modify: `EgoAnchor_Tools/anchor_upsample_sim/Program.cs`

- [ ] **Step 1: Write JSONL output**

Each render tick writes top-level time, latest observation, and per-baseline pose:

```text
render_mono_ms, obs_source_frame_id, obs_age_ms, variants[label, pos, rot, euler_deg, predict_ahead_ms]
```

- [ ] **Step 2: Write summary CSV**

For each algorithm record:
- render rows,
- observation rows,
- mean observation age,
- per-frame position step RMS,
- per-frame rotation step RMS,
- max position step,
- max rotation step,
- RMS distance to latest observation at observation instants.

- [ ] **Step 3: Write SVG charts**

Generate one SVG per algorithm. Each SVG contains four panels:
- `x`,
- `y`,
- `z`,
- rotation angle relative to first observation.

Observation poses are drawn as discrete points; render poses are drawn as continuous polylines.

- [ ] **Step 4: Write algorithm notes**

Write `algorithm_notes.md` explaining each algorithm's update and prediction logic in Chinese.

---

## Task 5: Run Real Sessions

**Files:**
- Output only under session `anchor_upsample_sim/` directories.

- [ ] **Step 1: Run self-test**

```powershell
dotnet run --project EgoAnchor_Tools\anchor_upsample_sim\AnchorUpsampleSim.csproj -- --self-test
```

- [ ] **Step 2: Run current recorded session**

```powershell
dotnet run --project EgoAnchor_Tools\anchor_upsample_sim\AnchorUpsampleSim.csproj -- --session EgoAnchor_Python\data\eval\20260614_130324_controller_right --out EgoAnchor_Python\data\eval\20260614_130324_controller_right\anchor_upsample_sim
```

- [ ] **Step 3: Run offline_data**

```powershell
dotnet run --project EgoAnchor_Tools\anchor_upsample_sim\AnchorUpsampleSim.csproj -- --session EgoAnchor_Python\data\eval\offline_data --out EgoAnchor_Python\data\eval\offline_data\anchor_upsample_sim
```

- [ ] **Step 4: Build Unity smoke**

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected: PASS. The new tool must not regress existing policy behavior.

---

## Self Review

- Spec coverage: covers C# tool, two real sessions, 5Hz input, recorded render-time prediction, four baseline algorithms, plots, and implementation notes.
- Placeholder scan: no TBD/TODO placeholders.
- Type consistency: all existing project module names match current `EgoAnchor.Policy` files.
