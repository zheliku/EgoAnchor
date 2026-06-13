# EgoAnchor 评估系统实现计划（Phase P1）

> 配套文档：`IEEEVR2027-paper-architecture.md`（论文架构，本计划实现其 §8 实验矩阵）。
> 阶段：评估底座（measure-first）。本阶段**不改动锚定算法本身**，只新增评估采集与离线分析能力。
> 锁定决策：① Unity 跑在 **Editor + Quest Link（同机）**；② 定量 GT **使用左右手柄**（`controller_left` / `controller_right`，Meta SDK 自带 6DoF）；③ ablation 走 **P1a 实机并行录制 + P1b 确定性回放**；④ RQ2 必须同时比较 raw、low-pass、Kalman、vanilla One Euro 与 reliability-gated One Euro。

---

## 0. 如何使用本文档

每个脚本都给出：文件路径、类型（MonoBehaviour / 纯类 / 模块）、职责、关键字段与方法签名。
落地顺序见 §14 的 checklist。先做 Unity 三份日志跑通，再写 Python `eval/`，最后接回放。

核心隔离原则（贯穿全程）：

- **评估代码与运行时代码物理 + 编译期隔离**。Unity 侧独立 asmdef，单向依赖 `eval → runtime`；Python 侧独立顶层 `eval/`，不进 `src/egoanchor` 包、不 import 运行时模块（只读 JSONL）。
- **Ground Truth（手柄 pose）绝不进入锚定管线**。隔离的 asmdef 从编译期杜绝这种污染。
- **录一次，离线算所有**。日志记够原始量，filter/对齐方式的 ablation 尽量离线复算。

---

## 1. 已锁定的设计决策

| 决策           | 选择                                                                 | 后果                                                                                                             |
| -------------- | -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Unity 运行方式 | Editor + Quest Link（同一 PC）                                       | 日志直写本地 `data/eval/`，免 adb pull；两进程共享系统墙钟，`created_unix_ms` 直接可比，网络腿时延可直接相减 |
| GT 来源        | 左右手柄 `controller_left` / `controller_right`，Meta SDK `OVRInput` LTouch/RTouch → 世界系 | GT 连续、零成本、最可靠；被追踪物体本身就是手柄，标定的 `X` 定义明确；左右各一套 mesh 与 SDK 原点 |
| GT 偏移处理    | hand-eye 标定常量刚体变换 `X = C_T_A`（SDK 手柄系 ↔ mesh 原点系），**左右各标定一份** | 吸收固定安装偏置，评估量纯抖动/漂移；左右手柄 X 不同，按 session 的手柄归属各算 |
| ablation 方式  | P1a 多 runtime 并行实机录制 + P1b `AcceptWorldPose` 回放           | RQ2 公平（同输入流）且可复现；评的是出货 C# filter 本体                                                          |
| 其他物体       | mouse/earphone 本轮只出 overlay 视频，不进定量                       | 聚焦核心数据                                                                                                     |

Editor+Link 的代价（写入论文 limitations）：Link 的真实网络/编码时延被低估，latency 数字偏乐观。
若需论文级 latency，后续补一轮 Quest 独立录制；代码两条路径都支持，仅路径/对时配置不同。

---

## 2. 要采集的三份数据（决定一切）

每个指标反推需要什么，先把账算清。Python 端现有 `pose_result` JSONL（timing、reliability、pose 矩阵）已够用；**Unity 端缺三份**。

### 2.1 `unity_capture.jsonl` — 每 frame_id 一行（~8fps，与发送帧同步）

| 字段                        | 类型         | 说明                                                                                |
| --------------------------- | ------------ | ----------------------------------------------------------------------------------- |
| `event`                   | str          | 固定 `"unity_capture"`                                                            |
| `frame_id`                | long         | Quest stereo 帧号，全局 join 主键                                                   |
| `capture_mono_ms`         | double       | 采集时刻 Unity 单调时钟（`Time.realtimeSinceStartupAsDouble*1000`），latency 起点 |
| `capture_unix_ms`         | double       | 采集时刻系统墙钟，跨进程对时校验                                                    |
| `head_pos` / `head_rot` | float[3]/[4] | 采集时刻头（CenterEye）世界位姿                                                     |
| `cam_pos` / `cam_rot`   | float[3]/[4] | 采集时刻对齐参考相机（左目）世界位姿                                                |
| `gt_pos` / `gt_rot`     | float[3]/[4] | **采集时刻手柄世界位姿（GT）**                                                |
| `gt_tracked`              | bool         | `OVRInput.GetControllerPositionTracked` 与置信，剔除丢踪帧                        |

服务于：anchor error、RQ1 离线对齐、latency 起点、X 标定。

### 2.2 `unity_output.jsonl` — 每渲染 tick 一行（~90fps）

