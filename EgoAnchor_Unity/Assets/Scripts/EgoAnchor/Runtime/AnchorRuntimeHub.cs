using System.Collections.Generic;
using System;
using EgoAnchor.Diagnostics;
using EgoAnchor.Protocol.Generated;
using UnityEngine;

namespace EgoAnchor.Runtime
{
    /// <summary>
    /// Anchor runtime 分发中心。
    ///
    /// 一个 Python 目标 pose 流可以同时驱动多个 Unity anchor runtime（对比多种模块组合）：
    /// - raw 参照 runtime：ConstantVelocityModel + RawPassthroughStrategy（零阶保持）。
    /// - 平滑 runtime：KalmanModel/OneEuroModel + BlendStrategy/DelayedInterpStrategy。
    ///
    /// 因此网络 receiver 不应该各自绑定单个 PoseToAnchorRuntime；它们只负责解码
    /// Protobuf，再把 PoseResult、AnchorStatusEvent、ServerHeartbeat 交给本 hub。
    /// hub 在主线程顺序调用多个 runtime，保证所有对照变体使用完全相同的
    /// pose/status/heartbeat 输入。
    /// </summary>
    public sealed class AnchorRuntimeHub : MonoBehaviour
    {
        /// <summary>统一日志通道。</summary>
        private static readonly EgoAnchorLog.Channel Log = EgoAnchorLog.For<AnchorRuntimeHub>();

        /// <summary>接收 pose/status/heartbeat 的 runtime 列表。</summary>
        [Header("Targets")]
        [Tooltip("接收 pose/status/heartbeat 的 runtime 列表。用于同时驱动 raw baseline、smoothed 输出和 reliability-aware policy。")]
        [SerializeField] private List<PoseToAnchorRuntime> runtimes = new List<PoseToAnchorRuntime>();

        /// <summary>是否输出聚合统计。</summary>
        [Header("Debug")]
        [Tooltip("是否周期性输出分发统计。")]
        [SerializeField] private bool logStats = true;

        /// <summary>统计输出间隔。</summary>
        [Tooltip("每分发多少条 PoseResult 输出一次统计。")]
        [Min(1)]
        [SerializeField] private int statsIntervalMessages = 120;

        /// <summary>累计接收 PoseResult 数。</summary>
        private int received;

        /// <summary>累计接收 AnchorStatusEvent 数。</summary>
        private int receivedStatusEvents;

        /// <summary>累计接收 ServerHeartbeat 数。</summary>
        private int receivedHeartbeats;

        /// <summary>累计 runtime 成功对齐次数。</summary>
        private int aligned;

        /// <summary>累计 runtime 返回 no pose 次数。</summary>
        private int noPose;

        /// <summary>累计 runtime 对齐/矩阵失败次数。</summary>
        private int failed;

        /// <summary>累计分发 AnchorStatusEvent 的 runtime 次数。</summary>
        private int statusDispatched;

        /// <summary>累计分发 ServerHeartbeat 的 runtime 次数。</summary>
        private int heartbeatDispatched;

        /// <summary>PoseResult 分发时 runtime 抛出的异常次数。</summary>
        private int poseDispatchExceptions;

        /// <summary>AnchorStatusEvent 分发时 runtime 抛出的异常次数。</summary>
        private int statusDispatchExceptions;

        /// <summary>ServerHeartbeat 分发时 runtime 抛出的异常次数。</summary>
        private int heartbeatDispatchExceptions;

        /// <summary>上次打印统计时的总输入消息数量。</summary>
        private int lastLoggedTotalMessages;

        /// <summary>最近一条 PoseResult 携带的 Python 端 session_id。</summary>
        private string latestPythonSessionId = string.Empty;

        /// <summary>当前实际可派发的 runtime 数；忽略 Inspector 列表中的空槽位。</summary>
        public int RuntimeCount => CountActiveRuntimes();

        /// <summary>
        /// 最近一条 PoseResult 头部携带的 Python eval session_id。
        ///
        /// Python 启用 eval session 时，会把共享 session 目录名（例如
        /// <c>20260617_025334_controller_right</c>）写进每条 PoseResult 的
        /// MessageHeader.session_id。Unity eval 录制据此命名本地目录，实现跨机器
        /// （Python 在 Linux 服务器、Unity 在本地）的 session 配对，无需共享文件系统。
        /// 尚未收到任何 pose 时为空字符串。
        /// </summary>
        public string LatestPythonSessionId => latestPythonSessionId;

