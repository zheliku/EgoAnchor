using System;
using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 自适应 anchor 控制器的全部可调参数。
    ///
    /// 该类被 AnchorPolicyHost 序列化进 Inspector，也可由 smoke 测试直接 new 出来；
    /// 参数本身不携带任何运行状态，PolicyController.ApplyConfig 可在运行中热更而不清空滤波历史。
    /// </summary>
    [Serializable]
    public sealed class AnchorPolicyConfig
    {
        /// <summary>进入接受状态所需的最低可靠性总分。</summary>
        [Header("评分门控")]
        [Tooltip("进入接受状态所需的最低可靠性总分。冷启动或被拒后，分数达到该值才重新开始更新滤波器。")]
        [Range(0f, 1f)] public float acceptScoreEnter = 0.35f;

        /// <summary>已处于接受状态时继续接受的滞回下限。</summary>
        [Tooltip("已处于接受状态时继续接受的滞回下限。低于进入阈值但高于该值的帧仍被接受，防止分数在阈值附近抖动导致频繁拒绝。")]
        [Range(0f, 1f)] public float acceptScoreStay = 0.25f;

        /// <summary>低于该分视为强拒绝的下限。</summary>
        [Tooltip("低于该分视为强拒绝并停止刷新可靠时间；持续低于会随时间走向 Lost。介于该值与滞回下限之间时冻结保持。")]
        [Range(0f, 1f)] public float holdScoreMin = 0.12f;

        /// <summary>REGISTER/RE_REGISTER 重定位 pose 的接受下限。</summary>
        [Tooltip("REGISTER/RE_REGISTER 重定位 pose 的接受下限。重定位帧天然带低置信分，达到该值即硬贴合（滤波器重置到新位姿）。")]
        [Range(0f, 1f)] public float relocalizeMinScore = 0.12f;

        /// <summary>位置 innovation 马氏距离平方阈值。</summary>
        [Header("跳变门控")]
        [Tooltip("位置 innovation 马氏距离平方阈值（3 自由度，16 约对应 99.9%）。相对预测位姿与协方差判定，长时间无测量后协方差增大、门自动变宽。")]
        [Min(1f)] public float innovationPosChi2Gate = 16f;

        /// <summary>旋转 innovation 马氏距离平方阈值。</summary>
        [Tooltip("旋转 innovation 马氏距离平方阈值。判定逻辑与位置相同，但作用在旋转误差向量上。")]
        [Min(1f)] public float innovationRotChi2Gate = 11f;

        /// <summary>平移跳变绝对兜底，单位米。</summary>
        [Tooltip("平移跳变绝对兜底，单位米。无论协方差多大，单帧平移超过该值一律拒绝。")]
        [Min(0.001f)] public float maxTranslationJumpMeters = 0.8f;

        /// <summary>旋转跳变绝对兜底，单位度。</summary>
        [Tooltip("旋转跳变绝对兜底，单位度。无论协方差多大，单帧旋转超过该值一律拒绝。")]
        [Min(1f)] public float maxRotationJumpDegrees = 90f;

        /// <summary>可信运动接受的平移上限，单位米。</summary>
        [Tooltip("可信运动接受的平移上限，单位米。高分测量若只因马氏距离超阈、但绝对平移不超过该值，会被视为真实运动而不是外点。")]
        [Min(0.001f)] public float trustedMotionTranslationMeters = 0.18f;

        /// <summary>可信运动接受的旋转上限，单位度。</summary>
        [Tooltip("可信运动接受的旋转上限，单位度。高分测量若只因旋转马氏距离超阈、但绝对旋转不超过该值，会被视为真实旋转而不是外点。")]
        [Min(0.1f)] public float trustedMotionRotationDegrees = 45f;

        /// <summary>持续中等跳变软恢复所需的连续一致帧数。</summary>
        [Tooltip("连续高分且彼此一致的中等平移或大旋转测量达到该次数后，判定为真实物体运动并软恢复进入滤波；不会像瞬移恢复那样硬贴合。")]
        [Min(1)] public int softRecoveryCount = 2;

        /// <summary>软恢复的位置互一致阈值，单位米。</summary>
        [Tooltip("软恢复中，相邻被拒测量之间允许的最大位置差，单位米。用于确认新 pose 持续一致，而不是单帧随机外点。")]
        [Min(0.001f)] public float softRecoveryConsistencyMeters = 0.15f;

        /// <summary>软恢复的旋转互一致阈值，单位度。</summary>
        [Tooltip("软恢复中，相邻被拒测量之间允许的最大旋转差，单位度。该值应覆盖低频 pose 下真实手动旋转的帧间变化。")]
        [Min(0.1f)] public float softRecoveryConsistencyDegrees = 45f;

        /// <summary>软恢复时的旋转测量噪声放大倍数。</summary>
        [Tooltip("软恢复时额外放大旋转测量噪声，避免从旧姿态突然 Snap 到新姿态。数值越大恢复越平滑但越慢。")]
        [Min(1f)] public float softRecoveryRotationNoiseScale = 2f;

        /// <summary>判定物体真实瞬移所需的连续一致拒绝次数。</summary>
        [Tooltip("连续被跳变门拒绝、分数达到进入阈值且位置互相一致的帧达到该次数时，判定物体真实瞬移并强制贴合接受。")]
        [Min(2)] public int stuckRecoveryCount = 5;

        /// <summary>瞬移恢复的位置互一致半径，单位米。</summary>
        [Tooltip("瞬移恢复判定中，相邻被拒 pose 之间允许的最大位置差，单位米。用于区分真实瞬移与随机外点串。")]
        [Min(0.001f)] public float stuckConsistencyMeters = 0.10f;

        /// <summary>瞬移恢复的旋转互一致半径，单位度。</summary>
        [Tooltip("瞬移恢复判定中，相邻被拒 pose 之间允许的最大旋转差，单位度。")]
        [Min(0.1f)] public float stuckConsistencyDegrees = 15f;

        /// <summary>位置测量噪声基准，单位 m^2。</summary>
        [Header("位置滤波")]
        [Tooltip("位置测量噪声基准，单位 m^2（默认 4e-6 对应标准差约 2mm 的感知噪声）。会按可靠性分与静止状态自动放大；越大输出越稳但延迟越高。")]
        [Min(1e-9f)] public float positionMeasurementNoise = 4e-6f;

        /// <summary>静止状态下测量噪声的放大倍数。</summary>
        [Tooltip("静止状态下位置/旋转测量噪声的放大倍数。静止时强烈相信当前位姿以压制抖动，运动时恢复基准实现低延迟。")]
        [Min(1f)] public float staticMeasurementNoiseScale = 100f;

        /// <summary>可靠性分参与噪声放大的下限。</summary>
        [Tooltip("可靠性分参与噪声放大的下限：R_eff = R / clamp(score, 该值, 1)^2。分数越低测量权重越小，但不会无限放大。")]
        [Range(0.05f, 1f)] public float scoreNoiseFloor = 0.2f;

        /// <summary>运动状态下的位置过程噪声。</summary>
        [Tooltip("运动状态下常速度模型的位置过程噪声，单位 m^2/s。越大越允许快速变向，延迟更小但速度估计更噪。")]
        [Min(1e-9f)] public float processNoiseMoving = 0.02f;

        /// <summary>静止状态下的位置过程噪声。</summary>
        [Tooltip("静止状态下常速度模型的位置过程噪声，单位 m^2/s。需远小于运动值，静止平滑强度由它与放大后的测量噪声共同决定。")]
        [Min(1e-9f)] public float processNoiseStatic = 1e-5f;

        /// <summary>旋转测量噪声基准，单位 rad^2。</summary>
        [Header("旋转滤波")]
        [Tooltip("旋转测量噪声基准，单位 rad^2（默认 3e-4 对应标准差约 1 度）。按可靠性分与静止状态放大，规则与位置一致。")]
        [Min(1e-9f)] public float rotationMeasurementNoise = 3e-4f;

        /// <summary>旋转过程噪声，单位 rad^2/s。</summary>
        [Tooltip("运动状态下旋转误差协方差的增长速率，单位 rad^2/s。越大越快跟随测量旋转，越小越平稳。")]
        [Min(1e-9f)] public float rotationProcessNoise = 0.02f;

        /// <summary>静止状态下的旋转过程噪声，单位 rad^2/s。</summary>
        [Tooltip("静止状态下旋转误差协方差的增长速率，单位 rad^2/s。需远小于运动值，静止旋转抖动主要由它压制。")]
        [Min(1e-9f)] public float rotationProcessNoiseStatic = 0.001f;

        /// <summary>角速度修正增益相对四元数增益的比例。</summary>
        [Tooltip("角速度修正增益相对四元数增益的比例。过大会把测量噪声放大进角速度估计，反而加剧静止旋转抖动。")]
        [Range(0f, 2f)] public float angularVelocityGainBeta = 0.3f;

        /// <summary>角速度估计上限，单位度/秒。</summary>
        [Tooltip("角速度估计的模长上限，单位度/秒。防止单帧大旋转误差把角速度顶到不合理值。")]
        [Min(1f)] public float angularVelocityMaxDps = 200f;

        /// <summary>角速度持续阻尼时间常数，单位秒。</summary>
        [Tooltip("角速度估计的指数阻尼时间常数，单位秒。无新证据时角速度向 0 收敛，防止常角速度模型在噪声下漂移。")]
        [Min(0.01f)] public float angularVelocityDampingTau = 0.5f;

        /// <summary>单次旋转校正步长上限，单位度。</summary>
        [Tooltip("单次旋转测量最多校正的角度，单位度。用于防止大旋转恢复或偶发外点把模型一帧内硬贴到新朝向。")]
        [Min(1f)] public float maxRotationCorrectionDegrees = 45f;

        /// <summary>进入静止的测量散布半径，单位米。</summary>
        [Header("运动分类")]
        [Tooltip("进入静止状态的测量散布半径，单位米。持续指定时长内所有被接受测量的位置都落在该半径内才判定静止；应约为感知位置噪声标准差的 4 倍以上，否则噪声会反复打断静止判定。")]
        [Min(0.001f)] public float staticEnterRadius = 0.012f;

        /// <summary>进入静止的测量旋转散布，单位度。</summary>
        [Tooltip("进入静止状态的测量旋转散布，单位度。持续指定时长内所有被接受测量的旋转都在该范围内才判定静止。")]
        [Min(0.1f)] public float staticEnterRotationDeg = 2.5f;

        /// <summary>进入静止所需的持续时长，单位秒。</summary>
        [Tooltip("速度与角速度需持续低于进入阈值该时长才进入静止模式，避免运动间隙误判。")]
        [Min(0.05f)] public float staticEnterDuration = 0.5f;

        /// <summary>立即退出静止的 innovation 马氏距离平方阈值。</summary>
        [Tooltip("单帧位置 innovation 马氏距离平方超过该值时立即退出静止模式，保证物体突然被移动时快速恢复跟随。")]
        [Min(0.5f)] public float motionSpikeD2 = 6f;

        /// <summary>立即退出静止的测量位移阈值，单位米。</summary>
        [Tooltip("静止模式下单帧测量与预测的位置差超过该值时立即退出静止。该值需要接近静止测量抖动上界，避免强平滑把缓慢真实移动当噪声吸收。")]
        [Min(0.001f)] public float staticExitDisplacement = 0.01f;

        /// <summary>立即退出静止的测量旋转差阈值，单位度。</summary>
        [Tooltip("静止模式下单帧测量与预测的旋转差超过该值时立即退出静止。")]
        [Min(0.1f)] public float staticExitRotationDeg = 1.5f;

        /// <summary>超过该时长没有被接受的测量才进入 Coasting，单位秒。</summary>
        [Header("时序与续航")]
        [Tooltip("超过该时长没有被接受的测量才进入 Coasting，单位秒。应覆盖正常 pose 消息间隔（当前真机约 4-5Hz），避免普通消息间隙被误判为丢失。")]
        [Min(0.02f)] public float coastGraceSeconds = 0.30f;

        /// <summary>Coasting 外推上限，单位秒。</summary>
        [Tooltip("Coasting 阻尼外推的时间上限，单位秒。超过后清零速度冻结保持，进入 FrozenUncertain。")]
        [Min(0.05f)] public float maxCoastSeconds = 0.45f;

        /// <summary>进入 Lost 的无可靠测量时长，单位秒。</summary>
        [Tooltip("连续没有被接受的测量超过该时长后进入 Lost，单位秒。")]
        [Min(0.2f)] public float lostTimeoutSeconds = 2.0f;

        /// <summary>渲染时刻预测地平线上限，单位秒。</summary>
        [Tooltip("跟踪状态下向渲染时刻前推的最大时长，单位秒。用于隐藏感知延迟；设为 0 关闭前推（仍每帧推进 coast/lost 计时）。过大会把速度噪声放大进输出。")]
        [Min(0f)] public float maxPredictAheadSeconds = 0.15f;

        /// <summary>渲染时刻旋转预测地平线上限，单位秒。</summary>
        [Tooltip("跟踪状态下旋转向渲染时刻前推的最大时长，单位秒。旋转角速度比线速度更容易受低频测量和对称外点污染，因此默认短于位置预测。")]
        [Min(0f)] public float maxRotationPredictAheadSeconds = 0.05f;

        /// <summary>Coasting 期速度阻尼时间常数，单位秒。</summary>
        [Tooltip("Coasting 期线速度的指数阻尼时间常数，单位秒。位移上限约为 速度*该值，防止长间隙外推飞出。")]
        [Min(0.01f)] public float velocityDampingTauSeconds = 0.3f;

        /// <summary>测量允许的最大年龄，单位秒。</summary>
        [Tooltip("测量采集时间早于当前超过该值时直接丢弃，单位秒。用于时钟异常或缓存陈旧的保护。")]
        [Min(0.1f)] public float maxMeasurementAgeSeconds = 1.0f;

        /// <summary>静止输出锁定的位置释放阈值，单位米。</summary>
        [Header("渲染输出")]
        [Tooltip("进入静止后，渲染输出会锁定在当前 world pose；目标 pose 与锁定 pose 的位置差超过该阈值才释放并跟随。用于吸收 frame alignment 残余抖动和头动诱发的小漂移。")]
        [Min(0.001f)] public float staticOutputReleaseMeters = 0.02f;

        /// <summary>静止输出锁定的旋转释放阈值，单位度。</summary>
        [Tooltip("进入静止后，渲染输出会锁定在当前旋转；目标 pose 与锁定旋转差超过该阈值才释放并跟随。")]
        [Min(0.1f)] public float staticOutputReleaseDegrees = 3.0f;

        /// <summary>静止输出慢速归中的时间常数，单位秒。</summary>
        [Tooltip("静止锁定期间，渲染输出仍会以该时间常数慢速追踪滤波后的静止均值，避免锁在进入静止瞬间的随机偏差上。")]
        [Min(0.01f)] public float staticOutputSmoothingTauSeconds = 0.30f;

        /// <summary>静止锁定期间最大归中线速度，单位米/秒。</summary>
        [Tooltip("静止锁定期间渲染输出慢速归中的最大线速度，单位米/秒。该值应远小于运动输出速度，用于避免头动残余误差被快速显示出来。")]
        [Min(0.001f)] public float maxStaticOutputSpeedMps = 0.05f;

        /// <summary>静止锁定期间最大归中角速度，单位度/秒。</summary>
        [Tooltip("静止锁定期间渲染输出慢速归中的最大角速度，单位度/秒。该值应远小于运动输出角速度。")]
        [Min(0.1f)] public float maxStaticOutputAngularSpeedDps = 45f;

        /// <summary>运动输出追踪目标的时间常数，单位秒。</summary>
        [Tooltip("运动状态下渲染输出追踪滤波目标 pose 的时间常数，单位秒。用于把低频 pose 更新摊到高帧率渲染帧上；越小越跟手，越大越顺滑但延迟更高。")]
        [Min(0.001f)] public float movingOutputSmoothingTauSeconds = 0.04f;

        /// <summary>渲染输出最大线速度，单位米/秒。</summary>
        [Tooltip("渲染输出每秒允许移动的最大距离，单位米/秒。限制单帧目标跳变造成的显示速度尖峰。")]
        [Min(0.01f)] public float maxOutputSpeedMps = 3.0f;

        /// <summary>渲染输出最大角速度，单位度/秒。</summary>
        [Tooltip("渲染输出每秒允许旋转的最大角度，单位度/秒。限制单帧旋转目标跳变造成的显示速度尖峰。")]
        [Min(1f)] public float maxOutputAngularSpeedDps = 720f;

        /// <summary>
        /// 归一参数之间的约束关系，供 Inspector 修改后调用。
        /// </summary>
        public void Validate()
        {
            acceptScoreEnter = Mathf.Clamp01(acceptScoreEnter);
            acceptScoreStay = Mathf.Clamp(acceptScoreStay, 0f, acceptScoreEnter);
            holdScoreMin = Mathf.Clamp(holdScoreMin, 0f, acceptScoreStay);
            relocalizeMinScore = Mathf.Clamp01(relocalizeMinScore);
            trustedMotionTranslationMeters = Mathf.Clamp(trustedMotionTranslationMeters, staticExitDisplacement, maxTranslationJumpMeters);
            trustedMotionRotationDegrees = Mathf.Clamp(trustedMotionRotationDegrees, staticExitRotationDeg, maxRotationJumpDegrees);
            softRecoveryCount = Mathf.Max(1, softRecoveryCount);
            softRecoveryConsistencyMeters = Mathf.Max(softRecoveryConsistencyMeters, 0.001f);
            softRecoveryConsistencyDegrees = Mathf.Max(softRecoveryConsistencyDegrees, 0.1f);
            softRecoveryRotationNoiseScale = Mathf.Max(softRecoveryRotationNoiseScale, 1f);
            maxRotationCorrectionDegrees = Mathf.Max(maxRotationCorrectionDegrees, 1f);
            maxCoastSeconds = Mathf.Max(maxCoastSeconds, coastGraceSeconds);
            lostTimeoutSeconds = Mathf.Max(lostTimeoutSeconds, maxCoastSeconds);
            maxRotationPredictAheadSeconds = Mathf.Clamp(maxRotationPredictAheadSeconds, 0f, maxPredictAheadSeconds);
            staticOutputReleaseMeters = Mathf.Max(staticOutputReleaseMeters, staticExitDisplacement);
            staticOutputReleaseDegrees = Mathf.Max(staticOutputReleaseDegrees, staticExitRotationDeg);
            staticOutputSmoothingTauSeconds = Mathf.Max(staticOutputSmoothingTauSeconds, 0.01f);
            maxStaticOutputSpeedMps = Mathf.Max(maxStaticOutputSpeedMps, 0.001f);
            maxStaticOutputAngularSpeedDps = Mathf.Max(maxStaticOutputAngularSpeedDps, 0.1f);
            movingOutputSmoothingTauSeconds = Mathf.Max(movingOutputSmoothingTauSeconds, 0.001f);
            maxOutputSpeedMps = Mathf.Max(maxOutputSpeedMps, 0.01f);
            maxOutputAngularSpeedDps = Mathf.Max(maxOutputAngularSpeedDps, 1f);
        }
    }
}
