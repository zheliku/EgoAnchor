using System;
using EgoAnchor.Quest;
using UnityEngine;

namespace EgoAnchor.Anchor
{
    public sealed partial class PoseToAnchorRuntime
    {
        /// <summary>
        /// PoseToAnchorRuntime 的 Inspector 诊断快照。
        /// </summary>
        [Serializable]
        public sealed class RuntimeDiagnostics
        {
            /// <summary>最近成功对齐的 frame_id。</summary>
            [Tooltip("最近成功对齐的 frame_id。只用于 Inspector/日志诊断。")]
            public long latestAlignedFrameId = -1;

            /// <summary>最近一次 PoseResult phase。</summary>
            [Tooltip("最近一次 PoseResult phase。只用于 Inspector/日志诊断。")]
            public string latestPhase = "";

            /// <summary>最近一次失败原因。</summary>
            [Tooltip("最近一次失败原因。空字符串表示最近一次处理没有失败。")]
            public string latestFailure = "";

            /// <summary>当前 Unity anchor 生命周期状态。</summary>
            [Tooltip("当前 Unity anchor 生命周期状态。该状态属于 Unity anchor runtime，不等同于 Python pipeline phase。")]
            public AnchorState currentAnchorState = AnchorState.Uninitialized;

            /// <summary>最近一次 anchor policy 动作。</summary>
            [Tooltip("最近一次 anchor policy 动作：Accept/Reject/Coast/Hold/Reset。关闭 reliability policy 时显示 baseline_accept/no_pose 等诊断文本。")]
            public string latestPolicyAction = "";

            /// <summary>最近一次 anchor policy 原因。</summary>
            [Tooltip("最近一次 anchor policy 原因，例如 score_accept、translation_jump 或 no_pose。")]
            public string latestPolicyReason = "";

            /// <summary>最近一次 reliability score。</summary>
            [Tooltip("最近一次 PoseResult.reliability_score。旧协议或缺省字段会按 1.0 处理。")]
            public float latestReliabilityScore = 1.0f;

            /// <summary>最近一次 Python AnchorStatusEvent 状态。</summary>
            [Tooltip("最近一次 Python AnchorStatusEvent.state。该字段只用于诊断，不等同于 Unity anchor state。")]
            public string latestServerState = "";

            /// <summary>最近一次 Python AnchorStatusEvent 事件名。</summary>
            [Tooltip("最近一次 Python AnchorStatusEvent.event。用于观察 reset/reacquire/lost 等跨端状态闭环。")]
            public string latestServerEvent = "";

            /// <summary>最近一次 ServerHeartbeat 中的 input_ready。</summary>
            [Tooltip("最近一次 ServerHeartbeat.input_ready。false 表示 Python 尚未具备 stereo+camera_info 输入。")]
            public bool latestHeartbeatInputReady;

            /// <summary>最近一次 ServerHeartbeat 的 Unity 接收时间。</summary>
            [Tooltip("最近一次 ServerHeartbeat 被 Unity 主线程处理的时间，单位秒。")]
            public double latestHeartbeatReceiveTime = -1.0;

            /// <summary>最近一次实际使用的对齐参考相机。</summary>
            [Tooltip("最近一次实际使用的对齐参考相机。用于确认当前是 Left/Right/Center/None 哪一种对齐。")]
            public CameraReference latestUsedReference = CameraReference.Left;
        }
    }
}
