# EgoAnchor 评估系统 — 分步实现指导（执行手册）

> 配套计划：[`1-anchor-inherited-cook.md`](1-anchor-inherited-cook.md)。本文是它的**逐步执行版**，每个 Stage 给出：要写什么、为什么、关键代码骨架、验收标准。
> 执行顺序：**Unity 采集（U0→U4）→ Python 分析（P0→P3）→ 端到端测试（T）**。每个 Stage 验收通过后再进下一个。
> 原则：measure-first，不改 anchor 算法本体；评估代码与 runtime 物理+编译期隔离；录一次离线算所有。

---

## 0. 全局约定（先读，贯穿全程）

### 0.1 数据落盘位置与命名

所有评估数据落到 `EgoAnchor_Python/data/eval/<session_id>/`。默认推荐 **先启动 Python，再启动 Unity 录制**：Python 先创建共享 session 目录并写入 `python_session.json`，Unity Start/F7 时自动复用该目录。一个 session 目录内：

```
data/eval/<session_id>/
  python_session.json                 # Python 写，session 元数据 + python_log_filename
  <session_id>_python_runtime.jsonl   # Python 写，PoseResult/status/heartbeat/command runtime 日志
  <session_id>_unity_capture.jsonl     # Unity 写，每 frame_id 一行（~8fps）
  <session_id>_unity_output.jsonl      # Unity 写，每渲染 tick 一行（~90fps）
  session_manifest.json                # Unity 写，session 元数据 + 条件/事件标签
  report/                              # Python eval 产出表+图
```

Unity session_id 使用人类可读时间命名，默认格式为 `yyyyMMdd_HHmmss_<object_id>`，例如 `20260602_153012_controller_right`。若同一秒重复开始录制，自动追加 `_02`、`_03`，避免覆盖。

**关键**：默认自动配对时 Python 与 Unity 使用同一个人类可读 `session_id` 目录。三份日志仍靠 **`frame_id` 精确 join**（QuestStereoFrame 发出的 frame_id 同时出现在 Python `pose_result.frame_id` 和 Unity `unity_capture.frame_id`）。manifest 里记 `python_log_filename` 字段，Unity 从 `python_session.json` 自动填入；只有旧数据或未找到 Python session 时才需要显式传 `--python-log`。

### 0.2 坐标系约定（务必记牢，错了指标全错）

- Python `pose_result.pose_matrix_cv_camera`：OpenCV 左目相机系（x右 y下 z前），16 个 float 行主序。
- Unity 侧 GT / anchor / 头 / 相机 pose：全部记 **Unity 世界系**（左手系，y上）。
- GT（手柄）：当前主线直接记录场景中绑定的 `groundTruthTransform`（通常为 `OVRControllerPrefab` 根 Transform）的 Unity 世界位姿，日志写 `gt_pose_source="transform"`、`gt_source="transform"`、`gt_transform=<TransformName>`。因此 GT 与 anchor 都是 Unity 世界系 Transform pose，不再经过 `OVRInput` SDK 原点。
- anchor（被评估输出）：`AnchorEvalRecorder.recordedRuntimes[*].anchorTransform` 的 Unity 世界位姿；主变体额外记录 `PoseToAnchorRuntime.TryGetRawPose` 得到的 `aligned_raw_pos/rot` 作为离线诊断输入。
- 因此**离线指标全在 Unity 世界系直接比较 GT Transform 与 anchor Transform**。Python camera-space 矩阵只在 RQ1（arrival-time vs frame-aligned 离线重算）时才用到，需配合 `unity_capture` 的相机世界位姿做组合。

### 0.3 时间戳约定

每条记录同时写 `*_mono_ms`（Unity `Time.realtimeSinceStartupAsDouble*1000`，单调，做 latency）、`*_unix_ms`（`DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()`，墙钟，跨进程对时兜底）、`*_utc`（ISO-8601 UTC，可读）和 `*_local`（本地时区可读）。manifest 记 `mono_to_unix_offset_ms = unix - mono`（session 启动时采一次），并为 session/condition/event 同时写 UTC/local 可读时间。

### 0.4 JSON 序列化策略（Unity 侧）

**手写 JSON 字符串**，不用 `JsonUtility`（它不支持 variants 这种嵌套数组、且对 double 精度不友好）。在 `JsonlFileWriter` 上层用 `System.Text.StringBuilder` 拼，float/double 用 `ToString("R", CultureInfo.InvariantCulture)` 保证往返精度和小数点（避免某些 locale 用逗号）。

### 0.5 每个 Stage 的测试交付要求

每个 Stage 交付时，除代码和自动化构建/单测验证外，必须同时给出**可直接执行的测试脚本/测试组件**和**清楚的测试步骤**，不要把临时测试入口留给使用者再补。临时脚本或组件用于验收后可以删除；若后续 Stage 仍会复用，则作为 smoke/helper 明确保留并纳入验证命令。

