using UnityEngine;

namespace EgoAnchor.Processors
{
    /// <summary>
    /// anchor pose 处理器基类。
    ///
    /// Pose 是值类型，不能依赖事件参数被监听器原地修改。因此所有会改变 anchor pose 的模块
    /// 都应继承本类，并由 PoseToAnchorRuntime 按列表顺序调用，每个处理器显式返回处理后的 Pose。
    ///
    /// 处理器只处理 Unity world pose，不订阅 NATS，不解码 Protobuf，不访问 Quest camera。
    /// 这样 raw pose、Kalman、low-pass、未来 One Euro / reliability-aware controller 可以自由组合。
    /// </summary>
    public abstract class AnchorPoseProcessor : MonoBehaviour
    {
        /// <summary>是否启用该处理器。</summary>
        [Tooltip("是否启用该处理器。关闭后直接透传输入 pose，便于实验中快速切换处理链。")]
        [SerializeField] private bool processorEnabled = true;

        /// <summary>处理器当前是否参与处理链。</summary>
        public bool ProcessorEnabled => processorEnabled;

        /// <summary>是否已经收到过第一条样本。</summary>
        private bool hasSample;

        /// <summary>上一帧样本时间，单位秒。</summary>
        private double lastSampleTime;

        /// <summary>
        /// 处理输入 pose，并返回输出 pose。
        /// </summary>
        /// <param name="inputPose">上游输入 pose，Unity world 坐标。</param>
        /// <param name="frameId">该 pose 对应的 stereo frame_id。</param>
        /// <param name="sampleTime">当前 Unity 单调时间，单位秒。</param>
        /// <returns>处理后的 Unity world pose。</returns>
        public Pose Process(Pose inputPose, long frameId, double sampleTime)
        {
            if (!processorEnabled || !isActiveAndEnabled)
            {
                return inputPose;
            }

            return ProcessPose(inputPose, frameId, sampleTime);
        }

        /// <summary>
        /// 派生类实现具体滤波、预测或 gate 逻辑。
        /// </summary>
        /// <param name="inputPose">上游输入 pose，Unity world 坐标。</param>
        /// <param name="frameId">该 pose 对应的 stereo frame_id。</param>
        /// <param name="sampleTime">当前 Unity 单调时间，单位秒。</param>
        /// <returns>处理后的 Unity world pose。</returns>
        protected abstract Pose ProcessPose(Pose inputPose, long frameId, double sampleTime);

        /// <summary>
        /// 处理首次样本：初始化派生类状态，并按需直接返回贴合后的 pose。
        /// </summary>
        /// <param name="inputPose">首次输入 pose。</param>
        /// <param name="sampleTime">当前 Unity 单调时间，单位秒。</param>
        /// <param name="snapOnFirstPose">是否首次直接贴合。</param>
        /// <param name="outputPose">首次贴合输出。</param>
        /// <returns>是否已完成处理并应直接返回 outputPose。</returns>
        protected bool TryHandleFirstSample(in Pose inputPose, double sampleTime, bool snapOnFirstPose, out Pose outputPose)
        {
            outputPose = default;
            if (hasSample)
            {
                return false;
            }

            OnFirstSample(inputPose, sampleTime);
            lastSampleTime = sampleTime;
            hasSample = true;
            outputPose = CurrentPose;
            return snapOnFirstPose;
        }

        /// <summary>
        /// 计算与上一帧的时间间隔，并更新上一帧样本时间。
        /// </summary>
        /// <param name="sampleTime">当前 Unity 单调时间，单位秒。</param>
        /// <returns>采样间隔，单位秒。</returns>
        protected float ConsumeDeltaTime(double sampleTime)
        {
            float dt = Mathf.Max((float)(sampleTime - lastSampleTime), 1e-5f);
            lastSampleTime = sampleTime;
            return dt;
        }

        /// <summary>
        /// 派生类在首次样本到达时初始化自身滤波状态。
        /// </summary>
        /// <param name="inputPose">首次输入 pose。</param>
        /// <param name="sampleTime">当前 Unity 单调时间，单位秒。</param>
        protected virtual void OnFirstSample(in Pose inputPose, double sampleTime)
        {
        }

        /// <summary>派生类当前输出 pose，用于首次 snap。</summary>
        protected virtual Pose CurrentPose => Pose.identity;

        /// <summary>
        /// 重置内部状态。PoseToAnchorRuntime 可在重新捕获目标或用户手动 reset 时调用。
        /// </summary>
        public virtual void ResetProcessor()
        {
            hasSample = false;
            lastSampleTime = 0.0;
        }
    }
}