| 字段                                     | 类型         | 说明                                                                                               |
| ---------------------------------------- | ------------ | -------------------------------------------------------------------------------------------------- |
| `event`                                | str          | 固定 `"unity_output"`                                                                            |
| `render_mono_ms` / `render_unix_ms`  | double       | 该 tick 时戳                                                                                       |
| `source_frame_id`                      | long         | 当前显示位姿对应的最新 frame_id（latency 终点用 `t_apply(frame_id)` = 首次该帧被 apply 的 tick） |
| `head_pos` / `head_rot`              | float[3]/[4] | 该 tick 头世界位姿（slip/jitter 相对真值用）                                                       |
| `gt_pos` / `gt_rot` / `gt_tracked` | …           | **该 tick 手柄世界位姿（GT）**                                                               |
| `variants`                             | object[]     | 每个被记录 runtime 变体一项（见下）                                                                |

`variants[i]`：

| 字段                                      | 说明                                                                      |
| ----------------------------------------- | ------------------------------------------------------------------------- |
| `label`                                 | 变体名（`"raw"` / `"lowpass"` / `"kalman"` / `"one_euro"` / `"egoanchor_one_euro"` …）  |
| `has_pose`                              | 该变体当前是否有可用 stable pose                                          |
| `pos` / `rot`                         | 该变体显示位姿                                                            |
| `anchor_state`                          | 该变体 anchor lifecycle 状态（Tracking/Coasting/Lost…，无 lifecycle 则空）            |
| `policy_action` / `policy_reason`     | accept/reject/hold 及原因（jump suppression 用）；`one_euro` 可为空，`egoanchor_one_euro` 必填 |
| `aligned_raw_pos` / `aligned_raw_rot` | **对齐后未滤波的 raw 世界位姿**（P1b 回放输入，只需在主变体记一次） |
| `reliability_score`                     | 该 frame 的可靠性分（回放输入）                                           |

服务于：jitter、lag、slip、latency 终点、jump suppression、P1b 回放输入。

### 2.3 `session_manifest.json` — 每 session 一份

| 字段                       | 说明                                                                                                     |
| -------------------------- | -------------------------------------------------------------------------------------------------------- |
| `session_id`             | 与日志文件名一致的会话 ID                                                                                |
| `object_id`              | `"controller_left"` 或 `"controller_right"`（每 session 一个手柄）                                |
| `unity_run_mode`         | `"editor_link"` / `"quest_standalone"`                                                               |
| `gt_source`              | `"ovr_ltouch"` 或 `"ovr_rtouch"`，与 `object_id` 一致                                              |
| `mono_to_unix_offset_ms` | session 启动时 `unix - mono` 偏移，便于把 mono 映射到墙钟                                              |
| `condition_spans`        | 区间列表 `[{label, start_mono_ms, end_mono_ms}]`，标注 static/slow/fast/occlusion/out-of-view/lighting |
| `event_markers`          | 瞬时事件 `[{type, mono_ms}]`，如 occlusion_start/end、out_of_view、reappear                            |
| `variant_labels`         | 录制时启用的变体名列表                                                                                   |
| `notes`                  | 自由备注                                                                                                 |

服务于：recovery、按条件切分、跨进程对时基准。

### 2.4 关键设计点

- **GT 记两个采样率**：每 frame_id 一份（给 anchor error 和标定），每渲染 tick 再记一份（给 lag/jitter 对连续真值的比较）。GT 一次 `OVRInput` 读，近零成本，渲染帧每帧记无压力。
- **多变体同帧记录**：`AnchorRuntimeHub` 本就支持喂同一输入给 N 个 `PoseToAnchorRuntime`。RQ2 的 raw/low-pass/Kalman/vanilla One Euro/reliability-gated One Euro 做成 N 个并行 runtime，**一次录制全拿到**，对比绝对公平（同一输入流）。
- **RQ1 纯离线，不需独立 runtime**：有 `unity_capture` 的"采集时刻头位姿" + Python 的 camera-space 矩阵 `C_T_O` + `unity_output` 的"结果到达 tick 头位姿"，离线就能同时算 arrival-time 与 frame-aligned 两种映射并各自比 GT。

---

## 3. 同步与时钟规则（anchor 评估的命门）

RQ1 本质就是"用对时间戳"，所以对齐规则必须严格、写死成约定：

1. **按 `frame_id` 精确 join，不靠时间插值**。三份日志（Python `pose_result`、`unity_capture`、`unity_output`）都带 frame_id。
2. **端到端时延全程用 Unity 单调时钟**：`t_capture(frame_id)`（来自 `unity_capture`）与 `t_apply(frame_id)`（`unity_output` 中该 frame_id 首次被 apply 的 tick `render_mono_ms`）都在 Unity 记 → 端到端 latency 无需跨进程对时，最准。
3. **分模块 breakdown 用 Python 单时钟**：yolo/depth/cutie/pose/total 来自 `pose_result.timing`，自洽。
4. **网络腿（同机）直接相减**：Editor+Link 下两进程共享系统墙钟，`unity publish_unix` → `python server_receive` 与 `python server_publish` → `unity receive_unix` 直接用墙钟相减。无需估偏移。
5. **GT 数据卫生**：`gt_tracked=false` 或低置信的 GT 帧剔除（手柄背到身后会丢踪）。OVRInput 是预测位姿，静态/慢速无影响；快速段 lag 指标须标注此偏差（列入 limitations）。
6. **mono↔unix 兜底**：每条记录同时记 mono + unix 两个时戳；manifest 记 session 级 `mono_to_unix_offset_ms` 作为兜底映射。

