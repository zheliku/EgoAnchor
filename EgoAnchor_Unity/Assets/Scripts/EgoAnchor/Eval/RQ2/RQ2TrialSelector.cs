using System;
using EgoAnchor.Diagnostics;
using UnityEngine;

namespace EgoAnchor.Eval.RQ2
{
    /// <summary>
    /// RQ2 当前试次上下文选择器。
    /// <para>
    /// 该组件只保存场景、试次编号和目标速度，供 <see cref="EvalRecorder"/>
    /// 在渲染 tick 读取。它不控制 <see cref="EvalSession"/>、不拥有录制状态，也不写文件。
    /// </para>
    /// </summary>
    public sealed class RQ2TrialSelector : MonoBehaviour
    {
        /// <summary>当前 session 内已经分配的最大试次编号。</summary>
        private int _lastTrialId;

        /// <summary>当前试次编号；空闲时为 -1。</summary>
        private int _currentTrialId = -1;

        /// <summary>当前试次的运动场景。</summary>
        private RQ2Condition _currentCondition = RQ2Condition.None;

        /// <summary>当前试次目标线速度，单位 m/s；不适用时为 NaN。</summary>
        private float _targetLinearSpeedMs = float.NaN;

        /// <summary>当前试次目标角速度，单位 deg/s；不适用时为 NaN。</summary>
        private float _targetAngularSpeedDegS = float.NaN;

        /// <summary>当前试次开始时的 Unity 单调时钟毫秒。</summary>
        private double _trialStartMonoMs = double.NaN;

        /// <summary>当前运动场景；空闲时为 <see cref="RQ2Condition.None"/>。</summary>
        public RQ2Condition CurrentCondition => _currentCondition;

        /// <summary>当前 session 内的试次编号；空闲时为 -1。</summary>
        public int CurrentTrialId => _currentTrialId;

        /// <summary>目标线速度，单位 m/s；不适用或未指定时为 NaN。</summary>
        public float TargetLinearSpeedMs => _targetLinearSpeedMs;

        /// <summary>目标角速度，单位 deg/s；不适用或未指定时为 NaN。</summary>
        public float TargetAngularSpeedDegS => _targetAngularSpeedDegS;

        /// <summary>当前试次已经持续的秒数；空闲时为 0。</summary>
        public double CurrentTrialDurationSeconds => ElapsedSeconds(_trialStartMonoMs);

        /// <summary>
        /// 立即开始新的 RQ2 试次。同一 session 中每次成功开始都会分配新的单调递增编号。
        /// </summary>
        /// <param name="condition">本次试次的运动场景，不能为 None。</param>
        /// <param name="targetLinearSpeedMs">预设目标线速度，单位 m/s；未指定时传 NaN。</param>
        /// <param name="targetAngularSpeedDegS">预设目标角速度，单位 deg/s；未指定时传 NaN。</param>
        public void StartTrial(
            RQ2Condition condition,
            float targetLinearSpeedMs = float.NaN,
            float targetAngularSpeedDegS = float.NaN)
        {
            if (condition == RQ2Condition.None)
                throw new ArgumentOutOfRangeException(nameof(condition), "RQ2 试次必须指定有效运动场景。");
            if (_currentTrialId > 0)
            {
                EgoAnchorLog.For<RQ2TrialSelector>().Warning(
                    $"RQ2 试次仍在进行，忽略新的开始请求：active_id={_currentTrialId} requested={condition.ToLogString()}");
                return;
            }

            _lastTrialId++;
            _currentTrialId = _lastTrialId;
            _currentCondition = condition;
            _targetLinearSpeedMs = condition == RQ2Condition.Rotation
                ? float.NaN
                : NormalizeTarget(targetLinearSpeedMs);
            _targetAngularSpeedDegS = condition == RQ2Condition.Rotation
                ? NormalizeTarget(targetAngularSpeedDegS)
                : float.NaN;
            _trialStartMonoMs = CurrentMonoMs();

            EgoAnchorLog.For<RQ2TrialSelector>().Info(
                $"RQ2 试次开始：id={_currentTrialId} condition={_currentCondition.ToLogString()}");
        }

        /// <summary>
        /// 结束当前试次并恢复空闲上下文；已分配的试次编号计数保持不变。
        /// </summary>
        public void EndTrial()
        {
            if (_currentTrialId < 0) return;

            int endedTrialId = _currentTrialId;
            ClearCurrentContext();
            EgoAnchorLog.For<RQ2TrialSelector>().Info($"RQ2 试次结束：id={endedTrialId}");
        }

        /// <summary>
        /// 清空试次上下文并重置 session 内编号；应绑定到 EvalSession 的 sessionStarted 事件。
        /// </summary>
        public void ResetSession()
        {
            _lastTrialId = 0;
            ClearCurrentContext();
            EgoAnchorLog.For<RQ2TrialSelector>().Info("RQ2 试次上下文已按新 session 重置");
        }

        /// <summary>清除当前试次字段，但保留 session 内编号计数。</summary>
        private void ClearCurrentContext()
        {
            _currentTrialId = -1;
            _currentCondition = RQ2Condition.None;
            _targetLinearSpeedMs = float.NaN;
            _targetAngularSpeedDegS = float.NaN;
            _trialStartMonoMs = double.NaN;
        }

        /// <summary>将非法或负目标速度归一化为 NaN，避免日志写入误导性数值。</summary>
        private static float NormalizeTarget(float value)
        {
            return float.IsNaN(value) || float.IsInfinity(value) || value < 0f
                ? float.NaN
                : value;
        }

        /// <summary>计算给定单调时钟起点到当前时刻的秒数。</summary>
        private static double ElapsedSeconds(double startMonoMs)
        {
            return double.IsNaN(startMonoMs)
                ? 0.0
                : Math.Max(0.0, (CurrentMonoMs() - startMonoMs) / 1000.0);
        }

        /// <summary>读取 Unity 单调时钟并转换为毫秒。</summary>
        private static double CurrentMonoMs()
        {
            return Time.realtimeSinceStartupAsDouble * 1000.0;
        }
    }
}
