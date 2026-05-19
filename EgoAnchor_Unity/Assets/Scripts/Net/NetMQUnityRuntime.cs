using System;
using NetMQ;
using UnityEngine;

namespace EgoAnchor.Net
{
    /// <summary>
    /// Unity/Editor 中的 NetMQ 生命周期辅助类。
    ///
    /// 这个类现在只保留显式的 Acquire / Release / CleanupNow，
    /// 不再注册任何全局 Play Mode / Domain Reload 钩子。
    /// 这样可以避免“全局管理器”在场景重启时过早干预 NetMQ 状态，
    /// 让真正拥有 socket 的发布器自己决定何时初始化和清理。
    /// </summary>
    public static class NetMQUnityRuntime
    {
        private static readonly object SyncRoot = new object();
        private static int activeLeases;
        private static bool forceDotNetApplied;
        private static bool cleanupInProgress;

        /// <summary>
        /// 创建 NetMQ socket 前调用。返回的 lease 必须在 socket 释放后 Release。
        /// </summary>
        public static void Acquire()
        {
            lock (SyncRoot)
            {
                if (!forceDotNetApplied)
                {
                    AsyncIO.ForceDotNet.Force();
                    NetMQConfig.Linger = TimeSpan.Zero;
                    forceDotNetApplied = true;
                }

                activeLeases++;
            }
        }

        /// <summary>
        /// socket 释放后调用。最后一个 socket 退出时再清理 NetMQ 全局上下文。
        /// </summary>
        public static void Release()
        {
            bool shouldCleanup;
            lock (SyncRoot)
            {
                if (activeLeases > 0)
                {
                    activeLeases--;
                }

                shouldCleanup = activeLeases == 0;
            }

            if (shouldCleanup)
            {
                CleanupNow("last socket released");
            }
        }

        /// <summary>
        /// 强制清理 NetMQ 全局上下文。只在 Play Mode/Domain Reload/Editor 退出边界使用。
        /// </summary>
        public static void CleanupNow(string reason)
        {
            lock (SyncRoot)
            {
                if (cleanupInProgress)
                {
                    return;
                }

                cleanupInProgress = true;
            }

            try
            {
                NetMQConfig.Cleanup(false);
            }
            catch (Exception exc)
            {
                Debug.LogWarning($"[NetMQUnityRuntime] cleanup ignored ({reason}): {exc.Message}");
            }
            finally
            {
                lock (SyncRoot)
                {
                    activeLeases = 0;
                    forceDotNetApplied = false;
                    cleanupInProgress = false;
                }
            }
        }

    }
}