---

## 4. Unity 侧实现

### 4.1 目录与程序集（隔离）

新增目录 `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/`，带**自己的** asmdef。

**文件：`EgoAnchorEval.asmdef`**

```json
{
  "name": "EgoAnchorEval",
  "references": ["EgoAnchor", "Oculus.VR", "meta.xr.mrutilitykit", "Unity.TextMeshPro"],
  "autoReferenced": true
}
```

- 单向依赖：`eval → runtime`。`EgoAnchor.asmdef` **绝不**引用 `EgoAnchorEval`，编译期保证 GT 不可能污染锚定管线。
- 引用 `Oculus.VR`（OVRInput/OVRCameraRig）、`meta.xr.mrutilitykit`（相机 intrinsics）。

### 4.2 组件清单与职责

| 文件                                 | 类型          | 职责                                                       |
| ------------------------------------ | ------------- | ---------------------------------------------------------- |
| `EgoAnchorEval.asmdef`             | asmdef        | 隔离程序集                                                 |
| `ControllerGroundTruthProvider.cs` | MonoBehaviour | 左/右手柄 → 世界系 GT pose + tracked 标志（可配 LTouch/RTouch）   |
| `JsonlFileWriter.cs`               | 纯 C#         | 缓冲写盘，定期 flush，线程安全 append                      |
| `AnchorEvalRecorder.cs`            | MonoBehaviour | 核心记录器：双采样率、多变体，写 capture + output 两份日志 |
| `EvalSessionController.cs`         | MonoBehaviour | session 开停、条件标签、事件标记、写 manifest              |
| `ReplayPoseSource.cs`              | MonoBehaviour | P1b：读录好的 raw 世界位姿流，按时戳重泵进 runtime         |

### 4.3 `ControllerGroundTruthProvider.cs`

职责：把 Meta SDK 的手柄局部位姿变换到 Unity 世界系，输出统一的 `(Pose, bool tracked)`。采集时刻与渲染时刻共用同一个实例（OVRInput 每帧只更新一次，同帧多次读得同值）。`controller` 字段按本次 session 追踪的手柄配置为 LTouch 或 RTouch，与 Python 端 `--object controller_left/right` 对应。

```csharp
public sealed class ControllerGroundTruthProvider : MonoBehaviour
{
    [SerializeField] private OVRCameraRig cameraRig;          // 拖入场景的 OVRCameraRig
    [SerializeField] private OVRInput.Controller controller = OVRInput.Controller.RTouch;  // 本 session 追的手柄：LTouch / RTouch

    // 读取当前手柄世界位姿。trackingSpace 把局部位姿变到世界系。
    public bool TryGetWorldPose(out Pose worldPose, out bool tracked)
    {
        Vector3 localPos = OVRInput.GetLocalControllerPosition(controller);
        Quaternion localRot = OVRInput.GetLocalControllerRotation(controller);
        Transform space = cameraRig.trackingSpace;
        worldPose = new Pose(space.TransformPoint(localPos), space.rotation * localRot);
        tracked = OVRInput.GetControllerPositionTracked(controller)
               && OVRInput.GetControllerOrientationTracked(controller);
        return true;
    }
}
```

要点：`cameraRig` 通过 serialized field 拖拽（项目既有约定，无 FindObjectOfType）；`controller` 按 session 追的手柄选 LTouch/RTouch，必须与 Python `--object` 和 manifest `gt_source` 三者一致。

### 4.4 `JsonlFileWriter.cs`

职责：把对象序列化成单行 JSON 追加写盘。缓冲 + 周期 flush，避免每帧 IO 卡渲染。

```csharp
public sealed class JsonlFileWriter : IDisposable
{
    public JsonlFileWriter(string filePath, int flushEveryLines = 64);
    public void WriteLine(string jsonLine);   // 入队，满阈值或定时 flush
    public void Flush();
    public void Dispose();                     // 关闭前 flush
}
```

要点：

- 序列化用轻量手写 JSON（避免引第三方库，且字段固定）；或用 Unity `JsonUtility`（需 `[Serializable]` DTO，注意它不支持顶层数组/字典，variants 用包装类）。
- 写在后台线程或用 `StreamWriter` + 周期 flush；Editor 下直接写 `EgoAnchor_Python/data/eval/<session>/` 的绝对路径（serialized 字段配置）。
- 文件名约定与 Python 端一致：`<session_id>_unity_capture.jsonl` / `_unity_output.jsonl`。

### 4.5 `AnchorEvalRecorder.cs`（核心）

职责：两个采样率分别落两份日志。

