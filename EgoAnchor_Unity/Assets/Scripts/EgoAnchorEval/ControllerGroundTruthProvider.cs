using UnityEngine;

namespace EgoAnchorEval
{
    /// <summary>
    /// 一次手柄 GT 采样结果；区分 live tracked pose 与为了静止段连续性保留的 last-known pose。
    /// </summary>
    public readonly struct ControllerGroundTruthSample
    {
        /// <summary>是否有可写入日志的 pose。</summary>
        public readonly bool HasPose;

        /// <summary>当前输出的 Unity world pose。</summary>
        public readonly Pose Pose;

        /// <summary>Meta SDK 本帧是否明确报告位置和朝向都 tracked。</summary>
        public readonly bool Tracked;

        /// <summary>pose 来源，例如 live_tracked、hold_last 或 ovr_untracked。</summary>
        public readonly string PoseSource;

        /// <summary>当 PoseSource=hold_last 时，距离最后一次 live tracked pose 的时间，单位毫秒。</summary>
        public readonly double HoldAgeMs;

        /// <summary>
        /// 构造 GT 采样结果。
        /// </summary>
        public ControllerGroundTruthSample(bool hasPose, Pose pose, bool tracked, string poseSource, double holdAgeMs)
        {
            HasPose = hasPose;
            Pose = pose;
            Tracked = tracked;
            PoseSource = poseSource ?? ControllerGroundTruthProvider.SourceNone;
            HoldAgeMs = holdAgeMs;
        }
    }

    /// <summary>
    /// 左/右手柄到 Unity 世界系 GT pose 的提供者；GT 只进入评估日志，不进入锚定管线。
    /// </summary>
    public sealed class ControllerGroundTruthProvider : MonoBehaviour
    {
        /// <summary>没有可用 GT pose。</summary>
        public const string SourceNone = "none";

        /// <summary>Meta SDK 本帧 live tracked pose。</summary>
        public const string SourceLiveTracked = "live_tracked";

        /// <summary>Meta SDK 静止停追踪后，沿用最后一次 live tracked pose。</summary>
        public const string SourceHoldLast = "hold_last";

        /// <summary>Meta SDK 返回了 controller pose，但本帧 tracked=false。</summary>
        public const string SourceOvrUntracked = "ovr_untracked";

        /// <summary>场景中的 OVRCameraRig，用于把 OVRInput 局部位姿变换到 Unity 世界系。</summary>
        [Tooltip("场景中的 OVRCameraRig，用于把手柄局部位姿变到 Unity 世界系。")]
        [SerializeField] private OVRCameraRig cameraRig;

        /// <summary>本 session 追踪的手柄，必须与 Python 对象配置和 manifest 一致。</summary>
        [Tooltip("本 session 追踪的手柄：必须与 Python --object controller_left/right 及 manifest gt_source 三者一致。")]
        [SerializeField] private OVRInput.Controller controller = OVRInput.Controller.RTouch;

        /// <summary>Meta SDK 报告 tracked=false 时是否输出最后一次 live tracked pose。</summary>
        [Header("Continuity")]
        [Tooltip("Meta SDK 静止省电导致 tracked=false 时，是否继续输出最后一次 live tracked pose。日志仍会写 gt_tracked=false 和 gt_pose_source=hold_last，不伪装为实时追踪。")]
        [SerializeField] private bool holdLastPoseWhenUntracked = true;

        /// <summary>last-known pose 最大保持时间；0 表示不设上限。</summary>
        [Tooltip("last-known pose 最大保持时间，单位秒。0 表示不设上限；若手柄确实移动但 SDK 未恢复 tracked，建议保持较小值。")]
        [Min(0.0f)]
        [SerializeField] private float maxHoldAgeSeconds = 0.0f;

        /// <summary>最近一次 live tracked pose。</summary>
        private Pose lastLivePose;

        /// <summary>最近一次 live tracked pose 的 Unity 单调时间，单位毫秒。</summary>
        private double lastLiveMonoMs = -1.0;

        /// <summary>是否已经缓存过 live tracked pose。</summary>
        private bool hasLastLivePose;

        /// <summary>最近一次对外输出的 GT sample。</summary>
        private ControllerGroundTruthSample latestSample;