        /// <summary>
        /// Inspector 修改时确保列表非空。
        /// </summary>
        private void OnValidate()
        {
            if (runtimes == null)
            {
                runtimes = new List<PoseToAnchorRuntime>();
            }
        }

        /// <summary>
        /// 注册一个 runtime。可由动态创建的 anchor 调用。
        /// </summary>
        /// <param name="runtime">待接收 PoseResult 的 runtime。</param>
        public void Register(PoseToAnchorRuntime runtime)
        {
            if (runtime == null)
            {
                return;
            }

            if (runtimes == null)
            {
                runtimes = new List<PoseToAnchorRuntime>();
            }

            if (!runtimes.Contains(runtime))
            {
                runtimes.Add(runtime);
            }
        }

        /// <summary>
        /// 取消注册一个 runtime。
        /// </summary>
        /// <param name="runtime">待移除的 runtime。</param>
        public void Unregister(PoseToAnchorRuntime runtime)
        {
            if (runtime == null || runtimes == null)
            {
                return;
            }

            runtimes.Remove(runtime);
        }

        /// <summary>
        /// 把一条 PoseResult 分发给所有 runtime。
        /// </summary>
        /// <param name="result">Python 发布的 camera-space PoseResult。</param>
        public void Publish(PoseResult result)
        {
            EnsureRuntimeList();
            received++;

            if (result != null && result.Header != null && !string.IsNullOrEmpty(result.Header.SessionId))
            {
                latestPythonSessionId = result.Header.SessionId;
            }

            int activeRuntimeCount = 0;
            foreach (PoseToAnchorRuntime runtime in runtimes)
            {
                if (runtime == null)
                {
                    continue;
                }

                activeRuntimeCount++;
                if (!TryAcceptPose(runtime, result, out PoseToAnchorRuntime.AcceptResult acceptResult))
                {
                    failed++;
                    continue;
                }

                switch (acceptResult)
                {
                    case PoseToAnchorRuntime.AcceptResult.Aligned:
                        aligned++;
                        break;
                    case PoseToAnchorRuntime.AcceptResult.NoPose:
                        noPose++;
                        break;
                    case PoseToAnchorRuntime.AcceptResult.AlignFailed:
                    case PoseToAnchorRuntime.AcceptResult.InvalidMatrix:
                        failed++;
                        break;
                }
            }

            if (activeRuntimeCount == 0)
            {
                failed++;
            }

            MaybeLogStats();
        }

        /// <summary>
        /// 把一条 AnchorStatusEvent 分发给所有 runtime。
        /// </summary>
        /// <param name="status">Python 发布的 AnchorStatusEvent。</param>
        /// <returns>实际通知的 runtime 数量。</returns>
        public int PublishStatus(AnchorStatusEvent status)
        {
            EnsureRuntimeList();
            if (status == null)
            {
                return 0;
            }

            receivedStatusEvents++;
            if (runtimes.Count == 0)
            {
                MaybeLogStats();
                return 0;
            }

            int count = 0;
            foreach (PoseToAnchorRuntime runtime in runtimes)
            {
                if (runtime == null)
                {
                    continue;
                }

                if (!TryNotifyStatus(runtime, status))
                {
                    continue;
                }

                count++;
            }

            statusDispatched += count;
            MaybeLogStats();
            return count;
        }

        /// <summary>
        /// 把一条 ServerHeartbeat 分发给所有 runtime。
        /// </summary>
        /// <param name="heartbeat">Python 发布的 ServerHeartbeat。</param>
        /// <returns>实际通知的 runtime 数量。</returns>
        public int PublishHeartbeat(ServerHeartbeat heartbeat)
        {
            EnsureRuntimeList();
            if (heartbeat == null)
            {
                return 0;
            }

            receivedHeartbeats++;
            if (runtimes.Count == 0)
            {
                MaybeLogStats();
                return 0;
            }

            int count = 0;
            foreach (PoseToAnchorRuntime runtime in runtimes)
            {
                if (runtime == null)
                {
                    continue;
                }

                if (!TryNotifyHeartbeat(runtime, heartbeat))
                {
                    continue;
                }

                count++;
            }

            heartbeatDispatched += count;
            MaybeLogStats();
            return count;
        }