```csharp
[Serializable]
public struct RecordedRuntime
{
    public string label;                 // "raw" / "lowpass" / "kalman" / "one_euro" / "egoanchor_one_euro"
    public PoseToAnchorRuntime runtime;  // 拖入对应 runtime
    public bool isPrimary;               // 主变体：额外记 aligned_raw + reliability（回放输入）
}

public sealed class AnchorEvalRecorder : MonoBehaviour
{
    [SerializeField] private string outputDir;                         // data/eval 绝对路径
    [SerializeField] private ControllerGroundTruthProvider gt;
    [SerializeField] private Transform headAnchor;                     // CenterEyeAnchor
    [SerializeField] private CameraReference alignmentReference;       // 与 runtime 一致（Left）
    [SerializeField] private StereoFrameSource stereoSource;           // 订阅 FrameCaptured
    [SerializeField] private FramePoseHistory framePoseHistory;        // 取采集时刻相机位姿
    [SerializeField] private List<RecordedRuntime> recordedRuntimes;   // 各变体
    [SerializeField] private bool recording;                           // 由 SessionController 控制

    void OnEnable()  { stereoSource.FrameCaptured += OnFrameCaptured; }
    void OnDisable() { stereoSource.FrameCaptured -= OnFrameCaptured; }

    // 采集时刻回调（与发送帧同 Unity 帧）：写 unity_capture
    private void OnFrameCaptured(long frameId, double captureMonoMs)
    {
        if (!recording) return;
        gt.TryGetWorldPose(out Pose gtPose, out bool tracked);
        // 从 framePoseHistory 取该 frameId 的相机/中心位姿；headAnchor 取头位姿
        // 组 JSON 一行 → captureWriter.WriteLine(...)
    }

    // 渲染 tick：写 unity_output（每变体一项）
    void LateUpdate()
    {
        if (!recording) return;
        gt.TryGetWorldPose(out Pose gtPose, out bool tracked);
        // 遍历 recordedRuntimes：TryGetStablePose / 诊断属性 / (主变体) TryGetRawPose + reliability
        // 组 JSON 一行（含 variants 数组）→ outputWriter.WriteLine(...)
    }
}
```

读各变体数据用 `PoseToAnchorRuntime` 现有公开 API：`TryGetStablePose`、`TryGetRawPose`、`LatestAlignedFrameId`、`CurrentAnchorState`、`LatestPolicyAction`、`LatestPolicyReason`、`LatestReliabilityScore`。
**无需为记录改 runtime**——这些都是现成只读接口。

### 4.6 `EvalSessionController.cs`

职责：控制录制生命周期、打条件/事件标签、生成 manifest。

```csharp
public sealed class EvalSessionController : MonoBehaviour
{
    [SerializeField] private AnchorEvalRecorder recorder;
    [SerializeField] private string objectId = "controller_right";   // 本 session 追的手柄：controller_left / controller_right

    public void StartSession();                         // 生成 session_id，建目录，置 recording=true
    public void StopSession();                          // recording=false，flush，写 manifest
    public void BeginCondition(string label);           // 记 condition span 起点
    public void EndCondition();                         // 记终点
    public void Mark(string eventType);                 // 瞬时事件（occlusion_start 等）
}
```

绑定：场景已有 `Button_Reset/Resume/Pause/ForceReacquire`。新增 `Button_EvalStart/Stop`（或 Editor 下键盘热键）触发 `StartSession/StopSession`；条件切换与事件标记用按钮或键盘，便于录制时单手操作。

### 4.7 唯一的运行时改动（一条缝）

**修改 `Quest/StereoFrameSource.cs`**：新增事件，在它记录 frame_id 相机位姿处触发。

```csharp
public event Action<long, double> FrameCaptured;   // (frameId, captureMonoMs)
// 在已有的「记录 frame_id → 相机位姿」之后：
FrameCaptured?.Invoke(frameId, Time.realtimeSinceStartupAsDouble * 1000.0);
```

理由：只有 `StereoFrameSource` 知道 frame_id 的诞生时刻，recorder 必须在**同一 Unity 帧**采 GT，才能保证 GT 与相机位姿同瞬间。无订阅者时零成本。
（保守备选：暴露只读 `LastCapturedFrameId` + `CapturedThisFrame`，recorder 在 LateUpdate 轮询。推荐事件，更准。）

### 4.8 挂载设计（对照现有场景）

场景 `Server` 父物体下已有：`AnchorRuntimeHub`、`AnchorPolicyHost`、`AnchorObject`（stable）、`AnchorObject Raw`、`StereoFrameSource`、`FramePoseHistory`、`CameraInfoSource`；以及 `OVRCameraRig/CenterEyeAnchor`。沿用 serialized field 拖拽约定：

1. 新建空 GameObject `EvalRig`（挂 `Server` 下），挂 `AnchorEvalRecorder` + `EvalSessionController` + `ControllerGroundTruthProvider`。
2. `ControllerGroundTruthProvider.cameraRig` ← 场景 `OVRCameraRig`。
3. `AnchorEvalRecorder` 各字段拖入：`gt` ← 同物体的 provider；`headAnchor` ← `CenterEyeAnchor`；`stereoSource`/`framePoseHistory`/`alignmentReference` ← 对应组件（与 runtime 配置一致）；`outputDir` ← `data/eval` 绝对路径。
4. `recordedRuntimes` 列表：P1a 先连 `AnchorObject`(stable, isPrimary=true) 与 `AnchorObject Raw`(raw)。做 RQ2 ablation 时，往 `AnchorRuntimeHub.runtimes` 再加 lowpass、kalman、one_euro、egoanchor_one_euro 等 runtime 子物体，然后也拖进这个 list——**纯场景配置，不改代码**。
5. UI：`EvalSessionController` 监听新增按钮/键盘。

