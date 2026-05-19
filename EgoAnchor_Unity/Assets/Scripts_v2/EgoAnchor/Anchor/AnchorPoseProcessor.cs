using UnityEngine;

namespace EgoAnchor.V2.Anchor
{
    /// <summary>
    /// v2 anchor pose 处理器基类。
    ///
    /// Pose 是 struct，不能依赖事件参数被监听器原地修改。因此所有会改变 anchor pose 的模块
    /// 都应继承本类，并由 PoseToAnchorRuntime 按列表顺序调用，每个处理器显式返回处理后的 Pose。
    ///
    /// 处理器只处理 Unity world pose，不订阅 NATS，不解码 Protobuf，不访问 Quest camera。
    /// 这样 raw pose、Kalman、low-pass、未来 One Euro / reliability-aware controller 可以自由组合。
    /// </summary>
    public abstract class AnchorPoseProcessor : MonoBehaviour
    {
        [Tooltip("是否启用该处理器。关闭后直接透传输入 pose，便于实验中快速切换处理链。")]
        [SerializeField] private bool processorEnabled = true;

        /// <summary>处理器当前是否参与处理链。</summary>
        public bool ProcessorEnabled => processorEnabled;

        /// <summary>
        /// 处理输入 pose，并返回输出 pose。
        /// </summary>
        /// <param name="inputPose">上游输入 pose，Unity world 坐标。</param>
        /// <param name="frameId">该 pose 对应的 stereo frame_id。</param>
        /// <param name="sampleTime">当前 Unity 单调时间，单位秒。</param>
        public Pose Process(Pose inputPose, long frameId, double sampleTime)
        {
            if (!processorEnabled || !isActiveAndEnabled)
            {
                return inputPose;
            }

            return ProcessPose(inputPose, frameId, sampleTime);
        }

        /// <summary>派生类实现具体滤波/预测/gate 逻辑。</summary>
        protected abstract Pose ProcessPose(Pose inputPose, long frameId, double sampleTime);

        /// <summary>
        /// 重置内部状态。PoseToAnchorRuntime 可在重新捕获目标或用户手动 reset 时调用。
        /// </summary>
        public virtual void ResetProcessor() { }
    }
}
