using System.Collections.Generic;
using EgoAnchor.Protocol.Generated;
using UnityEngine;

namespace EgoAnchor.Anchor
{
    /// <summary>
    /// PoseResult 分发中心。
    ///
    /// 一个 Python 目标 pose 流可以同时驱动多个 Unity anchor runtime：
    /// - raw baseline runtime：不挂 processor，或 DynamicObjectAnchor 读取 Raw。
    /// - smoothed runtime：挂 Kalman/LowPass 等 processor，DynamicObjectAnchor 读取 Smoothed。
    ///
    /// 因此 PoseResultReceiver 不应该绑定单个 PoseToAnchorRuntime；它只负责解码网络消息，
    /// 再把同一条 PoseResult 广播给本 hub。hub 在主线程顺序调用多个 runtime，保证
    /// baseline 和 smoothed 对照使用完全相同的输入 pose。
    /// </summary>
    public sealed class PoseResultHub : MonoBehaviour
    {
        /// <summary>接收同一 PoseResult 的 runtime 列表。</summary>
        [Header("Targets")]
        [Tooltip("接收同一 PoseResult 的 runtime 列表。用于同时驱动 raw baseline 与 smoothed 输出。")]
        [SerializeField] private List<PoseToAnchorRuntime> runtimes = new List<PoseToAnchorRuntime>();

        /// <summary>是否在 Awake 时自动收集子物体中的 runtime。</summary>
        [Tooltip("列表为空时，是否自动收集当前 GameObject 子层级中的 PoseToAnchorRuntime。建议显式绑定，自动收集只用于快速调试。")]
        [SerializeField] private bool autoCollectChildrenWhenEmpty = true;

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

        /// <summary>累计 runtime 成功对齐次数。</summary>
        private int aligned;

        /// <summary>累计 runtime 返回 no pose 次数。</summary>
        private int noPose;

        /// <summary>累计 runtime 对齐/矩阵失败次数。</summary>
        private int failed;

        /// <summary>上次打印统计时的接收数量。</summary>
        private int lastLoggedReceived;

        /// <summary>只读 runtime 数。</summary>
        public int RuntimeCount => runtimes?.Count ?? 0;

        /// <summary>
        /// Unity Awake：按需自动收集 runtime。
        /// </summary>
        private void Awake()
        {
            EnsureRuntimeList();
        }

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

            if (runtimes == null || runtimes.Count == 0)
            {
                failed++;
                MaybeLogStats();
                return;
            }

            foreach (PoseToAnchorRuntime runtime in runtimes)
            {
                if (runtime == null)
                {
                    continue;
                }

                PoseToAnchorRuntime.AcceptResult acceptResult = runtime.AcceptPoseResult(result);
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

            MaybeLogStats();
        }

        /// <summary>
        /// 确保 runtime 列表可用，并在空列表时按需从子层级自动收集。
        /// </summary>
        private void EnsureRuntimeList()
        {
            if (runtimes == null)
            {
                runtimes = new List<PoseToAnchorRuntime>();
            }

            if (runtimes.Count == 0 && autoCollectChildrenWhenEmpty)
            {
                runtimes.AddRange(GetComponentsInChildren<PoseToAnchorRuntime>(includeInactive: false));
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

            if (received > 0 && received - lastLoggedReceived >= statsIntervalMessages)
            {
                lastLoggedReceived = received;
                Debug.Log(
                    $"[PoseResultHub] received={received}, runtimes={RuntimeCount}, aligned={aligned}, noPose={noPose}, failed={failed}",
                    this
                );
            }
        }
    }
}