Unity 侧所有测试热键、按钮输入或临时交互入口必须使用 **Unity 新 Input System**（如 `UnityEngine.InputSystem.Keyboard.current` / `InputAction`），不要使用旧 `UnityEngine.Input` / `KeyCode`。每次交付说明必须列出：运行命令、场景挂载/引用绑定步骤、Play Mode 操作步骤、期望 Console/文件输出、哪些临时测试产物可删除。

---

## Stage U0 — 隔离骨架 + 采集缝（先验证日志能落盘）

**目标**：建独立 asmdef、能写一行 JSON、StereoFrameSource 暴露 frame_id 诞生时刻事件。

### U0.1 `EgoAnchorEval.asmdef`

新目录 `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/`，放：

```json
{
  "name": "EgoAnchorEval",
  "rootNamespace": "EgoAnchorEval",
  "references": ["EgoAnchor", "Oculus.VR", "meta.xr.mrutilitykit", "Unity.TextMeshPro", "Unity.InputSystem"],
  "autoReferenced": true
}
```

单向依赖 `eval → runtime`。`EgoAnchor.asmdef`（现有，已确认 references 为 Oculus.VR/mrutilitykit/TextMeshPro）**绝不**反向引用本程序集——编译期保证 GT 不可能污染锚定管线。若测试组件使用 Unity 新 Input System，`EgoAnchorEval.asmdef` 必须显式引用 `Unity.InputSystem`。

### U0.2 `JsonlFileWriter.cs`（纯 C#，非 MonoBehaviour）

职责：缓冲 + 周期 flush 的线程安全单行追加写。骨架：

```csharp
public sealed class JsonlFileWriter : IDisposable
{
    private readonly StreamWriter writer;
    private readonly int flushEveryLines;
    private int sinceFlush;
    private readonly object gate = new object();

    public JsonlFileWriter(string filePath, int flushEveryLines = 64)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(filePath));
        writer = new StreamWriter(filePath, append: false, Encoding.UTF8);
        this.flushEveryLines = Mathf.Max(1, flushEveryLines);
    }
    public void WriteLine(string jsonLine)
    {
        lock (gate) { writer.Write(jsonLine); writer.Write('\n');
            if (++sinceFlush >= flushEveryLines) { writer.Flush(); sinceFlush = 0; } }
    }
    public void Flush() { lock (gate) { writer.Flush(); sinceFlush = 0; } }
    public void Dispose() { lock (gate) { writer.Flush(); writer.Dispose(); } }
}
```

### U0.3 修改 `StereoFrameSource.cs`（唯一的运行时改动，一条缝）