---

## 5. Python 侧实现（离线分析）

### 5.1 目录（隔离、不进包）

新增**顶层** `EgoAnchor_Python/eval/`（与 `src/` 平级，独立目录，**不 import egoanchor**，只读 JSONL）：

```
EgoAnchor_Python/eval/
  __init__.py
  io/
    __init__.py
    log_loader.py        # 读三份 Unity JSONL + Python pose_result，按 frame_id / 时间 join
    schemas.py           # 各日志行的 dataclass + 字段校验
  calib/
    __init__.py
    hand_eye.py          # 求常量 X (controller→anchor)，鲁棒
  metrics/
    __init__.py
    anchor_error.py      # World-space anchor error
    slip.py              # Head-motion-induced slip（屏幕空间 + 世界空间）
    jitter.py            # 静态窗 jitter
    lag.py               # 互相关 lag + 阶跃上升时间
    latency.py           # 端到端 + 分模块 breakdown，P50/P90/P95
    recovery.py          # recovery success rate / time / failure taxonomy
    jump_suppression.py  # 坏跳变拒绝数量与幅度
    common.py            # SE(3)/SO(3) 工具：matrix↔(pos,quat)、angle、插值、高通
  report/
    __init__.py
    tables.py            # pandas → 论文 Table 2 / Table 3
    figures.py           # matplotlib → Fig 7 / Fig 8 等
  run_eval.py            # CLI 主入口：一条命令产出某 session 全部表图
```

pixi 任务（沿用 `python <path> --args` 约定，加到 `pixi.toml [tasks]`）：

```toml
eval         = "python eval/run_eval.py --session-dir data/eval/{session}"
eval-calib   = "python eval/run_eval.py --session-dir data/eval/{session} --only calib"
eval-figures = "python eval/run_eval.py --session-dir data/eval/{session} --only figures"
```

输出写 `data/eval/<session>/report/`。依赖 numpy/scipy/pandas/matplotlib/opencv 均已在环境。

### 5.2 `io/log_loader.py`

职责：把四份日志读成 DataFrame，并提供两种 join。

```python
class SessionLogs:
    capture: pd.DataFrame      # unity_capture，index=frame_id
    output:  pd.DataFrame      # unity_output 展平（每 variant 一行，多列 label）
    pose:    pd.DataFrame      # Python pose_result，index=frame_id
    manifest: dict

def load_session(session_dir: Path) -> SessionLogs: ...
def join_by_frame(logs) -> pd.DataFrame:   # capture ⋈ pose on frame_id，给 anchor error / RQ1 / latency
def label_conditions(df, manifest) -> pd.DataFrame:   # 用 condition_spans 给每行打 condition 列
```

要点：`unity_output` 的 `variants` 数组展平成长表（列 `label`），方便 groupby 按变体算指标。`gt_tracked=false` 行打 `valid=False`，指标函数默认过滤。

### 5.3 `calib/hand_eye.py`（标定常量 X）

我们的 anchor 是 mesh 原点世界位姿 `W_T_A`，GT 是手柄世界位姿 `W_T_C`，二者差恒定刚体变换 `X = C_T_A`，使 `W_T_A = W_T_C · X`。

> **左右手柄的 X 不同，各标定一份。** 左右手柄是不同物体（mesh `MetaQuestTouchPlus_Left.glb` / `MetaQuestTouchPlus_Right.glb`，SDK 原点 LTouch / RTouch），mesh 原点与 SDK 手柄原点的相对关系互不相同。每条 session 只追一个手柄，标定就用该 session 的 `(W_T_C, W_T_A)` 算出对应那只手的 `X`。跨 session 复用 X 时必须按 `manifest.object_id` 匹配，**不可混用**。两只手的 session 各自独立标定、独立出指标，最后可分手柄报告或合并统计。

```python
def estimate_hand_eye(
    w_T_c: np.ndarray,    # (N,4,4) GT 手柄世界位姿
    w_T_a: np.ndarray,    # (N,4,4) anchor 世界位姿（取高可靠 + 静态子集）
    use_ransac: bool = True,
) -> tuple[np.ndarray, dict]:   # 返回 X (4,4) 与诊断（逐帧残差方差等）
    ...
```

算法：

- 每帧 `X_i = inv(W_T_C_i) @ W_T_A_i`，理论全相等。
- **旋转**：各 `X_i` 取四元数，累加外积 `M = Σ qᵢqᵢᵀ`，取最大特征向量 → chordal L2 均值（四元数符号先统一）。
- **平移**：旋转定后 `t_X = median_i(t_i)`。
- **RANSAC**：用静态 + 高 reliability 子集做内点，剔除坏 anchor 帧。
- **可观测性校验**：若手柄旋转激励不足（旋转范围小），在诊断里报警——这要求录制协议含"手柄充分三轴旋转"段（见 §8）。
- 标定吸收固定安装偏置，于是后续指标量的是**抖动/漂移**而非偏置。

