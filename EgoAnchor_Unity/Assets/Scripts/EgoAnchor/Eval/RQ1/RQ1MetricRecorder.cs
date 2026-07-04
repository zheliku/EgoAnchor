using System;
using EgoAnchor.Diagnostics;
using UnityEngine;

namespace EgoAnchor.Eval.RQ1
{
    /// <summary>
    /// RQ1 指标标记记录器。
    /// <para>
    /// 记录用户按键标记的时间戳和指标类型，用于后续 Python 分析。
    /// </para>
    /// </summary>
    public sealed class RQ1MetricRecorder : MonoBehaviour
    {
        // ── State ──

        private RQ1MetricType _currentMetric = RQ1MetricType.None;
        private double _metricStartMonoMs;
        private bool _recording;

        // ── Events ──

        /// <summary>指标变化事件（新指标类型，开始时间）。</summary>
        public event Action<RQ1MetricType, double> MetricChanged;

        // ── Public API ──

        /// <summary>当前标记的指标类型。</summary>
        public RQ1MetricType CurrentMetric => _currentMetric;

        /// <summary>当前指标持续时间（秒）。</summary>
        public double CurrentMetricDuration
        {
            get
            {
                if (_currentMetric == RQ1MetricType.None) return 0.0;
                double nowMs = Time.realtimeSinceStartupAsDouble * 1000.0;
                return (nowMs - _metricStartMonoMs) / 1000.0;
            }
        }

        /// <summary>是否正在录制。</summary>
        public bool IsRecording => _recording;

        /// <summary>开始录制。</summary>
        public void StartRecording()
        {
            _recording = true;
            _currentMetric = RQ1MetricType.None;
            _metricStartMonoMs = 0.0;
        }

        /// <summary>停止录制。</summary>
        public void StopRecording()
        {
            _recording = false;
            _currentMetric = RQ1MetricType.None;
            _metricStartMonoMs = 0.0;
        }

        /// <summary>设置当前指标（按键调用）。</summary>
        public void SetMetric(RQ1MetricType type)
        {
            if (!_recording)
            {
                EgoAnchorLog.For<RQ1MetricRecorder>().Warning($"未录制状态下无法设置指标：{type}");
                return;
            }

            if (type == _currentMetric) return;

            _currentMetric = type;
            _metricStartMonoMs = Time.realtimeSinceStartupAsDouble * 1000.0;

            MetricChanged?.Invoke(type, _metricStartMonoMs);

            string displayName = type.GetDisplayName();
            string desc = type.GetDescription();
            int suggestedDuration = type.GetSuggestedDuration();

            if (type == RQ1MetricType.None)
            {
                EgoAnchorLog.For<RQ1MetricRecorder>().Info("清除 RQ1 指标标记");
            }
            else if (suggestedDuration > 0)
            {
                EgoAnchorLog.For<RQ1MetricRecorder>().Info(
                    $"RQ1 指标标记：{displayName} ({desc}) - 建议时长 {suggestedDuration}s");
            }
            else
            {
                EgoAnchorLog.For<RQ1MetricRecorder>().Info(
                    $"RQ1 指标标记：{displayName} ({desc}) - 单次事件");
            }
        }

        /// <summary>清除当前指标标记。</summary>
        public void ClearMetric() => SetMetric(RQ1MetricType.None);

        // ── Unity 生命周期 ──

        private void OnDestroy()
        {
            _recording = false;
            _currentMetric = RQ1MetricType.None;
        }
    }
}
