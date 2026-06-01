using UnityEngine;

namespace EgoAnchorEval
{
    /// <summary>
    /// 左/右手柄到 Unity 世界系 GT pose 的提供者；GT 只进入评估日志，不进入锚定管线。
    /// </summary>
    public sealed class ControllerGroundTruthProvider : MonoBehaviour
    {
        /// <summary>场景中的 OVRCameraRig，用于把 OVRInput 局部位姿变换到 Unity 世界系。</summary>
        [Tooltip("场景中的 OVRCameraRig，用于把手柄局部位姿变到 Unity 世界系。")]
        [SerializeField] private OVRCameraRig cameraRig;

        /// <summary>本 session 追踪的手柄，必须与 Python 对象配置和 manifest 一致。</summary>
        [Tooltip("本 session 追踪的手柄：必须与 Python --object controller_left/right 及 manifest gt_source 三者一致。")]
        [SerializeField] private OVRInput.Controller controller = OVRInput.Controller.RTouch;

        /// <summary>当前配置的 OVRInput 手柄。</summary>
        public OVRInput.Controller Controller => controller;

        /// <summary>
        /// 尝试读取手柄 Unity 世界系 pose 和追踪状态。
        /// </summary>
        /// <param name="worldPose">成功时输出手柄世界系 pose。</param>
        /// <param name="tracked">位置和朝向是否都被 OVRInput 标记为 tracked。</param>
        /// <returns>是否具备可用的 camera rig/trackingSpace 来计算世界系 pose。</returns>
        public bool TryGetWorldPose(out Pose worldPose, out bool tracked)
        {
            worldPose = Pose.identity;
            tracked = false;
            if (cameraRig == null || cameraRig.trackingSpace == null)
            {
                return false;
            }

            Vector3 localPos = OVRInput.GetLocalControllerPosition(controller);
            Quaternion localRot = OVRInput.GetLocalControllerRotation(controller);
            Transform space = cameraRig.trackingSpace;
            worldPose = new Pose(space.TransformPoint(localPos), space.rotation * localRot);
            tracked = OVRInput.GetControllerPositionTracked(controller)
                && OVRInput.GetControllerOrientationTracked(controller);
            return true;
        }
    }
}
