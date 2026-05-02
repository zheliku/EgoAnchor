using UnityEngine;

/// <summary>
/// PoseFollow 位姿处理器基类。
///
/// Pose 是 struct，不能依赖 UnityEvent 参数在监听器中被原地修改。
/// 因此所有会改变 pose 的模块都应继承本类，并由 PoseFollow 按 processors 列表顺序调用，
/// 每个处理器显式返回处理后的 Pose。
/// </summary>
public abstract class PoseProcessor : MonoBehaviour
{
    [Tooltip("是否启用该处理器。关闭后直接透传输入 pose。")]
    [SerializeField] private bool processorEnabled = true;

    public bool ProcessorEnabled => processorEnabled;

    /// <summary>
    /// 处理输入 pose，并返回输出 pose。
    /// </summary>
    /// <param name="inputPose">上游输入 pose，世界坐标。</param>
    /// <param name="frameId">该 pose 对应的 stereo frame_id。</param>
    /// <param name="sampleTime">当前 Unity 单调时间，单位秒。</param>
    public Pose Process(Pose inputPose, long frameId, float sampleTime)
    {
        if (!processorEnabled || !isActiveAndEnabled)
        {
            return inputPose;
        }

        return ProcessPose(inputPose, frameId, sampleTime);
    }

    protected abstract Pose ProcessPose(Pose inputPose, long frameId, float sampleTime);

    /// <summary>
    /// 重置内部状态。PoseFollow 可在收到新目标或手动重置时调用。
    /// </summary>
    public virtual void ResetProcessor() { }
}