        /// <summary>
        /// 确保 runtime 列表可用。
        /// </summary>
        private void EnsureRuntimeList()
        {
            if (runtimes == null)
            {
                runtimes = new List<PoseToAnchorRuntime>();
            }
        }

        /// <summary>
        /// 统计实际可派发的 runtime，避免把 Inspector 中遗留的空槽位算作有效目标。
        /// </summary>
        private int CountActiveRuntimes()
        {
            if (runtimes == null)
            {
                return 0;
            }

            int count = 0;
            foreach (PoseToAnchorRuntime runtime in runtimes)
            {
                if (runtime != null)
                {
                    count++;
                }
            }

            return count;
        }

        /// <summary>
        /// 安全分发 PoseResult，避免单个 runtime 异常阻断其他 baseline/runtime。
        /// </summary>
        private bool TryAcceptPose(PoseToAnchorRuntime runtime, PoseResult result, out PoseToAnchorRuntime.AcceptResult acceptResult)
        {
            try
            {
                acceptResult = runtime.AcceptPoseResult(result);
                return true;
            }
            catch (Exception ex)
            {
                acceptResult = PoseToAnchorRuntime.AcceptResult.AlignFailed;
                poseDispatchExceptions++;
                LogDispatchException("PoseResult", poseDispatchExceptions, ex);
                return false;
            }
        }

        /// <summary>
        /// 安全分发 AnchorStatusEvent，避免单个 runtime 异常阻断其他 runtime。
        /// </summary>
        private bool TryNotifyStatus(PoseToAnchorRuntime runtime, AnchorStatusEvent status)
        {
            try
            {
                runtime.NotifyStatusEvent(status);
                return true;
            }
            catch (Exception ex)
            {
                statusDispatchExceptions++;
                LogDispatchException("AnchorStatusEvent", statusDispatchExceptions, ex);
                return false;
            }
        }

        /// <summary>
        /// 安全分发 ServerHeartbeat，避免单个 runtime 异常阻断其他 runtime。
        /// </summary>
        private bool TryNotifyHeartbeat(PoseToAnchorRuntime runtime, ServerHeartbeat heartbeat)
        {
            try
            {
                runtime.NotifyHeartbeat(heartbeat);
                return true;
            }
            catch (Exception ex)
            {
                heartbeatDispatchExceptions++;
                LogDispatchException("ServerHeartbeat", heartbeatDispatchExceptions, ex);
                return false;
            }
        }

        /// <summary>
        /// 限频输出 runtime 分发异常，保留诊断但避免每帧刷屏。
        /// </summary>
        private void LogDispatchException(string payloadName, int exceptionCount, Exception ex)
        {
            int interval = Mathf.Max(1, statsIntervalMessages);
            if (exceptionCount <= 3 || exceptionCount % interval == 0)
            {
                Log.Error($"{payloadName} dispatch exception count={exceptionCount}: {ex}", this);
            }
        }

        /// <summary>
        /// 周期性输出分发统计。
        /// </summary>
        private void MaybeLogStats()
        {
            if (!logStats)
            {
                return;
            }

            int totalMessages = received + receivedStatusEvents + receivedHeartbeats;
            if (totalMessages > 0 && totalMessages - lastLoggedTotalMessages >= statsIntervalMessages)
            {
                lastLoggedTotalMessages = totalMessages;
                Log.Info(
                    $"pose={received}, status={receivedStatusEvents}, heartbeat={receivedHeartbeats}, runtimes={RuntimeCount}, aligned={aligned}, noPose={noPose}, " +
                    $"failed={failed}, statusDispatched={statusDispatched}, heartbeatDispatched={heartbeatDispatched}, " +
                    $"poseDispatchExceptions={poseDispatchExceptions}, statusDispatchExceptions={statusDispatchExceptions}, " +
                    $"heartbeatDispatchExceptions={heartbeatDispatchExceptions}",
                    this
                );
            }
        }
    }
}