在 [`StereoFrameSource.cs:117`](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Quest/StereoFrameSource.cs#L117) 的 `framePoseHistory?.Record(...)` **之后**加事件触发。`currentFrameId` 和 `senderMonoMs` 此处都在作用域内（见 L103-104）：

```csharp
// 类字段：
/// <summary>采集并记录一帧 frame_id 相机位姿后触发；(frameId, captureMonoMs)。无订阅者时零成本。</summary>
public event Action<long, double> FrameCaptured;

// L117 之后：
FrameCaptured?.Invoke(currentFrameId, senderMonoMs);
```

理由：只有 StereoFrameSource 知道 frame_id 诞生的确切 Unity 帧，recorder 必须在**同一 Unity 帧**采 GT，才能保证 GT 与该帧相机位姿同瞬间。`Action` 已随 `using System;`（L1）可用。

### U0.4 验收

- Unity 编译通过，Console 无 asmdef 循环依赖报错。
- 写个临时 MonoBehaviour（或在 recorder 雏形里）`Start()` 里 `new JsonlFileWriter(path).WriteLine("{\"test\":1}")`，确认 `data/eval/.../test.jsonl` 出现且内容正确。
- 临时订阅 `stereoSource.FrameCaptured += (id,t)=>Debug.Log($"cap {id} @{t}")`，Play 后 Console 持续打印递增 frame_id —— 证明缝点有效。验证后删临时代码。

---

## Stage U1 — Transform GT 绑定（GT 来源）

**目标**：直接把场景中代表真实控制器/目标物体的 Transform 作为 Unity 世界系 GT。当前主线已采用此路径，替代旧 `ControllerGroundTruthProvider` / `OVRInput` SDK 原点方案。

### U1.1 实现

`AnchorEvalRecorder` 暴露：

```csharp
[Tooltip("作为 GT 的场景 Transform，通常绑定 OVRControllerPrefab 根 Transform。")]
[SerializeField] private Transform groundTruthTransform;

public string ManifestGtSource => groundTruthTransform != null ? "transform" : "transform_missing";
public string ManifestGtTransform => groundTruthTransform != null ? groundTruthTransform.name : string.Empty;
```

采样时只读取 `groundTruthTransform.position/rotation`，写入 `gt_pose_valid`、`gt_pose_source`、`gt_pos/gt_rot`。GT 仍只进入 Eval asmdef，不进入 anchor runtime。

### U1.2 验收

- `AnchorEvalRecorder.groundTruthTransform` 拖入本轮被追踪控制器可视 Transform（例如 `OVRControllerPrefab`），不要拖 `AnchorObject` 或任何被评估输出。
- Play 后录几秒，确认 capture/output 均写 `gt_pose_valid=true`、`gt_pose_source="transform"`，并且 `session_manifest.json` 写 `gt_source="transform"`、`gt_transform` 为正确 Transform 名称。

---

## Stage U2 — AnchorEvalRecorder（核心：双采样率多变体）

**目标**：`FrameCaptured` 回调写 `unity_capture`（每 frame_id），`LateUpdate` 写 `unity_output`（每渲染 tick，含各变体）。

### U2.1 变体配置结构

```csharp
[Serializable]
public struct RecordedRuntime
{
    public string label;                 // "raw" / "lowpass" / "kalman" / "controller"
    public PoseToAnchorRuntime runtime;  // 拖入对应 runtime
    public Transform anchorTransform;    // 实际被评估的输出 Transform
    public bool isPrimary;               // 主变体额外记 aligned_raw + reliability（回放输入）
}
```

### U2.2 字段与生命周期

```csharp
public sealed class AnchorEvalRecorder : MonoBehaviour
{
    [SerializeField] private Transform groundTruthTransform;
    [SerializeField] private Transform headAnchor;            // CenterEyeAnchor
    [SerializeField] private CameraReference alignmentReference = CameraReference.Left; // 与主 runtime 一致
    [SerializeField] private StereoFrameSource stereoSource;
    [SerializeField] private FramePoseHistory framePoseHistory;
    [SerializeField] private List<RecordedRuntime> recordedRuntimes = new();

    private JsonlFileWriter captureWriter;
    private JsonlFileWriter outputWriter;
    private bool recording;

    // 由 EvalSessionController 调用
    public void BeginRecording(string capturePath, string outputPath) {
        captureWriter = new JsonlFileWriter(capturePath);
        outputWriter  = new JsonlFileWriter(outputPath);
        recording = true;
    }
    public void StopRecording() {
        recording = false;
        captureWriter?.Dispose(); outputWriter?.Dispose();
        captureWriter = outputWriter = null;
    }

    void OnEnable()  { if (stereoSource != null) stereoSource.FrameCaptured += OnFrameCaptured; }
    void OnDisable() { if (stereoSource != null) stereoSource.FrameCaptured -= OnFrameCaptured; }
}
```

### U2.3 capture 回调（每 frame_id，同 Unity 帧采 GT）

```csharp
private void OnFrameCaptured(long frameId, double captureMonoMs)
{
    if (!recording) return;
    PoseSample gtSample = ReadGroundTruthSample();
    framePoseHistory.TryGet(frameId, out FramePoseRecord rec);
    rec.TryGetCameraPose(alignmentReference, out Pose camPose);
    Pose head = headAnchor != null ? new Pose(headAnchor.position, headAnchor.rotation) : Pose.identity;
    double unixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
    // 手写 JSON 一行：event=unity_capture, frame_id, capture_mono_ms, capture_unix_ms,
    //   head_pos/rot, cam_pos/rot, gt_pos/rot,
    //   gt_pose_valid, gt_pose_source(transform/none), capture_unity_frame, camera_reference
    captureWriter.WriteLine(BuildCaptureLine(frameId, captureMonoMs, unixMs, head, camPose, gtSample.Pose,
        gtSample.HasPose, gtSample.PoseSource));
}
```

注意 `FramePoseRecord.TryGetCameraPose(CameraReference, out Pose)` 是现有 API（[FramePoseHistory.cs:150](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Alignment/FramePoseHistory.cs#L150)），按 Left/Right/Center 取采集时刻相机世界位姿。

### U2.4 output（每渲染 tick）

```csharp
void LateUpdate()
{
    if (!recording) return;
    PoseSample gtSample = ReadGroundTruthSample();
    double monoMs = Time.realtimeSinceStartupAsDouble * 1000.0;
    double unixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
    Pose head = headAnchor != null ? new Pose(headAnchor.position, headAnchor.rotation) : Pose.identity;

    // 遍历 recordedRuntimes 组 variants 数组：
    foreach (var rr in recordedRuntimes) {
        var rt = rr.runtime;
        bool has = TryReadAnchorPose(rr.anchorTransform, out Pose stable, out string anchorPoseSource);
        long srcFrame = rt.LatestAlignedFrameId;
        string state = rt.CurrentAnchorState.ToString();   // AnchorState enum
        string action = rt.LatestPolicyAction, reason = rt.LatestPolicyReason;
        if (rr.isPrimary) {
            bool hasRaw = rt.TryGetRawPose(out Pose raw);   // = aligned_raw（无 processor 时 stable==raw）
            float rel = rt.LatestReliabilityScore;
            // 额外写 aligned_raw_pos/rot + reliability_score
        }
    }
    // source_frame_id 取主变体的 LatestAlignedFrameId
    outputWriter.WriteLine(BuildOutputLine(monoMs, unixMs, head, gtSample.Pose,
        gtSample.HasPose, gtSample.PoseSource, /*variants*/));
}
```

**全部用现有只读 API**（已确认存在于 [PoseToAnchorRuntime.cs:83-104,191-207](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs#L83)）：`TryGetStablePose`/`TryGetRawPose`/`LatestAlignedFrameId`/`CurrentAnchorState`/`LatestPolicyAction`/`LatestPolicyReason`/`LatestReliabilityScore`。**记录器零侵入 runtime**。

> latency 终点说明：`source_frame_id` 是该 tick 显示位姿对应的 frame_id；离线取某 frame_id **首次**出现的 tick 的 `render_mono_ms` 作为 `t_apply`。

### U2.5 验收

- 不接 SessionController，先在 recorder 里硬编码一个 `BeginRecording` 路径、Play 几秒、Stop。
- 确认两份 JSONL 行数比例合理（output 约为 capture 的 ~10×，对应 90fps vs 8fps）。
- 用文本编辑器看几行：capture 的 `frame_id` 递增、`gt_pos` 合理；output 的 `variants` 数组含配置的标签、主变体有 `aligned_raw_pos`。
- 抽一个 capture 的 `frame_id`，确认它能在同一 session 目录的 `<session_id>_python_runtime.jsonl` 中找到同 `frame_id` 的 `pose_result` 行（join 主键成立）。

---

## Stage U3 — EvalSessionController（session/条件/事件/manifest）

**目标**：控制录制生命周期、打条件区间、记瞬时事件、生成 manifest。

```csharp
public sealed class EvalSessionController : MonoBehaviour
{
    [SerializeField] private AnchorEvalRecorder recorder;
    [SerializeField] private string outputRoot;          // data/eval 绝对路径
    [SerializeField] private string objectId = "controller_right";  // controller_left / controller_right
    [SerializeField] private bool reuseLatestPythonSession = true;  // 先找 Python 已创建的共享 session
    [SerializeField] private string pythonSessionMetadataFilename = "python_session.json";

    private string sessionId;
    private string sessionDir;
    private double monoToUnixOffsetMs;
    private readonly List<(string label, double start, double end)> spans = new();
    private readonly List<(string type, double mono)> markers = new();
    private (string label, double start)? openSpan;

    public void StartSession() {
        if (reuseLatestPythonSession && TryFindReusablePythonSession(outputRoot, objectId, ..., out sessionId, out sessionDir, out pythonLog)) {
            // 复用 Python 的 data/eval/<session_id> 目录，manifest.python_log_filename 自动写 pythonLog。
        } else {
            sessionId = BuildReadableSessionId(DateTimeOffset.Now, objectId);
            sessionDir = Path.Combine(outputRoot, ResolveUniqueSessionId(outputRoot, sessionId));
        }
        double mono = Time.realtimeSinceStartupAsDouble * 1000.0;
        monoToUnixOffsetMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - mono;
        recorder.BeginRecording(
            Path.Combine(sessionDir, $"{sessionId}_unity_capture.jsonl"),
            Path.Combine(sessionDir, $"{sessionId}_unity_output.jsonl"));
    }
    public void StopSession() { EndCondition(); recorder.StopRecording(); WriteManifest(); }
    public void BeginCondition(string label) {
        EndCondition();
        openSpan = (label, Time.realtimeSinceStartupAsDouble * 1000.0);
    }
    public void EndCondition() {
        if (openSpan.HasValue) {
            spans.Add((openSpan.Value.label, openSpan.Value.start, Time.realtimeSinceStartupAsDouble * 1000.0));
            openSpan = null;
        }
    }
    public void Mark(string type) => markers.Add((type, Time.realtimeSinceStartupAsDouble * 1000.0));
    // WriteManifest：手写 session_manifest.json，含
    //   session_id, object_id, unity_run_mode="editor_link",
    //   gt_source="transform", gt_transform=recorder.ManifestGtTransform,
    //   mono_to_unix_offset_ms, condition_spans[], event_markers[],
    //   variant_labels[], python_log_filename(从 python_session.json 自动填入；旧数据可手动覆盖), notes,
    //   session_start/stop mono/unix/utc/local
}
```

**UI 绑定**：场景已有 `Button_Reset/Resume/Pause/ForceReacquire`。新增 `Button_EvalStart/Stop`，或 Editor 下挂 `EvalSessionHotkeyDriver`，用 Unity 新 Input System（`Keyboard.current` / `Key`）触发 `StartSession/StopSession`；条件切换/事件标记也用按钮或键盘（数字键 1-7 对应 7 个条件段，0 结束当前段，O/V/R 标 occlusion/out_of_view/recovery）。录制时单手操作友好。

> `gt_source` / `gt_transform` / `objectId` / Python `--object` **必须人工核对一致**。当前主线 `gt_source="transform"`，应确认 `gt_transform` 指向本轮被追踪的真实控制器可视 Transform，而不是 HMD、anchor 输出或无关代理物体。

### U3.1 验收

- 点 Start 或按 F7 → 切几个 condition（看 Console 或临时 UI 文本）→ 标一个 event → Stop/F8。
- 确认 `session_manifest.json` 生成，`condition_spans` 时间区间连续不重叠、`gt_source="transform"` 且 `gt_transform` 是本轮 GT Transform。
- 确认 capture/output 两份日志在该 session 目录下，文件名含 session_id。
- 确认 capture/output 中 `gt_pose_valid=true` 时 `gt_pose_source="transform"`，`gt_pos/gt_rot` 为 Unity 世界系 Transform pose；若 Transform 未绑定，则必须显式写 `gt_pose_valid=false`、`gt_pose_source="none"`。

---

## Stage U4 — 场景挂载 + 实跑验收三份日志

**目标**：在真实 Editor+Link 下跑通采集，三份日志格式正确、frame_id 对得上 Python。

### U4.1 挂载（对照现有 `Server` 父物体）

现有场景 `Server` 下已有：`AnchorRuntimeHub`、`AnchorPolicyHost`、`AnchorObject`(stable)、`AnchorObject Raw`、`StereoFrameSource`、`FramePoseHistory`、`CameraInfoSource`，以及 `OVRCameraRig/CenterEyeAnchor`。

1. 新建空 GameObject `EvalRig`（挂 `Server` 下），挂 `AnchorEvalRecorder` + `EvalSessionController` + `EvalSessionHotkeyDriver`。
2. `AnchorEvalRecorder.groundTruthTransform` ← 本轮被评估的控制器可视 Transform（当前样例为 `OVRControllerPrefab`）；不要绑定 anchor 输出 Transform。
3. `AnchorEvalRecorder.headAnchor`←`CenterEyeAnchor`；`stereoSource`/`framePoseHistory`←场景对应组件（与 runtime 同实例）；`alignmentReference`←`Left`（与主 runtime 一致）。
4. `recordedRuntimes` 列表：先连两项 —— `AnchorObject`(label="kalman" 或当前 stable 配置, `anchorTransform` 绑定该输出 Transform, isPrimary=true) 与 `AnchorObject Raw`(label="raw", `anchorTransform` 绑定 raw 输出 Transform)。RQ2 ablation 时再加 lowpass/policy 变体子物体（往 `AnchorRuntimeHub.runtimes` 加 + 拖进本 list，纯场景配置）。
5. `EvalSessionController`：`recorder` 拖入，`outputRoot` 填 `data/eval` 绝对路径，`objectId` 设对，`reuseLatestPythonSession` 保持勾选。
6. UI/热键绑定 Start/Stop/condition/mark；当前场景可直接用 `EvalSessionHotkeyDriver`：F7 Start、F8 Stop、1-7 条件段、0 结束段、O/V/R 事件标记。

### U4.2 验收（本阶段 Unity 侧完成定义）

- 启动 Python：`pixi run controller_right`（或 left）。Python 会创建 `data/eval/<session_id>/python_session.json` 和 `<session_id>_python_runtime.jsonl`。
- 戴头显进入 Editor+Link，点 Start/F7；Unity 应在 Console 打印复用 Python eval session。录 ~20 秒（随便动动手柄+头），点 Stop/F8。
- 产出三份文件齐全：`*_unity_capture.jsonl`、`*_unity_output.jsonl`、`session_manifest.json`。
- `dotnet run --project EgoAnchor_Tools\eval_writer_smoke\EvalWriterSmoke.csproj` 会自动检查 `EgoAnchor-Evaluation.unity` 中 `EvalRig`、`EvalSessionController`、`EvalSessionHotkeyDriver` 和 hold-last GT 配置仍存在。
- **frame_id 对齐验证**：取 capture 中任一 `frame_id`，在同目录 `<session_id>_python_runtime.jsonl` 里 grep 到同 `frame_id` 的 `pose_result`（证明三方 join 可行）。
- 录制后可直接跑 `dotnet run --project EgoAnchor_Tools\eval_session_check\EvalSessionCheck.csproj -- --session-dir EgoAnchor_Python\data\eval\<session_id> --require-python-join`，自动检查三份 Unity 日志、manifest、raw/主变体字段、GT 字段与 Python `frame_id` join。
- output 的 `variants` 含 raw + 主变体，主变体有 `aligned_raw_pos/rot` + `reliability_score`。
- capture/output 均含 `gt_pose_valid`、`gt_pose_source`；当前 Transform GT 路径不再写 `gt_tracked/gt_hold_age_ms`。
- 无明显掉帧/卡顿（若 90fps 写盘卡，把 output 降到 ~30Hz：LateUpdate 里按时间间隔节流）。

> ⚠️ Unity 侧到此可交付。Python 侧（P0-P4）可并行开工，但**端到端验收（Stage T）依赖一份真实录制数据**，建议 U4 跑出一份 ~3 分钟的完整协议数据备用。

---

## Stage P0 — 补 latency 分模块日志字段（非侵入运行时改动）

**目标**：让 Python `pose_result` 日志写出分模块耗时，供 latency breakdown 表（论文 Table 3）。

现状：[`runtime_log_writer.py:122`](EgoAnchor_Python/src/egoanchor/runtime/runtime_log_writer.py#L122) 只写 `total_ms`，但 proto `TimingStats` 已含 `yolo_ms/depth_ms/cutie_ms/pose_ms`（`message_factories.py:49-53` 已填充），`msg.timing` 上都有。`server_receive_mono_ms`（proto 已定义）也应写出做网络腿。

改动 `pose_result` 方法的 fields dict，新增：

```python
total_ms=float(msg.timing.total_ms),
yolo_ms=float(msg.timing.yolo_ms),
depth_ms=float(msg.timing.depth_ms),
cutie_ms=float(msg.timing.cutie_ms),
pose_ms=float(msg.timing.pose_ms),
server_receive_mono_ms=float(msg.server_receive_mono_ms),
server_publish_mono_ms=float(msg.server_publish_mono_ms),
```

纯加字段，向后兼容，不碰任何算法。

### P0.1 验收

- `pixi run controller_right` 跑几秒、停。
- 看最新 `data/eval/<session_id>/<session_id>_python_runtime.jsonl` 的 `pose_result` 行含 `yolo_ms/depth_ms/cutie_ms/pose_ms/server_receive_mono_ms`，数值合理（和为 ≈ total_ms 数量级）。
- 现有依赖 `pose_result` 的单测仍通过（`pixi run test` 或对应测试任务）。

---

## Stage P1 — eval/io：日志加载与 join（分析底座）

**目标**：把四份日志读成 DataFrame，提供 frame_id join 和 condition 切分。新增**顶层** `EgoAnchor_Python/eval/`（与 `src/` 平级，**不 import egoanchor**，只读 JSONL）。

### P1.1 `eval/io/schemas.py`

每份日志行的 dataclass + 字段校验（缺字段报清晰错误，而非后续 KeyError）。至少定义：`CaptureRow`、`OutputRow`（含 `variants: list[VariantRow]`）、`PoseResultRow`、`Manifest`。pose/rot 统一存 `np.ndarray`（pos shape (3,)，quat shape (4,) xyzw）。

### P1.2 `eval/io/log_loader.py`

```python
@dataclass
class SessionLogs:
    capture: pd.DataFrame      # index=frame_id
    output: pd.DataFrame       # 展平：每 (tick, variant) 一行，列含 label
    pose: pd.DataFrame         # Python pose_result，index=frame_id
    manifest: dict

def load_session(session_dir: Path) -> SessionLogs: ...
def join_by_frame(logs) -> pd.DataFrame:    # capture ⋈ pose on frame_id（anchor error / RQ1 / latency 起点）
def label_conditions(df, manifest, mono_col: str) -> pd.DataFrame:  # 按 condition_spans 给每行打 condition 列
```

要点：
- `output` 的 `variants` 数组**展平成长表**（每 variant 一行，列 `label`），方便 `groupby("label")` 算各变体指标。
- Python 日志路径：默认从 `manifest["python_log_filename"]` 取，自动配对成功时它指向同目录 `<session_id>_python_runtime.jsonl`；为空时回退到"同目录唯一非 Unity .jsonl"或让 CLI 显式传 `--python-log`。
- `gt_pose_valid=false` 的行打 `valid=False` 列，各指标默认 `df[df.valid]`。
- 坐标系：所有 pos/quat 已是 Unity 世界系（capture/output），pose_result 是 OpenCV 相机系（仅 RQ1 用）。

### P1.3 验收

- 用 U4 录的真实 session 跑 `load_session`，打印三张表 shape、`manifest` 内容。
- `join_by_frame` 后无大量 NaN（frame_id 命中率高，证明 join 主键对）。
- `label_conditions` 后每行有 condition 标签，分布与录制协议一致（static/slow_head/...）。
- 写最小单测：构造 2-3 行假 JSONL，断言 load+join+label 结果。

---

## Stage P2 — eval/metrics：Transform GT 直接评估指标

**目标**：基于当前 Unity Transform GT 日志直接计算 anchor error、latency、jitter、lag、slip、jump suppression、recovery 等论文指标。原 `eval/calib/hand_eye.py` 不再作为执行阶段：它只适用于 `OVRInput` SDK 原点与 mesh/anchor 原点不一致的旧方案；当前 `gt_source="transform"` 已把 GT 写成被评估对象的 Unity 世界 Transform pose，继续求 `X` 会把算法误差错误吸收到标定偏置里。

### P2.1 `eval/metrics/common.py`（先做，其他都依赖）

```python
def mat_to_pos_quat(T): ...                  # (4,4) → (pos(3,), quat(4,) xyzw)
def pos_quat_to_mat(p, q): ...               # Unity world pos/quat → (4,4)
def pose_error(gt_pos, gt_quat, anchor_pos, anchor_quat): ...  # 直接比较 GT Transform 与 anchor Transform
def angle_deg(q): ...                         # 四元数 → 旋转角度
def slerp_lerp_resample(t_src, p, q, t_dst):  # 位姿重采样到目标时间网格（lag/回放对齐）
def highpass(signal, dt, cutoff_hz): ...      # 去慢漂留抖动（jitter）
def project_point(K, w_T_cam, p_world): ...   # 世界点 → 头相机像面（slip 屏幕空间）
```

误差统一定义为 `E = inv(W_T_GT) · W_T_Anchor`，`e_t=‖E.t‖`(m)、`e_r=angle(E.R)`(deg)。对主变体可同时计算 `aligned_raw_pos/rot` 误差，用于 raw 输入质量诊断；正式 variant 指标默认使用 `stable_pos/stable_rot` 且 `has_stable=true` 的行。

### P2.2 指标文件

| # | 文件 | 定义 |
|---|---|---|
| 1 | `anchor_error.py` | 各条件 × 各变体的 `e_t,e_r` RMSE/median/p95。输入为 output 长表，直接比较 `gt_pos/gt_rot` 与 `stable_pos/stable_rot`。 |
| 2 | `slip.py` | 屏幕空间：anchor 原点与 GT 原点用头相机或近似相机内参投影，`slip_px=‖proj(anchor)−proj(gt)‖`，报 RMS/peak，并可关联头部角速度。 |
| 3 | `jitter.py` | GT 速度低于阈值的静止窗内，对 anchor 位姿高通去慢漂后报位置/旋转 std/RMS；raw vs lowpass vs kalman vs controller 同窗对比。 |
| 4 | `lag.py` | anchor 与 GT 位置重采样到均匀网格，速度信号归一化互相关 `lag=argmax`；快速平移段报阶跃响应上升时间(到90%)。 |
| 5 | `latency.py` | 每 frame_id 首次应用 tick 的 `t_apply−t_capture`（Unity 单调钟）；分模块用 Python timing；报 P50/90/95 + breakdown。 |
| 6 | `recovery.py` | manifest 遮挡/出视野/返回标记 + anchor_state 流 + 误差回落阈。`recovery_time`=重现标记→首次持续 accepted 且 e_t<阈。 |
| 7 | `jump_suppression.py` | raw（不拦尖峰）vs controller/stable（抑制后）：误差尖峰计数+幅度；统计 policy reject 原因分布。 |
| 8 | task/主观 | 本轮不实现，只在 manifest 留 event marker 钩子。 |

### P2.3 GT/anchor 语义一致性 sanity check

`run_eval.py` 每次输出 `report/gt_anchor_sanity.json`：

- `gt_source`、`gt_transform`、`object_id`、`variant_labels`。
- 每个 variant 可评估行数、GT 有效行数、`anchor_pose_source` 分布。
- 主变体 `aligned_raw` 与 GT 的直接误差摘要（若存在），用于快速发现 GT 绑错物体或 anchor 输出未生效。

### P2.4 验收

- 每个指标用 U4 真实数据跑出数字；若某项因数据不足（例如没有 `has_stable=true` 或没有 recovery marker）无法计算，应输出 `insufficient_data` 而不是崩溃。
- `common.py` 几何工具有单测（往返 `mat↔pos_quat`、已知旋转的 `angle_deg`、重采样保形、直接 pose error）。
- raw vs stable 的 jitter/lag 对比在有对应数据时可见；无 stable 行时报告里清楚标注本 session 只能做 raw/latency/loader smoke。

---

## Stage P3 — eval/report + run_eval + pixi 任务

**目标**：一条命令产出某 session 全部表图。

### P3.1 `eval/report/tables.py` + `figures.py`

- `tables.py`（pandas → 论文 Table 2/3）：各条件 × 各变体的 error/jitter/slip 汇总表；latency breakdown 表（capture/network/yolo/depth/cutie/pose/apply 的 P50/90/95）。导出 CSV + markdown。
- `figures.py`（matplotlib）：误差时间线（叠 condition 区间底色）；四变体 jitter-lag 散点（凸显 tradeoff）；slip vs 头部角速度；latency breakdown 堆叠条；recovery 时间线；**EgoAnchor 各变体 vs Transform GT 同图**（标注"视觉-only，物体无传感器"，凸显优势叙事）。导出 PNG + PDF（论文用矢量）。

### P3.2 `eval/run_eval.py`（CLI 主入口）

流程：`load_session` → `label_conditions` → `compute_all_metrics` → `write_tables/write_figures` → `write gt_anchor_sanity.json` → 写 `report/`。支持 `--only metrics|figures|tables|sanity|all` 分步调试。

### P3.3 pixi 任务（加到 `EgoAnchor_Python/pixi.toml [tasks]`）

```toml
eval         = "python eval/run_eval.py"
eval-metrics = "python eval/run_eval.py --only metrics"
eval-figures = "python eval/run_eval.py --only figures"
```

使用方式：`pixi run eval --session-dir data/eval/<session_id>`。依赖 numpy/scipy/pandas/matplotlib/opencv 均已在环境（确认；缺则加 pixi 依赖）。

### P3.4 验收

- `pixi run eval --session-dir data/eval/<session>` 一条命令跑通，`report/` 出全部表+图。
- 图能直接看懂：误差时间线有 condition 底色、latency 堆叠条各模块清晰、jitter-lag 散点在有足够数据时显示各变体差异。

---

## Stage T — 端到端测试与验收（本阶段完成定义）

按录制协议（计划 §录制协议）跑完整数据，验证整条链路。

### T.1 完整录制（左右手柄各一轮）

| 段 | 时长 | 动作 | 标签 |
|---|---|---|---|
| 1 | 30s | 物体放定、头不动 | static |
| 2 | 30s | 物体放定、头自然左右上下 | slow_head |
| 3 | 20s | 物体放定、猛转头 | fast_head |
| 4 | 30s | 手持手柄平移+充分三轴旋转 | object_motion |
| 5 | 20s | 手挡一部分(+Mark) | occlusion |
| 6 | ×5 | 移出视野再返回(+Mark) | out_of_view |
| 7 | 20s | 开关灯/换背景 | lighting |

### T.2 验收清单（=整个 P1 阶段的 Definition of Done）

- [ ] 跑完整协议，产出三份 Unity 日志 + manifest，`frame_id` 与 Python `pose_result` 完全对应（join 无大量丢帧）。
- [ ] `report/gt_anchor_sanity.json` 证明 `gt_source="transform"`、`gt_transform`、`object_id` 与变体输出语义一致；直接世界系误差量级合理。
- [ ] `pixi run eval` 一条命令产出：RQ1（arrival-time vs frame-aligned 的 anchor error/slip，若当前数据具备）、end-to-end latency breakdown（P50/90/95 含分模块）、当前 stable 与 raw 的 jitter/slip/anchor-error/jump suppression 表与图。
- [ ] 左右手柄各自使用对应 Transform GT session 独立出指标，未混用 session 或 object_id。
- [ ] 这套基线数字存档，作为后续几何质量评分/统一 SE(3) filter 所有改动的对照组。

### T.3 P1b 回放（可选，为 P3 铺路，最后做）

`ReplayPoseSource.cs`：读主变体 `unity_output` 里记的 `aligned_raw_pos/rot`+`reliability_score`+`source_frame_id`+`render_mono_ms` 流，按时戳经 `PoseToAnchorRuntime.AcceptWorldPose(frameId, worldPose)` 重泵进各 filter 变体，重录 output 走同分析管线。若注入需带 reliability，给 runtime 加向后兼容重载 `AcceptWorldPose(frameId, worldPose, reliabilityScore)`（旧重载转调新重载默认 1.0）—— 这是回放唯一可能的运行时小改动，非侵入。

---

## 附：执行节奏建议

1. **先 U0-U2**（骨架+缝+recorder 雏形），跑出哪怕几秒的两份日志 —— 早验证比写全再验证省事。
2. **U3-U4** 补 session 管理 + 真机跑一份 ~3 分钟数据。
3. **P0 立刻做**（独立、低风险，补 latency 字段），然后 P1-P3 对着真实数据写，避免对空 schema 编程。
4. 每个 Stage 验收过了我再开下一个；卡住就回到对应源文件核对，不堆叠假设。
