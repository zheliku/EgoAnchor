using System;
using System.Collections.Generic;
using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;

namespace EgoAnchor.Tools3.Eval
{
    /// <summary>一帧观测被污染的类型 (供鲁棒性指标按"真实坏帧位置"评判)。</summary>
    public enum CorruptionKind
    {
        None,
        JumpSpike,    // 单帧大跳变 (错误 pose) + 低分
        NoiseBurst,   // 一段噪声抬升 + 中分
        LowScore,     // 一段低分 (跟踪退化, pose 可能漂移)
    }

    /// <summary>注入后的观测 + 它的真实污染标签 (干净的真值仍保留, 供指标对比)。</summary>
    public readonly struct InjectedObservation
    {
        public readonly Observation Observation;   // 喂给算法的 (可能被污染的) 观测
        public readonly Pose CleanPose;            // 注入前的干净 pose (= 真值, 算误差用)
        public readonly CorruptionKind Kind;       // 这帧是不是坏帧、哪种坏

        public InjectedObservation(Observation observation, Pose cleanPose, CorruptionKind kind)
        {
            Observation = observation;
            CleanPose = cleanPose;
            Kind = kind;
        }
    }

    /// <summary>
    /// 坏 pose 注入器。在干净观测流上人为制造跟踪退化, 用来测 EgoAnchor 的 score 机制
    /// (gating / 自适应噪声) 在恶劣条件下的鲁棒性。
    ///
    /// **完全确定性**: 不用随机数发生器, 所有"随机"都由帧 index 经哈希得到, 同输入永远同结果,
    /// 可复现 (符合论文实验要求)。
    ///
    /// 三种失败模式 (模拟真实: 分割跳到错物体 / 深度噪声 / 遮挡致跟踪退化):
    ///   - JumpSpike:  每隔 period 帧, 注入一次大平移+旋转跳变, score 压到很低;
    ///   - NoiseBurst: 若干段内给 pose 叠加高斯式噪声 (由哈希生成), score 中等;
    ///   - LowScore:   若干段内 score 压低但 pose 基本不动 (模拟"跟踪退化但没跳")。
    ///
    /// 关键: 注入会同时降低该帧的 reliability_score, 这样 EgoAnchor 的 score-gating / 自适应
    /// 才有信号可用; 而 baseline (不看 score) 会照单全收 -> 在 jump rejection / recovery 上崩。
    /// </summary>
    public sealed class BadPoseInjector
    {
        private readonly int jumpPeriod;          // 每隔多少帧一次跳变
        private readonly double jumpMeters;       // 跳变平移幅度
        private readonly double jumpDegrees;      // 跳变旋转幅度
        private readonly double jumpScore;        // 跳变帧的 score
        private readonly double noiseMeters;      // 噪声段位置噪声标准差
        private readonly double noiseScore;       // 噪声段 score
        private readonly double lowScoreValue;    // 低分段 score

        public BadPoseInjector(
            int jumpPeriod = 23,
            double jumpMeters = 0.15,
            double jumpDegrees = 35.0,
            double jumpScore = 0.15,
            double noiseMeters = 0.02,
            double noiseScore = 0.5,
            double lowScoreValue = 0.2)
        {
            this.jumpPeriod = jumpPeriod;
            this.jumpMeters = jumpMeters;
            this.jumpDegrees = jumpDegrees;
            this.jumpScore = jumpScore;
            this.noiseMeters = noiseMeters;
            this.noiseScore = noiseScore;
            this.lowScoreValue = lowScoreValue;
        }

        /// <summary>
        /// 在 [noiseStartFrac, noiseEndFrac] 区间注入噪声段, [lowStartFrac, lowEndFrac] 注入低分段,
        /// 全程每 jumpPeriod 帧注入一次跳变。比例用 session 时长归一, 便于不同数据集一致。
        /// </summary>
        public List<InjectedObservation> Inject(
            IReadOnlyList<Observation> clean,
            double noiseStartFrac = 0.25,
            double noiseEndFrac = 0.35,
            double lowStartFrac = 0.60,
            double lowEndFrac = 0.70)
        {
            var result = new List<InjectedObservation>(clean.Count);
            if (clean.Count == 0)
            {
                return result;
            }

            double t0 = clean[0].TimeSeconds;
            double t1 = clean[^1].TimeSeconds;
            double dur = Math.Max(t1 - t0, 1e-6);

            for (int i = 0; i < clean.Count; i++)
            {
                Observation o = clean[i];
                double frac = (o.TimeSeconds - t0) / dur;
                Pose cleanPose = o.Pose;
                Pose pose = cleanPose;
                double score = o.Score;
                CorruptionKind kind = CorruptionKind.None;

                // 1) 周期性跳变 (最严重的坏帧)
                if (i > 0 && i % jumpPeriod == 0)
                {
                    Vec3 dir = UnitHash(i * 7 + 1);
                    Vec3 axis = UnitHash(i * 7 + 4);
                    pose = new Pose(
                        cleanPose.Position + dir * jumpMeters,
                        (cleanPose.Rotation * Quat.Exp(axis * (jumpDegrees * Math.PI / 180.0 * 0.5))).Normalized());
                    score = jumpScore;
                    kind = CorruptionKind.JumpSpike;
                }
                // 2) 噪声段
                else if (frac >= noiseStartFrac && frac <= noiseEndFrac)
                {
                    Vec3 n = GaussHash(i) * noiseMeters;
                    pose = new Pose(cleanPose.Position + n, cleanPose.Rotation);
                    score = noiseScore;
                    kind = CorruptionKind.NoiseBurst;
                }
                // 3) 低分段 (pose 不变, 只压分 — 模拟"跟踪退化但没明显跳")
                else if (frac >= lowStartFrac && frac <= lowEndFrac)
                {
                    score = lowScoreValue;
                    kind = CorruptionKind.LowScore;
                }

                var injected = new Observation(o.SourceFrameId, o.TimeSeconds, pose, (float)score);
                result.Add(new InjectedObservation(injected, cleanPose, kind));
            }

            return result;
        }

        /// <summary>由整数种子生成确定性单位向量 (代替随机数, 保证可复现)。</summary>
        private static Vec3 UnitHash(int seed)
        {
            double a = Frac(Math.Sin(seed * 12.9898) * 43758.5453) * 2 - 1;
            double b = Frac(Math.Sin(seed * 78.233) * 12345.6789) * 2 - 1;
            double c = Frac(Math.Sin(seed * 37.719) * 98765.4321) * 2 - 1;
            var v = new Vec3(a, b, c);
            double m = v.Magnitude;
            return m < 1e-9 ? new Vec3(1, 0, 0) : v / m;
        }

        /// <summary>由整数种子生成确定性"类高斯"向量 (Box-Muller 近似, 用哈希均匀数)。</summary>
        private static Vec3 GaussHash(int seed)
        {
            return new Vec3(Gauss(seed * 3 + 1), Gauss(seed * 3 + 2), Gauss(seed * 3 + 3));
        }

        private static double Gauss(int seed)
        {
            double u1 = Math.Max(Frac(Math.Sin(seed * 12.9898) * 43758.5453), 1e-9);
            double u2 = Frac(Math.Sin(seed * 78.233) * 12345.6789);
            return Math.Sqrt(-2.0 * Math.Log(u1)) * Math.Cos(2.0 * Math.PI * u2);
        }

        private static double Frac(double x) => x - Math.Floor(x);
    }
}