诊断输出（写进 report）：`X` 的逐帧残差方差应很小，否则说明对齐/录制有问题。

### 5.4 `metrics/common.py`（共享几何工具）

```python
def mat_to_pos_quat(T): ...
def pos_quat_to_mat(p, q): ...
def pose_error(w_T_c, X, w_T_a):     # E = inv(W_T_C·X)·W_T_A → (e_t[m], e_r[deg])
def angle_deg(q): ...                 # 四元数 → 角度
def slerp_lerp_resample(t_src, p, q, t_dst): ...   # 位姿重采样到目标时间网格
def highpass(signal, dt, cutoff_hz): ...           # 去慢漂，留抖动
def project_point(K, w_T_cam, p_world): ...         # 世界点 → 头相机像面（slip 用）
```

### 5.5 八个指标的精确定义（逐个对应论文 §8）

记每帧误差 `E = inv(W_T_C·X)·W_T_A`，`e_t=‖E.t‖`(m)、`e_r=angle(E.R)`(deg)。

| # | 指标（论文名）                         | 模块                    | 定义                                                                                                                                                                                                               |
| - | -------------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1 | **World-space anchor error**     | `anchor_error.py`     | 每条件报 `e_t,e_r` 的 RMSE/median/p95。用 stable 变体接受该 frame_id 时的值。                                                                                                                                    |
| 2 | **Head-motion-induced slip**     | `slip.py`             | headline 用屏幕空间：anchor 原点与 GT 原点用头相机 intrinsics 投影到像面，`slip_px=‖proj(W_T_A)−proj(W_T_C·X)‖`，头动窗口报峰值/RMS，并与头部 yaw 角速度相关。辅助：世界空间下 anchor 位移与头速的相关分量。 |
| 3 | **World-space jitter**           | `jitter.py`           | GT 速度<阈值自动切静止窗，对 stable 位姿高通去慢漂后报位置/旋转 std/RMS。raw vs lowpass vs kalman vs one_euro vs egoanchor_one_euro 同窗对比。                                                                                         |
| 4 | **Lag**                          | `lag.py`              | anchor 与 GT 位置重采样到均匀网格，速度信号归一化互相关 `lag=argmax`；另在快速平移段报阶跃响应上升时间（到 90%）。                                                                                               |
| 5 | **End-to-end latency**           | `latency.py`          | 每 frame_id `t_apply−t_capture`（Unity 单时钟）；分模块用 Python timing；网络腿用墙钟相减。报 P50/P90/P95 + breakdown（Table 3）。                                                                              |
| 6 | **Recovery success rate / time** | `recovery.py`         | 用 manifest 的遮挡/出视野/返回标记 + anchor_state 流 + 误差回落阈值。`recovery_time` = 物体重现标记 → 首次持续"accepted 且 e_t<阈"。                                                                            |
| 7 | **Jump rejection / suppression** | `jump_suppression.py` | 对比 raw/vanilla One Euro（不拦或弱拦的跳变尖峰）与 egoanchor_one_euro（抑制后）：误差尖峰计数 + 幅度；统计 Python re-register / Unity reject/hold 原因。                                                                                       |
| 8 | **Task / 主观**（可选）          | —                      | 本轮只留 event marker 钩子，不实现。                                                                                                                                                                               |

### 5.6 RQ → 指标 → 数据 映射（`run_eval.py` 产出）

| RQ   | 主对比                                | 指标                                        | 数据来源                                                                |
| ---- | ------------------------------------- | ------------------------------------------- | ----------------------------------------------------------------------- |
| RQ1  | arrival-time vs frame-aligned         | anchor error、slip                          | 离线：capture 头位姿 +`C_T_O`(pose_result) + arrival tick 头位姿 + GT |
| RQ2  | raw / low-pass / Kalman / vanilla One Euro / reliability-gated One Euro | jitter、lag、jump suppression、stable error | 并行 runtime 的 `unity_output` + GT                                   |
| RQ3  | always-update vs hold/coast/reacquire | recovery rate/time、failure taxonomy        | manifest 标记 + state 流 + error                                        |
| 通用 | —                                    | end-to-end latency breakdown                | 三份日志 join                                                           |

`run_eval.py` 流程：`load_session` → `estimate_hand_eye`（缓存 X 到 report）→ 各 metric 模块按条件计算 → `tables.py`/`figures.py` 输出 → 写 `report/`。

---

## 6. P1b：确定性回放（RQ2 公平 + 可复现）

目的：录一次真实 raw 流，让 RQ2 各 filter ablation 在**同一输入**上可复现地复算，且评估的是出货的 C# filter 本体（无 Python 重写偏差）。这一步尤其用于区分 Kalman、vanilla One Euro 和 EgoAnchor 的 modified One Euro，而不是只证明“加滤波会更稳”。

### 6.1 天然注入缝（已存在，无需新增运行时接口）

