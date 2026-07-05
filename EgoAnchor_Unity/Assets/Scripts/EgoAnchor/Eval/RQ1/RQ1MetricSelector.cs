using System;
using EgoAnchor.Diagnostics;
using UnityEngine;

namespace EgoAnchor.Eval.RQ1
{
    /// <summary>
    /// RQ1 当前指标选择器。
    /// <para>
    /// 只负责记录「用户当前按键选中的指标类型」和「该指标已持续多久」，供
    /// <see cref="EvalRecorder"/> 每帧读取并写入 output 行的 rq1_metric 字段。
    /// 它<b>不</b>写任何文件、也<b>不</b>拥有录制状态——录制开关的唯一真理是
    /// <see cref="EvalSession"/>。会话开始/结束时由 EvalSession 事件调用
    /// <see cref="ClearMetric"/> 清空标记，保证每段录制从「无标记」开始。
    /// </para>
    /// </summary>
    public sealed class RQ1MetricSelector : MonoBehaviour
    {
        // ── State ──

        private RQ1MetricType _currentMetric = RQ1MetricType.None;
        private double _metricStartMonoMs;

        // ── Events ──

        /// <summary>指标变化事件（新指标类型，开始时间毫秒）。</summary>
        public event Action<RQ1MetricType, double> MetricChanged;

        // ── Public API ──

        /// <summary>当前标记的指标类型。</summary>
        public RQ1MetricType CurrentMetric => _currentMetric;

        /// <summary>当前指标持续时间（秒）；无标记时为 0。</summary>
        public double CurrentMetricDuration
        {
            get
            {
                if (_currentMetric == RQ1MetricType.None) return 0.0;
                double nowMs = Time.realtimeSinceStartupAsDouble * 1000.0;
                return (nowMs - _metricStartMonoMs) / 1000.0;
            }
        }

        /// <summary>设置当前指标（按键 1-5 调用）；与上次相同则忽略。</summary>
        public void SetMetric(RQ1MetricType type)
        {
            if (type == _currentMetric) return;

            _currentMetric = type;
            _metricStartMonoMs = Time.realtimeSinceStartupAsDouble * 1000.0;
            MetricChanged?.Invoke(type, _metricStartMonoMs);

            if (type == RQ1MetricType.None)
            {
                EgoAnchorLog.For<RQ1MetricSelector>().Info("清除 RQ1 指标标记");
                return;
            }

            string displayName = type.GetDisplayName();
            string desc = type.GetDescription();
            int suggestedDuration = type.GetSuggestedDuration();
            if (suggestedDuration > 0)
                EgoAnchorLog.For<RQ1MetricSelector>().Info($"RQ1 指标标记：{displayName} ({desc}) - 建议时长 {suggestedDuration}s");
            else
                EgoAnchorLog.For<RQ1MetricSelector>().Info($"RQ1 指标标记：{displayName} ({desc}) - 单次事件");
        }

        /// <summary>清除当前指标标记；按键 0 手动调用，或 EvalSession 在会话开始/结束时调用。</summary>
        public void ClearMetric() => SetMetric(RQ1MetricType.None);

        // ── Unity 生命周期 ──

        private void OnDestroy() => _currentMetric = RQ1MetricType.None;
    }
}
