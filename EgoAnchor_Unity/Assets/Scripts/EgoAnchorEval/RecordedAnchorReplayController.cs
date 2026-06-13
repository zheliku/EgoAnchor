using System.Collections.Generic;
using UnityEngine;

namespace EgoAnchorEval
{
    /// <summary>
    /// Unity replay 场景的轻量控制器，统一控制 runtime replay source 和 trajectory player。
    /// </summary>
    public sealed class RecordedAnchorReplayController : MonoBehaviour
    {
        /// <summary>需要同步控制的 runtime replay source。</summary>
        [Header("Replay Targets")]
        [Tooltip("需要同步控制的 RecordedAnchorReplaySource 列表。每个 source 通常对应一个要重跑策略的 PoseToAnchorRuntime。")]
        [SerializeField] private List<RecordedAnchorReplaySource> replaySources = new List<RecordedAnchorReplaySource>();

        /// <summary>需要同步控制的轨迹播放器。</summary>
        [Tooltip("需要同步控制的 AnchorTrajectoryPlayer 列表。每个 player 通常播放一个策略 label 的 stable 轨迹。")]
        [SerializeField] private List<AnchorTrajectoryPlayer> trajectoryPlayers = new List<AnchorTrajectoryPlayer>();

        /// <summary>是否在 Start 时自动播放。</summary>
        [Header("Playback")]
        [Tooltip("是否在 Start 时自动播放所有 source/player。")]
        [SerializeField] private bool playOnStart;

        /// <summary>是否循环播放。</summary>
        [Tooltip("播完后是否循环播放。该设置会下发给所有 source/player。")]
        [SerializeField] private bool loop;

        /// <summary>播放速度倍率。</summary>
        [Tooltip("播放速度倍率。该设置会下发给所有 source/player。")]
        [Min(0.01f)]
        [SerializeField] private float playbackSpeed = 1.0f;

        /// <summary>Unity Start：按需自动播放。</summary>
        private void Start()
        {
            ApplyPlaybackOptions();
            if (playOnStart)
            {
                PlayAll();
            }
        }

        /// <summary>Inspector 修改时保持列表和速度有效。</summary>
        private void OnValidate()
        {
            if (replaySources == null)
            {
                replaySources = new List<RecordedAnchorReplaySource>();
            }

            if (trajectoryPlayers == null)
            {
                trajectoryPlayers = new List<AnchorTrajectoryPlayer>();
            }

            playbackSpeed = Mathf.Max(0.01f, playbackSpeed);
        }

        /// <summary>播放全部回放组件。</summary>
        public void PlayAll()
        {
            ApplyPlaybackOptions();
            ForEachSource(source => source.Play());
            ForEachPlayer(player => player.Play());
        }

        /// <summary>暂停全部回放组件。</summary>
        public void PauseAll()
        {
            ForEachSource(source => source.Pause());
            ForEachPlayer(player => player.Pause());
        }

        /// <summary>停止全部回放组件并回到起点。</summary>
        public void StopAll()
        {
            ForEachSource(source => source.Stop());
            ForEachPlayer(player => player.Stop());
        }

        /// <summary>从起点重新播放全部回放组件。</summary>
        public void RestartAll()
        {
            ApplyPlaybackOptions();
            ForEachSource(source => source.Restart());
            ForEachPlayer(player => player.Restart());
        }

        /// <summary>向所有子组件下发当前播放参数。</summary>
        private void ApplyPlaybackOptions()
        {
            float speed = Mathf.Max(0.01f, playbackSpeed);
            ForEachSource(source =>
            {
                source.PlaybackSpeed = speed;
                source.Loop = loop;
            });
            ForEachPlayer(player =>
            {
                player.PlaybackSpeed = speed;
                player.Loop = loop;
            });
        }

        /// <summary>遍历非空 replay source。</summary>
        private void ForEachSource(System.Action<RecordedAnchorReplaySource> action)
        {
            if (action == null || replaySources == null)
            {
                return;
            }

            for (int i = 0; i < replaySources.Count; i++)
            {
                if (replaySources[i] != null)
                {
                    action(replaySources[i]);
                }
            }
        }

        /// <summary>遍历非空 trajectory player。</summary>
        private void ForEachPlayer(System.Action<AnchorTrajectoryPlayer> action)
        {
            if (action == null || trajectoryPlayers == null)
            {
                return;
            }

            for (int i = 0; i < trajectoryPlayers.Count; i++)
            {
                if (trajectoryPlayers[i] != null)
                {
                    action(trajectoryPlayers[i]);
                }
            }
        }
    }
}