`PoseToAnchorRuntime` 已有公开方法 `AcceptWorldPose(long frameId, Pose worldPose)`（"直接注入世界位姿，供测试"）。这就是回放注入点。

### 6.2 `ReplayPoseSource.cs`

```csharp
public sealed class ReplayPoseSource : MonoBehaviour
{
    [SerializeField] private string replayFilePath;              // 录好的 raw 流 jsonl
    [SerializeField] private AnchorRuntimeHub hub;               // 或直接持有目标 runtimes
    [SerializeField] private bool useOriginalTiming = true;      // 按原 mono 间隔重放
    [SerializeField] private float speed = 1.0f;

    void Update()
    {
        // 按 render_mono_ms 节奏，把到期的 (frame_id, aligned_raw_pose, reliability)
        // 通过 hub 分发给各 runtime 的 AcceptWorldPose（或扩展一个带 reliability 的注入）
    }
}
```

回放输入来源：P1a 在 `unity_output` 主变体里记的 `aligned_raw_pos/rot` + `reliability_score` + `source_frame_id` + `render_mono_ms`。

### 6.3 回放注意

- 回放 tick 与原始渲染 tick 不会逐帧对齐 → jitter/lag 对比时 GT 按时戳插值到回放 tick（`slerp_lerp_resample`）。静态段 GT 近常量无影响，运动段插值，列入方法说明。
- filter/policy 在真实 MonoBehaviour 的 Update 里照常 90fps predict，所以评的就是真实时序行为。
- 注入若需带 reliability，给 `PoseToAnchorRuntime` 加一个轻量重载 `AcceptWorldPose(frameId, worldPose, reliabilityScore)`（向后兼容，旧重载转调新重载默认 1.0）。这是回放唯一可能的运行时小改动，且非侵入。

---

## 7. 端到端数据流总览

```
录制（P1a，实机 Editor+Link）
  StereoFrameSource.FrameCaptured(frameId, t) ──► AnchorEvalRecorder.OnFrameCaptured
                                                      └─► unity_capture.jsonl（GT@capture + 相机/头位姿）
  每渲染 tick: AnchorEvalRecorder.LateUpdate
                  └─► unity_output.jsonl（GT@tick + raw/lowpass/kalman/one_euro/egoanchor_one_euro 显示位姿 + 主变体 aligned_raw + reliability）
  Python 运行时已产出: <session>_pose_result（runtime_logs，含 C_T_O 矩阵 + timing）
  EvalSessionController ──► session_manifest.json（条件/事件标签 + 对时基准）

离线分析（Python eval/）
  load_session → estimate_hand_eye(X) → metrics/* 按条件计算 → report/ 表+图

回放（P1b，可选复现）
  ReplayPoseSource 读 aligned_raw 流 → AcceptWorldPose → 各 filter 变体（含 Kalman/One Euro）→ 重录 unity_output → 同分析管线
```

---

## 8. 录制协议（一起采的"动作脚本"）

`EvalSessionController` 每段用 `BeginCondition/EndCondition` 打标签，瞬时事件用 `Mark`。左右手柄各跑一轮完整协议（`controller_left` 与 `controller_right` 分别启动 Python `--object`、Unity provider 配对应 LTouch/RTouch）：

| 段 | 时长 | 动作                                  | 条件标签                           | 服务指标                       |
| -- | ---- | ------------------------------------- | ---------------------------------- | ------------------------------ |
| 1  | 30s  | 物体放定、头不动                      | `static`                         | jitter floor、精度底           |
| 2  | 30s  | 物体放定、头自然左右上下              | `slow_head`                      | 日常 MR、slip 基线             |
| 3  | 20s  | 物体放定、猛转头 yaw/平移             | `fast_head`                      | head-motion slip 峰值          |
| 4  | 30s  | **手持手柄平移 + 充分三轴旋转** | `object_motion`                  | **X 标定关键激励** + lag |
| 5  | 20s  | 手挡住物体一部分                      | `occlusion`（+ Mark start/end）  | 坏/缺观测、jump                |
| 6  | ×5  | 移出视野再返回                        | `out_of_view`（+ Mark reappear） | recovery                       |
| 7  | 20s  | 开关灯/换背景                         | `lighting`                       | 感知鲁棒                       |

要点：

- **第 4 段是 X 标定的硬约束**，旋转必须覆盖三轴足够范围，否则 `hand_eye` 旋转维度不可辨识（`estimate_hand_eye` 会报警）。
- 每条件同时录 raw + 所有 ablation 变体（并行 runtime），一次成型。

---

## 9. 文件改动总表（本阶段）

### Unity（`Assets/Scripts/EgoAnchorEval/`，新程序集）

