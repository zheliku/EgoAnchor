using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// EgoAnchor 静态锚定方法的 Inspector 宿主组件 (从 AnchorPolicyHost 剥离)。
    ///
    /// 它把 EgoAnchor "方法层"的全部可调参数 + <see cref="StaticLockController"/> 实例收拢到一个独立
    /// MonoBehaviour, 让 AnchorPolicyHost 回归"motion model × smoothing strategy + 生命周期"的本职,
    /// 不再被二十多个 staticLock* 参数淹没。host 持有一个可选引用并委托:
    ///   - 收到观测: <see cref="OnObservation"/>;
    ///   - 每渲染帧: <see cref="Stabilize"/> (未启用时原样返回 candidate);
    ///   - 重置: <see cref="ResetModule"/>。
    ///
    /// 挂载方式: 和 AnchorPolicyHost 挂同一个 GameObject, 把本组件拖进 host 的 staticLockModule 槽。
    /// 不挂或不启用 = 纯 baseline (motion × smoothing), 挂上并 enabled = EgoAnchor 方法。
    /// 这样"翻一个组件的开关 = baseline ↔ EgoAnchor"的消融关系仍然成立。
    /// </summary>
    public sealed class EgoAnchorStaticLockModule : MonoBehaviour
    {
        /// <summary>是否启用静止锚定 (EgoAnchor 核心方法层)。</summary>
        [Header("Static Lock (EgoAnchor 核心方法)")]
        [Tooltip("是否启用静止锚定稳定器：物体静止且高分时冻结输出 pose，把小抖动当噪声吸收 → 看上去一动不动；运动时交回 smoothing。关闭=纯 baseline。")]
        [SerializeField] private bool enableStaticLock = true;

        /// <summary>进入静止判定的线速度阈值，单位 m/s。</summary>
        [Tooltip("进入静止判定的观测线速度阈值 (m/s)。必须设在观测噪声地板之上 (5090@12fps 平移噪声地板 ~14mm/s)。默认 0.05。")]
        [SerializeField] private float staticLockEnterSpeedMps = 0.05f;

        /// <summary>进入静止判定的角速度阈值，单位 deg/s。</summary>
        [Tooltip("进入静止判定的观测角速度阈值 (deg/s)。设太低 (低于旋转噪声地板) 会导致永不锁定 (5090@12fps 旋转噪声地板 ~15°/s)。默认 35。")]
        [SerializeField] private float staticLockEnterAngSpeedDps = 35.0f;

        /// <summary>进入锁定需连续保持静止的时间，单位秒 (帧率无关)。</summary>
        [Tooltip("进入锁定需连续保持静止 (+高分) 的时间 (秒)。防静止判定抖动。帧率无关。默认 0.35。")]
        [SerializeField] private float staticLockDwellSeconds = 0.35f;

        /// <summary>进入锁定所需的最低可靠性分数。</summary>
        [Tooltip("进入/维持锁定所需的最低可靠性分数 (0..1)。设太高 (高于物体常见分) 会永不锁定。默认 0.25。")]
        [Range(0f, 1f)]
        [SerializeField] private float staticLockMinScore = 0.25f;

        /// <summary>锁定时位置死区，单位米。</summary>
        [Tooltip("锁定时位置死区 (米)：观测相对锁点位移小于此值视为噪声、忽略。杀静止抖动的核心。默认 0.008。")]
        [SerializeField] private float staticLockDeadbandMeters = 0.008f;

        /// <summary>锁定时旋转死区，单位度。</summary>
        [Tooltip("锁定时旋转死区 (度)：旋转小于此值视为噪声、忽略。默认 3。")]
        [SerializeField] private float staticLockDeadbandDegrees = 3.0f;

        /// <summary>解锁位置证据阈值 (score 加权 CUSUM)，单位米。</summary>
        [Tooltip("解锁位置证据阈值 (score 加权累计的超死区位移, 米)。越大越粘 (难解锁), 越小越灵敏。默认 0.08。")]
        [SerializeField] private float staticLockUnlockEvidenceMeters = 0.08f;

        /// <summary>解锁旋转证据阈值 (score 加权 CUSUM)，单位度。</summary>
        [Tooltip("解锁旋转证据阈值 (score 加权累计的超死区旋转, 度)。越大越粘。默认 20。")]
        [SerializeField] private float staticLockUnlockEvidenceDegrees = 20.0f;

        /// <summary>绝对漂移租绳：相对锁定原点平移超此值则解锁，单位米。</summary>
        [Tooltip("绝对漂移租绳 (米)：相对锁定原点 (creep 不动) 的总平移超此值 → 解锁。修复慢速持续平移被 creep 跟住而永不解锁。默认 0.015。")]
        [SerializeField] private float staticLockUnlockDriftMeters = 0.015f;

        /// <summary>绝对漂移租绳：相对锁定原点旋转超此值则解锁，单位度。</summary>
        [Tooltip("绝对漂移租绳 (度)：相对锁定原点的总旋转超此值 → 解锁。默认 5。")]
        [SerializeField] private float staticLockUnlockDriftDegrees = 5.0f;

        /// <summary>解锁证据半衰期，单位秒 (帧率无关)。</summary>
        [Tooltip("解锁证据半衰期 (秒, 帧率无关漏积分)：偶发噪声会漏掉, 只有持续运动才累积越阈。越大越粘。默认 0.27。")]
        [SerializeField] private float staticLockEvidenceHalfLifeSeconds = 0.27f;

        /// <summary>漏锁 creep 半衰期，单位秒 (帧率无关)。</summary>
        [Tooltip("漏锁 creep 半衰期 (秒, 帧率无关)：锁定时朝高分小位移观测缓慢靠拢, 精修锁点 + 跟极慢漂移。越小靠拢越快。默认 2.7。")]
        [SerializeField] private float staticLockCreepHalfLifeSeconds = 2.7f;

        /// <summary>解锁后禁止再锁的时间，单位秒 (反 chatter, 帧率无关)。</summary>
        [Tooltip("解锁后禁止再锁的时间 (秒, 反 chatter)：给真实运动一个逃逸窗口, 防锁定频繁翻转。帧率无关。默认 1.0。")]
        [SerializeField] private float staticLockRelockSuppressSeconds = 1.0f;

        /// <summary>速度逃逸倍数。</summary>
        [Tooltip("速度逃逸倍数：锁定时观测速度 > 静止阈值 × 此倍数 连续一段时间 → 立即解锁 (堵 CUSUM 跟不上的慢运动 false-lock 长尾)。越大越粘。默认 2.5。")]
        [SerializeField] private float staticLockUnlockSpeedFactor = 2.5f;

        /// <summary>速度逃逸需连续运动的时间，单位秒 (帧率无关)。</summary>
        [Tooltip("速度逃逸需连续检测到明确运动的时间 (秒)。防单帧噪声误解锁。帧率无关。默认 0.4。")]
        [SerializeField] private float staticLockUnlockMovingSeconds = 0.4f;

        /// <summary>解锁接缝残差衰减 (60fps 基准, 已帧率无关)。</summary>
        [Tooltip("解锁接缝残差每帧衰减比例 (60fps 基准, 已按 dt 归一)：解锁瞬间从锁点平滑收敛到 smoothing 输出, 防 pop。越大释放越柔、越不卡。默认 0.85。")]
        [Range(0.5f, 0.99f)]
        [SerializeField] private float staticLockSeamDecayPerFrame = 0.85f;

        /// <summary>CUSUM 累积时间归一基准，单位秒。</summary>
        [Tooltip("CUSUM 证据累积的时间归一基准 (秒)：通常设为标定时的观测周期 (5fps=0.2)。改它等比缩放所有解锁灵敏度。默认 0.2。")]
        [SerializeField] private float staticLockRefObsIntervalSeconds = 0.2f;

        /// <summary>头角速度达此值 (deg/s) 时头动容忍度吃满。</summary>
        [Header("Head-Motion Awareness (问题3)")]
        [Tooltip("头角速度 (deg/s) 达此值 → 头动容忍因子放大到上限。越小越早进入宽松。默认 60。")]
        [SerializeField] private float staticLockHeadRotForFullToleranceDps = 60.0f;

        /// <summary>头线速度达此值 (m/s) 时头动容忍度吃满。</summary>
        [Tooltip("头线速度 (m/s) 达此值 → 头动容忍因子放大到上限。默认 0.3。")]
        [SerializeField] private float staticLockHeadLinForFullToleranceMps = 0.3f;

        /// <summary>头动容忍最大放大倍数 (1=关闭头动感知)。</summary>
        [Tooltip("头动时 static 容忍度 (死区/漂移租绳/速度逃逸阈值) 最大放大倍数。1=关闭头动感知；越大头动时越粘 (越不容易因头动解锁), 但头动中物体真动的响应也越慢。默认 4。")]
        [Range(1.0f, 8.0f)]
        [SerializeField] private float staticLockHeadMaxToleranceFactor = 4.0f;

        /// <summary>低分释放阈值：锁定时分数持续低于此值则强制解锁。</summary>
        [Header("Low-Score Release (问题1)")]
        [Tooltip("低分释放：锁定时 score 持续低于此值 → 锁点不可信, 强制解锁, 不让 anchor 冻在错 pose。配合 PoseToAnchorRuntime 的低分自动 reacquire。默认 0.3。")]
        [Range(0f, 1f)]
        [SerializeField] private float staticLockLowScoreReleaseScore = 0.3f;

        /// <summary>低分释放持续时间，单位秒。</summary>
        [Tooltip("低分释放需持续的时间 (秒)。锁定时分数连续低于阈值超过此时长才强制解锁, 防单帧低分误释放。0=关闭低分释放。默认 0.6。")]
        [SerializeField] private float staticLockLowScoreReleaseSeconds = 0.6f;

        private readonly StaticLockController staticLock = new StaticLockController();

        /// <summary>是否启用静止锚定。</summary>
        public bool Enabled => enableStaticLock;

        /// <summary>当前是否锁定 (供 eval 的 latest_static_locked)。</summary>
        public bool IsLocked => enableStaticLock && staticLock.IsLocked;

        /// <summary>收到一帧被接受的观测时调用 (host 在 motion model 更新后)。未启用则忽略。</summary>
        public void OnObservation(in Pose worldPose, float score, double measurementTimeSeconds, bool hasHeadPose, in Pose headPose)
        {
            if (!enableStaticLock)
            {
                return;
            }

            ConfigureStaticLock();
            staticLock.OnObservation(worldPose, score, measurementTimeSeconds, hasHeadPose, headPose);
        }

        /// <summary>每渲染帧调用。未启用则原样返回 candidate；启用则返回锁定/接缝/自由 pose。</summary>
        public Pose Stabilize(in Pose candidatePose, float dtSeconds)
        {
            if (!enableStaticLock)
            {
                return candidatePose;
            }

            ConfigureStaticLock();
            return staticLock.Stabilize(candidatePose, dtSeconds);
        }

        /// <summary>清空控制器状态。</summary>
        public void ResetModule()
        {
            staticLock.Reset();
        }

        private void ConfigureStaticLock()
        {
            staticLock.Configure(
                staticLockEnterSpeedMps,
                staticLockEnterAngSpeedDps,
                staticLockDwellSeconds,
                staticLockMinScore,
                staticLockDeadbandMeters,
                staticLockDeadbandDegrees,
                staticLockUnlockEvidenceMeters,
                staticLockUnlockEvidenceDegrees,
                staticLockUnlockDriftMeters,
                staticLockUnlockDriftDegrees,
                staticLockEvidenceHalfLifeSeconds,
                staticLockCreepHalfLifeSeconds,
                staticLockRelockSuppressSeconds,
                staticLockUnlockSpeedFactor,
                staticLockUnlockMovingSeconds,
                staticLockSeamDecayPerFrame,
                staticLockRefObsIntervalSeconds,
                staticLockHeadRotForFullToleranceDps,
                staticLockHeadLinForFullToleranceMps,
                staticLockHeadMaxToleranceFactor,
                staticLockLowScoreReleaseScore,
                staticLockLowScoreReleaseSeconds);
        }
    }
}