        /// <summary>当前配置的 OVRInput 手柄。</summary>
        public OVRInput.Controller Controller => controller;

        /// <summary>是否启用静止停追踪时的 last-known pose 连续输出。</summary>
        public bool HoldLastPoseWhenUntracked => holdLastPoseWhenUntracked;

        /// <summary>last-known pose 最大保持时间，单位毫秒；0 表示不设上限。</summary>
        public double MaxHoldAgeMs => Mathf.Max(0.0f, maxHoldAgeSeconds) * 1000.0;

        /// <summary>最近一次对外输出的 GT sample。</summary>
        public ControllerGroundTruthSample LatestSample => latestSample;

        /// <summary>写入 manifest 的 GT 来源标识。</summary>
        public string ManifestGtSource
        {
            get
            {
                if (controller == OVRInput.Controller.LTouch)
                {
                    return "ovr_ltouch";
                }

                if (controller == OVRInput.Controller.RTouch)
                {
                    return "ovr_rtouch";
                }

                return "ovr_" + controller.ToString().ToLowerInvariant();
            }
        }

        /// <summary>写入 manifest 的 GT continuity 策略描述。</summary>
        public string HoldPolicyName => holdLastPoseWhenUntracked
            ? "hold_last_pose_when_untracked"
            : "live_tracked_only";

        /// <summary>
        /// 尝试读取手柄 Unity 世界系 pose 和追踪状态。
        /// </summary>
        /// <param name="worldPose">成功时输出手柄世界系 pose。</param>
        /// <param name="tracked">位置和朝向是否都被 OVRInput 标记为 tracked。</param>
        /// <returns>是否具备可用的 camera rig/trackingSpace 来计算世界系 pose。</returns>
        public bool TryGetWorldPose(out Pose worldPose, out bool tracked)
        {
            bool hasPose = TryGetWorldPoseSample(out ControllerGroundTruthSample sample);
            worldPose = sample.Pose;
            tracked = sample.Tracked;
            return hasPose;
        }

        /// <summary>
        /// 尝试读取完整 GT 采样，显式区分 live tracked、hold_last 和 untracked OVR pose。
        /// </summary>
        /// <param name="sample">输出 GT 采样结果。</param>
        /// <returns>是否有可写入日志的 pose。</returns>
        public bool TryGetWorldPoseSample(out ControllerGroundTruthSample sample)
        {
            sample = new ControllerGroundTruthSample(false, Pose.identity, false, SourceNone, 0.0);
            if (cameraRig == null || cameraRig.trackingSpace == null)
            {
                latestSample = sample;
                return false;
            }

            Vector3 localPos = OVRInput.GetLocalControllerPosition(controller);
            Quaternion localRot = OVRInput.GetLocalControllerRotation(controller);
            Transform space = cameraRig.trackingSpace;
            Pose sdkWorldPose = new Pose(space.TransformPoint(localPos), space.rotation * localRot);
            bool liveTracked = OVRInput.GetControllerPositionTracked(controller)
                && OVRInput.GetControllerOrientationTracked(controller);
            double nowMs = Time.realtimeSinceStartupAsDouble * 1000.0;

            if (liveTracked)
            {
                lastLivePose = sdkWorldPose;
                lastLiveMonoMs = nowMs;
                hasLastLivePose = true;
                sample = new ControllerGroundTruthSample(true, sdkWorldPose, true, SourceLiveTracked, 0.0);
                latestSample = sample;
                return true;
            }

            if (holdLastPoseWhenUntracked && hasLastLivePose)
            {
                double holdAgeMs = Mathf.Max(0.0f, (float)(nowMs - lastLiveMonoMs));
                if (MaxHoldAgeMs <= 0.0 || holdAgeMs <= MaxHoldAgeMs)
                {
                    sample = new ControllerGroundTruthSample(true, lastLivePose, false, SourceHoldLast, holdAgeMs);
                    latestSample = sample;
                    return true;
                }
            }

            sample = new ControllerGroundTruthSample(true, sdkWorldPose, false, SourceOvrUntracked, 0.0);
            latestSample = sample;
            return true;
        }
    }
}