| 文件                                 | 动作                     | 职责                                    |
| ------------------------------------ | ------------------------ | --------------------------------------- |
| `EgoAnchorEval.asmdef`             | 新增                     | 隔离程序集，单向依赖 runtime            |
| `ControllerGroundTruthProvider.cs` | 新增                     | 左/右手柄（LTouch/RTouch）→ 世界系 GT + tracked |
| `JsonlFileWriter.cs`               | 新增                     | 缓冲落盘                                |
| `AnchorEvalRecorder.cs`            | 新增                     | 双采样率多变体日志                      |
| `EvalSessionController.cs`         | 新增                     | session/条件/事件/manifest              |
| `ReplayPoseSource.cs`              | 新增（P1b）              | 确定性回放                              |
| `Quest/StereoFrameSource.cs`       | **修改（一条缝）** | 新增 `FrameCaptured` 事件             |
| `Runtime/PoseToAnchorRuntime.cs`   | 修改（P1b，可选）        | `AcceptWorldPose` 带 reliability 重载 |

### Python（`EgoAnchor_Python/eval/`，新顶层目录）

| 文件                                     | 动作     | 职责                                              |
| ---------------------------------------- | -------- | ------------------------------------------------- |
| `eval/io/log_loader.py` `schemas.py` | 新增     | 读 + join 日志                                    |
| `eval/calib/hand_eye.py`               | 新增     | 标定常量 X                                        |
| `eval/metrics/*.py`（8 个 + common）   | 新增     | 8 指标                                            |
| `eval/report/tables.py` `figures.py` | 新增     | 论文表/图                                         |
| `eval/run_eval.py`                     | 新增     | CLI 主入口                                        |
| `pixi.toml`                            | 修改     | `eval` / `eval-calib` / `eval-figures` 任务 |
| `data/eval/`                           | 新增目录 | 日志与报告产物                                    |

---

## 10. 落地 checklist（建议顺序）

**Step 1 — 打通采集骨架（先验证日志能落盘）**

- [ ] `EgoAnchorEval.asmdef`
- [ ] `JsonlFileWriter.cs`（先能写一行测试 JSON）
- [ ] `StereoFrameSource.cs` 加 `FrameCaptured` 事件
- [ ] `ControllerGroundTruthProvider.cs` + 场景挂载，确认 LTouch 与 RTouch 都能读出手柄世界位姿（Inspector 打印验证）

**Step 2 — 三份日志**

- [ ] `AnchorEvalRecorder.cs`：先只记 capture，再加 output 多变体
- [ ] `EvalSessionController.cs` + UI 按钮/热键
- [ ] 场景 `EvalRig` 挂载、字段拖拽（含 `AnchorObject` 与 `AnchorObject Raw` 两变体）
- [ ] 跑一小段，确认三份 JSONL + manifest 格式正确、frame_id 能对上 Python 日志

**Step 3 — Python 分析底座**

- [ ] `eval/io/log_loader.py` + `schemas.py`：能 load + join + 按条件切分
- [ ] `eval/calib/hand_eye.py`：标定 X，诊断逐帧残差方差小（验证对齐正确）
- [ ] `eval/metrics/common.py`：几何工具 + 单测

**Step 4 — 指标与报告（产出基线数据）**

- [ ] `anchor_error` → `latency` → `jitter` → `slip` → `jump_suppression` → `lag` → `recovery`（按依赖先后）
- [ ] `report/tables.py` `figures.py`
- [ ] `run_eval.py` 串起来；`pixi run eval` 出 RQ1 + latency + 当前 stable/raw 的 jitter/slip/error/jump

**Step 5 — P1b 回放（可复现 + 为 P3 铺路）**

- [ ] `ReplayPoseSource.cs`（+ 可选 `AcceptWorldPose` reliability 重载）
- [ ] 录一段 raw 流，回放出各 filter 变体，确认与实机一致

---

## 11. 验证标准（本阶段完成的定义）

- 能跑完整录制协议，产出三份 Unity 日志 + manifest，frame_id 与 Python `pose_result` 完全对应。
- `estimate_hand_eye` 的 `X` 逐帧残差方差小（对齐正确的硬证据）。
- `pixi run eval` 一条命令产出：RQ1（arrival-time vs frame-aligned 的 anchor error/slip）、end-to-end latency breakdown（P50/90/95）、当前 stable 与 raw 的 jitter/slip/anchor-error/jump suppression 表与图。
- 这套基线数字成为后续 P2（几何质量评分）/P3（统一 SE(3) filter）所有改动的对照组。

---

## 12. 风险与待确认

| 风险                                        | 缓解                                                            |
| ------------------------------------------- | --------------------------------------------------------------- |
| OVRInput 手柄位姿是预测值，快速段与真实有偏 | 静态/慢速无影响；快速段 lag 标注此偏差，列 limitations          |
| Editor+Link 低估真实网络/编码时延           | latency 数字标注偏乐观；需论文级数据时补 Quest 独立录制         |
| 手柄旋转激励不足 → X 不可辨识              | 录制协议第 4 段强制三轴充分旋转；`hand_eye` 自动报警          |
| 每渲染帧写盘卡顿                            | `JsonlFileWriter` 缓冲 + 后台 flush；必要时 output 降到 ~30Hz |
| JsonUtility 不支持顶层数组/字典             | variants 用 `[Serializable]` 包装类；或手写 JSON              |
| 双盲：日志含路径/用户名                     | 投稿前清理 session 元数据（已在论文 desk-reject 清单）          |
