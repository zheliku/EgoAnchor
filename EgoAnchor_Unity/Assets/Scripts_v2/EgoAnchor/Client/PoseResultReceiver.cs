using System;
using System.Collections.Concurrent;
using System.Threading;
using System.Threading.Tasks;
using EgoAnchor.Protocol.V1;
using EgoAnchor.V2.Protocol;
using EgoAnchor.V2.Transport;
using NATS.Net;
using UnityEngine;

namespace EgoAnchor.V2.Client
{
    /// <summary>
    /// 订阅 Python -> Unity 的 `egoanchor.v1.pose.result`。
    ///
    /// 处理流程：
    /// 1. 通过 NatsConnection 订阅 pose result bytes；
    /// 2. 解析为 PoseResult protobuf；
    /// 3. has_pose=false 时忽略位姿应用，仅保留后续扩展状态处理空间；
    /// 4. has_pose=true 时把 OpenCV 相机坐标下的 4x4 matrix 转成 Unity Pose；
    /// 5. 触发 OnPoseReceived(pose, frameId)，通常由 FrameAlignedAnchorBridge 接到 FrameAlignedObjectAnchor。
    /// </summary>
    public class PoseResultReceiver : MonoBehaviour
    {
        [SerializeField] private NatsConnection connection;
        [SerializeField] private bool convertFromOpenCvCamera = true;

        public PoseReceivedEvent OnPoseReceived = new PoseReceivedEvent();

        private CancellationTokenSource _cts;
        private readonly ConcurrentQueue<(Pose Pose, long FrameId)> _mainThreadEvents = new ConcurrentQueue<(Pose Pose, long FrameId)>();

        private async void OnEnable()
        {
            _cts = new CancellationTokenSource();
            await StartReceiveLoop(_cts.Token);
        }

        private void OnDisable()
        {
            _cts?.Cancel();
            _cts?.Dispose();
            _cts = null;
        }

        private void Update()
        {
            // NATS 接收循环可能不在 Unity 主线程；所有 UnityEvent 统一在 Update 中触发。
            while (_mainThreadEvents.TryDequeue(out var item))
            {
                OnPoseReceived?.Invoke(item.Pose, item.FrameId);
            }
        }

        private async Task StartReceiveLoop(CancellationToken cancellationToken)
        {
            if (connection == null)
            {
                Debug.LogWarning("[EgoAnchorV2] PoseResultReceiver missing NatsConnection.", this);
                return;
            }

            try
            {
                NatsClient client = await connection.ConnectAsync(cancellationToken);
                // 注意：NATS callback/async loop 不一定等同于 Unity 主线程。
                // HandlePoseResultBytes 只解析并入队，UnityEvent 在 Update 中触发。
                await foreach (var msg in client.SubscribeAsync<byte[]>(SubjectNames.PoseResult, cancellationToken: cancellationToken))
                {
                    HandlePoseResultBytes(msg.Data);
                }
            }
            catch (OperationCanceledException)
            {
            }
            catch (Exception e)
            {
                Debug.LogError($"[EgoAnchorV2] Pose receive loop failed: {e.Message}", this);
            }
        }

        private void HandlePoseResultBytes(byte[] payload)
        {
            if (payload == null || payload.Length == 0)
            {
                return;
            }

            PoseResult result = PoseResult.Parser.ParseFrom(payload);
            // has_pose=false 是合法状态包，不是错误；Unity 不应应用空 pose。
            if (!result.HasPose || result.PoseMatrixCvCamera == null || result.PoseMatrixCvCamera.Values.Count != 16)
            {
                return;
            }

            if (!TryPoseFromMatrix(result.PoseMatrixCvCamera, out Pose pose))
            {
                return;
            }

            if (convertFromOpenCvCamera && !TryConvertOpenCvPoseToUnity(pose, out pose))
            {
                return;
            }

            _mainThreadEvents.Enqueue((pose, result.Header.FrameId));
        }

        private static bool TryPoseFromMatrix(global::EgoAnchor.Protocol.V1.Matrix4x4 matrix, out Pose pose)
        {
            // Protobuf matrix 约定为 4x4 行优先展平。
            // position 取第 4 列；旋转列向量取 x/y/z 轴方向。
            var values = matrix.Values;
            Vector3 position = new Vector3((float)values[3], (float)values[7], (float)values[11]);
            Vector3 forward = new Vector3((float)values[2], (float)values[6], (float)values[10]);
            Vector3 up = new Vector3((float)values[1], (float)values[5], (float)values[9]);
            if (forward.sqrMagnitude < 1e-12f || up.sqrMagnitude < 1e-12f)
            {
                pose = Pose.identity;
                return false;
            }

            pose = new Pose(position, Quaternion.LookRotation(forward, up));
            return true;
        }

        private static bool TryConvertOpenCvPoseToUnity(Pose inputPose, out Pose outputPose)
        {
            // Python/FoundationPose 输出 OpenCV camera 坐标：x右、y下、z前。
            // Unity 使用 x右、y上、z前，所以位置和旋转都需要绕 y 轴符号翻转。
            Vector3 forwardInput = inputPose.rotation * Vector3.forward;
            Vector3 forward = new Vector3(forwardInput.x, -forwardInput.y, forwardInput.z);
            Vector3 upInput = inputPose.rotation * Vector3.down;
            Vector3 up = new Vector3(upInput.x, -upInput.y, upInput.z);
            if (forward.sqrMagnitude < 1e-12f || up.sqrMagnitude < 1e-12f)
            {
                outputPose = Pose.identity;
                return false;
            }

            Vector3 position = inputPose.position;
            outputPose = new Pose(new Vector3(position.x, -position.y, position.z), Quaternion.LookRotation(forward, up));
            return true;
        }
    }
}
