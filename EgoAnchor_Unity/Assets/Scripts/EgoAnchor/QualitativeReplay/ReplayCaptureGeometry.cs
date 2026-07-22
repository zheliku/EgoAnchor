using UnityEngine;

namespace EgoAnchor.QualitativeReplay
{
    /// <summary>定性 replay 使用的 Unity world 到 OpenCV camera-space 坐标转换。</summary>
    public static class ReplayCaptureGeometry
    {
        /// <summary>
        /// 把最终显示 anchor 的 Unity world pose 放到 image-time 左目相机坐标系，
        /// 再按 F*T*F（F=diag(1,-1,1,1)）转换为 OpenCV x-right/y-down/z-forward。
        /// 最终显示 pose 已包含 runtime 的 camera/anchor/world 补偿，因此这里不得再逆补偿。
        /// </summary>
        /// <param name="cameraWorldPose">背景 JPEG 的 image-time 左目 world pose。</param>
        /// <param name="displayWorldPose">某方法在同一 image-time 渲染帧的最终显示 world pose。</param>
        /// <returns>row-major OpenCV object-in-camera 4x4。</returns>
        public static float[] ToOpenCvObjectMatrix(Pose cameraWorldPose, Pose displayWorldPose)
        {
            Matrix4x4 cameraToWorld = Matrix4x4.TRS(
                cameraWorldPose.position,
                cameraWorldPose.rotation,
                Vector3.one);
            Matrix4x4 objectToWorld = Matrix4x4.TRS(
                displayWorldPose.position,
                displayWorldPose.rotation,
                Vector3.one);
            Matrix4x4 unityObjectInCamera = cameraToWorld.inverse * objectToWorld;
            float[] signs = { 1f, -1f, 1f, 1f };
            float[] values = new float[16];
            for (int row = 0; row < 4; row++)
            {
                for (int column = 0; column < 4; column++)
                {
                    values[row * 4 + column] = signs[row]
                        * unityObjectInCamera[row, column]
                        * signs[column];
                }
            }
            return values;
        }
    }
}
